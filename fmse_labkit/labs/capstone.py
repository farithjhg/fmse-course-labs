"""Capstone - High-Assurance Enterprise AI System (Module 16).

Capstone Studio: milestone checklists, reference datasets and templates. No complete implementation
is supplied. The default domain is enterprise financial reconciliation (spec "Capstone Detailed
Specification"); an alternate SRE/MCP variant may be offered.

Each EDP milestone review has its own public validator (check_public("capstone-define", package),
...), and the overall package validator implements the capstone public requirements:
  CAP-01 All critical requirements trace to verification
  CAP-02 No unresolved high-severity security finding              [critical]
  CAP-03 Schema/domain integrity checks pass                       [critical]
  CAP-04 Evaluation suite includes robustness/metamorphic cases
  CAP-05 Release/rollback/runbook complete
  CAP-06 Validation evidence tied to MOEs
Public checks are structural and run on the public reference datasets. Unseen/held-out scenarios
belong to the optional Phase 2 evaluator; the architecture defense is assessed with the rubric in
the portal. Aggregate scores cannot override a critical safety/security gate.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Any, Callable, Dict, List

from ..core import Checker, LAB_SPECS, LabSpec, call_learner, capture_output, register

# --- Reference datasets (intentionally imperfect) -------------------------------------------------

BANK_CSV = """line_id,booking_date,amount,currency,counterparty,reference
B01,01/09/2026,"1.452,00",EUR,Norte Logistics S.L.,INV-2026-0141
B02,02/09/2026,"3.000,00",EUR,Blue Harbor Ltd,INV-88-311
B03,03/09/2026,"552,00",EUR,Kappa Systems GmbH,INV-7781
B04,04/09/2026,"420,00",EUR,Delta Office Supply,INV-3310
B05,04/09/2026,"420,00",EUR,Delta Office Supply,INV-3310
B06,07/09/2026,"2.420,00",EUR,Sigma Cloud BV,INV-9002
B07,08/09/2026,"165,00",EUR,Rho Catering,
B08,09/09/2026,"99,90",EUR,Omega Print,INV-12-9
B09,10/09/2026,"1.250,00",EUR,Iberia Parts SA,INV-55-120
B10,11/09/2026,"780,00",EUR,Lambda Security,INV-6604
B11,12/09/2026,"9.999,00",EUR,Unknown Transfer Co,REF-XX-01
B12,15/09/2026,"310,40",EUR,Tau Ltd,INV-1
"""

LEDGER_CSV = """entry_id,posting_date,amount,currency,vendor_id,invoice_ref
L01,2026-09-01,1452.00,EUR,V01,INV-2026-0141
L02,2026-09-02,3000.00,EUR,V02,INV-88-311
L03,2026-09-03,552.00,EUR,V03,INV-7781
L04,2026-09-04,420.00,EUR,V04,INV-3310
L06,2026-09-07,2420.00,EUR,V06,INV-9002
L07,2026-09-08,165.00,EUR,V07,INV-4410
L08,2026-09-09,99.90,EUR,V08,INV-12-9
L09,2026-09-10,1205.00,EUR,V09,INV-55-120
L10,2026-09-11,780.00,EUR,V99,INV-6604
L11,2026-09-14,640.00,EUR,V11,INV-7002
L12,2026-09-15,310.40,EUR,V12,INV-1
"""

VENDORS_CSV = """vendor_id,name,iban
V01,Norte Logistics S.L.,ES7620770024003102575766
V02,Blue Harbor Ltd,GB33BUKB20201555555555
V03,Kappa Systems GmbH,DE89370400440532013000
V04,Delta Office Supply,ES9121000418450200051332
V06,Sigma Cloud BV,NL91ABNA0417164300
V07,Rho Catering,ES1000492352082414205416
V08,Omega Print,FR1420041010050500013M02606
V09,Iberia Parts SA,ES6621000418401234567891
V11,Phi Components,IT60X0542811101000000123456
V12,Tau Ltd,GB29NWBK60161331926819
"""

EXPECTED_MATCHES = {("B01", "L01"), ("B02", "L02"), ("B03", "L03"), ("B04", "L04"), ("B06", "L06"), ("B08", "L08"), ("B10", "L10"), ("B12", "L12")}
# Planted issues: type -> rows that must appear in that discrepancy's evidence.
PLANTED = {
    "duplicate": {"B05"},
    "missing_reference": {"B07"},
    "amount_mismatch": {"B09", "L09"},
    "unmatched_bank": {"B11"},
    "unmatched_ledger": {"L11"},
    "unknown_vendor": {"L10"},
}


def _rows(text: str) -> List[Dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def load_datasets() -> Dict[str, List[Dict[str, str]]]:
    """Raw rows, exactly as exported: mixed date formats, EU decimal commas, a missing reference, an unknown vendor..."""
    return {"bank": _rows(BANK_CSV), "ledger": _rows(LEDGER_CSV), "vendors": _rows(VENDORS_CSV)}


def write_datasets(folder: str) -> None:
    import pathlib

    p = pathlib.Path(folder)
    p.mkdir(parents=True, exist_ok=True)
    for name, text in (("bank_export.csv", BANK_CSV), ("ledger_entries.csv", LEDGER_CSV), ("vendor_master.csv", VENDORS_CSV)):
        (p / name).write_text(text, encoding="utf-8")


# --- Milestone requirement sets --------------------------------------------------------------------

def _t(text, dim, crit, hint):
    return (text, dim, crit, hint)


MILESTONES: Dict[str, Dict[str, Any]] = {
    "capstone-define": {"title": "DEFINE review", "critical": False, "requirements": {
        "DEF-01": _t("Critical requirements are verifiable", "traceability", True, "Each critical requirement needs a 'shall' statement and a verification method (test, analysis, inspection, demonstration)."),
        "DEF-02": _t("High-severity risks have a control and test plan", "security", True, "Every AI-FMEA row with severity >= 8 needs a mitigation and a linked verifying requirement or test."),
        "DEF-03": _t("Problem statement and ConOps are complete", "completeness", False, "Problem statement without a prescribed solution, 3+ stakeholder groups, nominal/exception/degraded scenarios, 3+ measurable MOEs."),
    }},
    "capstone-research": {"title": "RESEARCH review", "critical": False, "requirements": {
        "RSR-01": _t("Candidate choices supported by measured evidence", "groundedness", False, "Profile at least two candidate model/configurations with measured quality, latency and cost."),
        "RSR-02": _t("Data/evidence profile documents real data quality issues", "completeness", False, "Profile the reference datasets: formats, missing fields, duplicates, unknown master data. Name the rows."),
    }},
    "capstone-architect": {"title": "ARCHITECT review", "critical": False, "requirements": {
        "CAR-01": _t(">=3 alternatives with a weighted trade study", "completeness", False, "Three distinct architecture patterns, criteria tied to requirement ids, weights summing to 1."),
        "CAR-02": _t("Decision survives sensitivity review or documents boundary conditions", "robustness", False, "Perturb the top weights by +/-20%; either the decision holds or you state when it would change."),
        "CAR-03": _t("ADRs with revisit triggers", "operations", False, "Each ADR: context, decision, alternatives, consequences and measurable revisit triggers."),
    }},
    "capstone-create": {"title": "CREATE review", "critical": False, "requirements": {
        "CRE-01": _t("Core happy path executes", "correctness", False, "Your reconcile() must match the clean bank/ledger pairs in the reference data."),
        "CRE-02": _t("Exception paths execute with evidence", "robustness", False, "Duplicates, missing references, amount mismatches, unmatched lines and unknown vendors must each be reported with the row ids that evidence them."),
        "CRE-03": _t("Financial mutations stay behind explicit approval", "security", True, "Proposed actions are proposals: every action that changes money or records must require approval."),
    }},
    "capstone-verify": {"title": "VERIFY review", "critical": False, "requirements": {
        "VER-01": _t("Golden data categorized", "completeness", False, "10+ golden cases, each with category and severity, including protected (high-severity) cases."),
        "VER-02": _t("Deterministic and semantic scorers", "correctness", False, "At least one deterministic scorer and one semantic/model-graded or rubric scorer, both named in the suite."),
        "VER-03": _t("Metamorphic tests and no protected-case regression", "robustness", False, "2+ metamorphic transformations, and every protected case passing in the reported run."),
    }},
    "capstone-security": {"title": "SECURITY review", "critical": True, "requirements": {
        "CSC-01": _t("Threat model with red-team traces and mitigations", "security", False, "4+ threats, each with asset, trust boundary, control and the regression test or trace that proves the control."),
        "CSC-02": _t("No unresolved critical/high planted finding", "security", True, "Every critical/high finding must be resolved (mitigated and tested) - not accepted, not deferred."),
    }},
    "capstone-improve": {"title": "IMPROVE review", "critical": False, "requirements": {
        "IMP-01": _t("Baseline vs optimized result on held-out data", "reproducibility", False, "Report the baseline and optimized scores on a held-out split that was not used for tuning."),
        "IMP-02": _t("Improvement without violating protected constraints", "robustness", True, "Show that cost, latency and protected security cases are within their limits after optimization."),
    }},
    "capstone-release": {"title": "RELEASE review", "critical": False, "requirements": {
        "CRL-01": _t("Release manifest and CI gate", "reproducibility", False, "Manifest with code, prompt, tool-schema, model/config, data and eval versions; a gate that blocks protected regressions."),
        "CRL-02": _t("Observability, rollback drill and runbook", "operations", False, "Trace schema for model/retrieval/tool events, explicit rollback criteria with a passed drill, and a runbook with owner and kill switch."),
    }},
    "capstone-validate": {"title": "VALIDATE review", "critical": False, "requirements": {
        "VAL-01": _t("Representative user scenarios measured against MOEs", "operations", False, "2+ scenarios with representative users/data, each tied to an MOE with a measured result."),
        "VAL-02": _t("Remaining gaps documented", "completeness", False, "For any MOE not achieved, state the gap and the plan; list residual risks."),
    }},
}

PACKAGE_REQUIREMENTS = {
    "CAP-01": _t("All critical requirements trace to verification", "traceability", False, "Every critical requirement id must appear in the traceability matrix with at least one verification (test id or method)."),
    "CAP-02": _t("No unresolved high-severity security finding", "security", True, "An unresolved high-impact authorization or data-integrity flaw fails the capstone regardless of other scores."),
    "CAP-03": _t("Schema/domain integrity checks pass", "correctness", True, "Every match and discrepancy must reference real rows, no row may be matched twice, and matched amounts must agree."),
    "CAP-04": _t("Evaluation suite includes robustness/metamorphic cases", "robustness", False, "Your evaluation must include robustness categories and metamorphic transformations, not only happy-path cases."),
    "CAP-05": _t("Release/rollback/runbook complete", "operations", False, "Release manifest, rollback criteria and drill, and a runbook with owner, kill switch and rollback steps."),
    "CAP-06": _t("Validation evidence tied to MOEs", "operations", False, "Each validation scenario names the MOE it measures and the measured result."),
}

# --- Helpers ---------------------------------------------------------------------------------------

VERIFY_METHODS = ("test", "analysis", "inspection", "demonstration")


def _list(d: Any, k: str) -> List[Dict[str, Any]]:
    v = (d or {}).get(k) if isinstance(d, dict) else None
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _txt(v: Any) -> str:
    return str(v or "").strip()


def _run_reconcile(fn: Callable) -> tuple:
    data = load_datasets()
    with capture_output():
        res, err = call_learner(fn, [dict(r) for r in data["bank"]], [dict(r) for r in data["ledger"]], [dict(r) for r in data["vendors"]])
    return (res if isinstance(res, dict) else {}), err


def _amount(v: str) -> float:
    s = str(v).strip()
    if "," in s and re.fullmatch(r"[\d.]*,\d{2}", s):
        s = s.replace(".", "").replace(",", ".")
    return round(float(s), 2)


# --- Milestone validators --------------------------------------------------------------------------

def _define(p: Dict[str, Any], c: Checker) -> None:
    reqs = _list(p, "requirements")
    crit = [r for r in reqs if r.get("critical")]
    bad = [_txt(r.get("id")) for r in crit if "shall" not in _txt(r.get("statement")).lower() or not any(m in _txt(r.get("verification_method")).lower() for m in VERIFY_METHODS)]
    c.record("DEF-01", bool(crit) and not bad, f"Critical requirements missing or unverifiable: {', '.join(bad) or 'none marked critical'}.", f"{len(crit)} critical requirements are verifiable.")
    ids = {_txt(r.get("id")) for r in reqs}
    fmea = _list(p, "fmea")
    open_risks = [_txt(f.get("id")) for f in fmea if int(f.get("severity", 0) or 0) >= 8 and (not f.get("mitigations") or not any(_txt(x) in ids or _txt(x).startswith("T-") for x in (f.get("verification") or [])))]
    c.record("DEF-02", bool(fmea) and not open_risks, f"High-severity risks without control/test plan: {', '.join(open_risks) or 'no AI-FMEA'}.", "High-severity risks have controls and tests.")
    conops = p.get("conops") or {}
    types = {_txt(s.get("type")).lower() for s in _list(conops, "scenarios")}
    groups = {_txt(s.get("group")).lower() for s in _list(conops, "stakeholders")}
    moes = [m for m in _list(conops, "moes") if re.search(r"\d", _txt(m.get("target")))]
    ok = len(_txt(p.get("problem_statement")).split()) >= 15 and len(groups) >= 3 and {"nominal", "exception", "degraded"} <= types and len(moes) >= 3
    c.record("DEF-03", ok, "Need a problem statement (15+ words), 3+ stakeholder groups, nominal/exception/degraded scenarios and 3+ MOEs with numeric targets.", "Problem definition and ConOps complete.")


def _research(p: Dict[str, Any], c: Checker) -> None:
    cands = [m for m in _list(p, "model_profile") if all(isinstance(m.get(k), (int, float)) for k in ("quality", "p50_latency_ms", "cost_per_task"))]
    c.record("RSR-01", len(cands) >= 2 and bool(_txt(p.get("selection_rationale"))), "Profile 2+ candidates with measured quality, p50_latency_ms and cost_per_task, and give a selection_rationale.", f"{len(cands)} candidates profiled.")
    issues = _list(p, "data_profile")
    rows = {r for i in issues for r in (i.get("rows") or [])}
    real = rows & {"B05", "B07", "B09", "B11", "L09", "L10", "L11"}
    c.record("RSR-02", len(issues) >= 3 and len(real) >= 3, f"Data profile lists {len(issues)} issue(s) evidencing {len(real)} planted row(s); need 3+ issues naming affected rows.", f"{len(issues)} data quality issues documented.")


def _architect(p: Dict[str, Any], c: Checker) -> None:
    alts = _list(p, "alternatives")
    pats = {_txt(a.get("pattern")) for a in alts if _txt(a.get("pattern"))}
    crits = _list(p, "criteria")
    try:
        w = sum(float(x["weight"]) for x in crits)
    except (KeyError, TypeError, ValueError):
        w = 0
    c.record("CAR-01", len(alts) >= 3 and len(pats) >= 3 and crits and abs(w - 1) < 1e-6 and all(x.get("requirements") for x in crits),
             "Need 3+ alternatives with distinct patterns and criteria linked to requirements with weights summing to 1.", "Trade study complete.")
    sens = _list(p, "sensitivity")
    c.record("CAR-02", len(sens) >= 4 and all(_txt(s.get("winner")) for s in sens) and (all(s.get("winner") == (p.get("decision") or {}).get("selected") for s in sens) or bool(_txt(p.get("boundary_conditions")))),
             "Record 4+ sensitivity runs (top-2 weights +/-20%); if the winner changes, document boundary_conditions.", "Decision survives sensitivity review or documents its boundaries.")
    adrs = _list(p, "adrs")
    good = [a for a in adrs if all(_txt(a.get(k)) for k in ("context", "decision", "consequences")) and a.get("alternatives") and any(re.search(r"\d|>|<", _txt(t)) for t in (a.get("revisit_triggers") or []))]
    c.record("CAR-03", len(good) >= 1 and len(good) == len(adrs), f"{len(good)} of {len(adrs)} ADRs complete (context, decision, alternatives, consequences, measurable revisit_triggers).", f"{len(good)} ADRs.")


def _reconcile_checks(p: Dict[str, Any]) -> Dict[str, Any]:
    fn = p.get("reconcile")
    if not callable(fn):
        return {"error": "no reconcile(bank_rows, ledger_rows, vendor_rows) function"}
    res, err = _run_reconcile(fn)
    if err:
        return {"error": err}
    matches = {(_txt(m.get("bank_line")), _txt(m.get("ledger_entry"))) for m in _list(res, "matches")}
    discs = _list(res, "discrepancies")
    found = {}
    for t, rows in PLANTED.items():
        found[t] = any(_txt(d.get("type")) == t and rows <= set(d.get("evidence") or []) and _txt(d.get("explanation")) for d in discs)
    actions = _list(res, "proposed_actions")
    return {"res": res, "matches": matches, "discrepancies": discs, "found": found, "actions": actions}


def _create(p: Dict[str, Any], c: Checker) -> None:
    r = _reconcile_checks(p)
    if "error" in r:
        for rid in ("CRE-01", "CRE-02", "CRE-03"):
            c.fail(rid, f"reconcile() could not be evaluated: {r['error']}.")
        return
    hit = len(EXPECTED_MATCHES & r["matches"])
    false = [m for m in r["matches"] if m not in EXPECTED_MATCHES]
    c.record("CRE-01", hit >= 7 and not false, f"{hit}/{len(EXPECTED_MATCHES)} clean pairs matched; false matches: {false[:4] or 'none'}.", f"{hit}/{len(EXPECTED_MATCHES)} clean pairs matched, no false matches.")
    missed = [t for t, ok in r["found"].items() if not ok]
    c.record("CRE-02", len(missed) <= 1, f"Exception paths not reported with evidence and explanation: {', '.join(missed)}.", f"{len(PLANTED) - len(missed)}/{len(PLANTED)} planted issues reported with evidence.")
    unguarded = [_txt(a.get("action")) for a in r["actions"] if not a.get("requires_approval")]
    c.record("CRE-03", bool(r["actions"]) and not unguarded, f"Proposed actions without approval: {', '.join(unguarded) or 'no proposed actions produced'}.", "Every proposed financial action requires approval.")
    c.evidence.update({"matched": hit, "planted_issues_found": len(PLANTED) - len(missed)})


def _verify(p: Dict[str, Any], c: Checker) -> None:
    golden = [g for g in _list(p, "golden_set") if _txt(g.get("category")) and _txt(g.get("severity"))]
    protected = [g for g in golden if _txt(g.get("severity")) in ("high", "critical")]
    c.record("VER-01", len(golden) >= 10 and bool(protected), f"{len(golden)} categorized golden cases ({len(protected)} protected); need 10+ including protected cases.", f"{len(golden)} golden cases.")
    kinds = {_txt(s.get("type")) for s in _list(p, "scorers")}
    c.record("VER-02", bool(kinds & {"exact_match", "schema", "numeric_tolerance", "executable"}) and bool(kinds & {"semantic_similarity", "model_graded", "rubric", "human_review"}),
             "Declare at least one deterministic scorer (exact_match/schema/numeric_tolerance/executable) and one semantic scorer (semantic_similarity/model_graded/rubric/human_review).", "Deterministic and semantic scorers declared.")
    run = p.get("latest_run") or {}
    failing_protected = [g for g in (run.get("failed_case_ids") or []) if g in {_txt(x.get("id")) for x in protected}]
    c.record("VER-03", len(_list(p, "metamorphic")) >= 2 and not failing_protected and "failed_case_ids" in run,
             f"Need 2+ metamorphic transformations and a latest_run with no failing protected case (failing: {', '.join(failing_protected) or 'none'}).", "Metamorphic tests present; no protected regression.")


def _security(p: Dict[str, Any], c: Checker) -> None:
    threats = [t for t in _list(p, "threats") if all(_txt(t.get(k)) for k in ("asset", "trust_boundary", "control", "test"))]
    c.record("CSC-01", len(threats) >= 4, f"{len(threats)} complete threats (asset, trust_boundary, control, test); need 4+.", f"{len(threats)} threats modelled.")
    open_ = [_txt(f.get("id")) for f in _list(p, "findings") if _txt(f.get("severity")) in ("critical", "high") and _txt(f.get("status")) != "resolved"]
    c.record("CSC-02", bool(_list(p, "findings")) and not open_, f"Unresolved critical/high findings: {', '.join(open_) or 'no findings recorded'}.", "No unresolved critical/high findings.")


def _improve(p: Dict[str, Any], c: Checker) -> None:
    b, o = p.get("baseline") or {}, p.get("optimized") or {}
    ok = all(isinstance(x.get("heldout_score"), (int, float)) for x in (b, o)) and p.get("heldout_used_for_tuning") is False
    c.record("IMP-01", ok, "Report baseline and optimized heldout_score and set heldout_used_for_tuning to false (and mean it).", f"Held-out {b.get('heldout_score')} -> {o.get('heldout_score')}.")
    lim = p.get("constraints") or {}
    viol = [k for k in ("cost_per_task", "p95_latency_ms") if not isinstance(lim.get(k), (int, float)) or not isinstance(o.get(k), (int, float)) or o[k] > lim[k]]
    if o.get("protected_failures", 1) != 0:
        viol.append("protected_failures")
    if ok and o["heldout_score"] < b["heldout_score"]:
        viol.append("no improvement")
    c.record("IMP-02", not viol, f"Constraint problems after optimization: {', '.join(viol)}.", "Improvement within cost/latency limits and no protected failures.")


def _release(p: Dict[str, Any], c: Checker) -> None:
    m = p.get("manifest") or {}
    keys = ("code_version", "prompt_versions", "tool_schema_versions", "model", "dataset_version", "eval_suite_version")
    gate = p.get("ci_gate") or {}
    c.record("CRL-01", all(m.get(k) for k in keys) and gate.get("blocks_on_protected_regression") is True,
             "Manifest needs code/prompt/tool-schema/model/dataset/eval versions, and ci_gate.blocks_on_protected_regression must be true.", "Manifest and CI gate complete.")
    ev = set((p.get("trace_schema") or {}).get("events") or [])
    rb = p.get("rollback") or {}
    rbk = p.get("runbook") or {}
    ok = {"model_call", "retrieval", "tool_call"} <= ev and len(rb.get("criteria") or []) >= 2 and rb.get("drill_passed") is True and all(rbk.get(k) for k in ("owner", "kill_switch", "rollback_steps"))
    c.record("CRL-02", ok, "Need trace events model_call/retrieval/tool_call, 2+ rollback criteria with drill_passed true, and a runbook with owner, kill_switch and rollback_steps.", "Observability, rollback drill and runbook complete.")


def _validate_ms(p: Dict[str, Any], c: Checker) -> None:
    sc = [s for s in _list(p, "scenarios") if all(_txt(s.get(k)) for k in ("moe", "users", "result"))]
    c.record("VAL-01", len(sc) >= 2, f"{len(sc)} scenarios with moe, users and measured result; need 2+.", f"{len(sc)} validation scenarios measured.")
    unmet = [s for s in sc if s.get("achieved") is False]
    ok = all(_txt(s.get("gap_plan")) for s in unmet) and bool(p.get("residual_risks"))
    c.record("VAL-02", ok, "Every scenario with achieved=false needs a gap_plan, and residual_risks must be listed.", "Gaps and residual risks documented.")


MILESTONE_VALIDATORS = {
    "capstone-define": _define, "capstone-research": _research, "capstone-architect": _architect, "capstone-create": _create,
    "capstone-verify": _verify, "capstone-security": _security, "capstone-improve": _improve, "capstone-release": _release,
    "capstone-validate": _validate_ms,
}


def _package(p: Any, c: Checker) -> None:
    if not isinstance(p, dict):
        raise ValueError("submit the full capstone package: a dict with one key per milestone (define, research, ... validate)")
    d = p.get("define") or {}
    crit = [_txt(r.get("id")) for r in _list(d, "requirements") if r.get("critical")]
    trace = d.get("traceability") or {}
    untraced = [r for r in crit if not trace.get(r)]
    c.record("CAP-01", bool(crit) and not untraced, f"Critical requirements without verification in the traceability matrix: {', '.join(untraced) or 'none marked critical'}.", f"{len(crit)} critical requirements traced.")

    s = p.get("security") or {}
    open_ = [_txt(f.get("id")) for f in _list(s, "findings") if _txt(f.get("severity")) in ("critical", "high") and _txt(f.get("status")) != "resolved"]
    c.record("CAP-02", bool(_list(s, "findings")) and not open_, f"Unresolved high-severity findings: {', '.join(open_) or 'no security findings recorded'}.", "No unresolved high-severity security finding.")

    r = _reconcile_checks(p.get("create") or {})
    if "error" in r:
        c.fail("CAP-03", f"Integrity checks could not run: {r['error']}.")
    else:
        data = load_datasets()
        bank = {x["line_id"]: x for x in data["bank"]}
        ledger = {x["entry_id"]: x for x in data["ledger"]}
        problems = []
        seen_b, seen_l = set(), set()
        for b, l in r["matches"]:
            if b not in bank or l not in ledger:
                problems.append(f"unknown rows {b}/{l}")
                continue
            if b in seen_b or l in seen_l:
                problems.append(f"row matched twice ({b}/{l})")
            seen_b.add(b)
            seen_l.add(l)
            if _amount(bank[b]["amount"]) != _amount(ledger[l]["amount"]):
                problems.append(f"amounts disagree {b}/{l}")
        for dsc in r["discrepancies"]:
            for ev in dsc.get("evidence") or []:
                if ev not in bank and ev not in ledger:
                    problems.append(f"evidence {ev} does not exist")
        c.record("CAP-03", not problems, "; ".join(problems[:5]) + ".", "Matches and discrepancies reference real rows; amounts balance; no double matching.")

    v = p.get("verify") or {}
    cats = {_txt(g.get("category")) for g in _list(v, "golden_set")}
    c.record("CAP-04", "robustness" in cats and len(_list(v, "metamorphic")) >= 2, "The evaluation suite needs robustness-category cases and 2+ metamorphic transformations.", "Robustness and metamorphic cases included.")
    rel = p.get("release") or {}
    rb, rbk = rel.get("rollback") or {}, rel.get("runbook") or {}
    c.record("CAP-05", bool(rel.get("manifest")) and rb.get("drill_passed") is True and len(rb.get("criteria") or []) >= 2 and all(rbk.get(k) for k in ("owner", "kill_switch", "rollback_steps")),
             "Release manifest, rollback criteria with a passed drill, and a complete runbook are required.", "Release, rollback and runbook complete.")
    val = p.get("validate") or {}
    moes = {_txt(m.get("id")) for m in _list(d.get("conops") or {}, "moes")}
    tied = [s for s in _list(val, "scenarios") if _txt(s.get("moe")) in moes and _txt(s.get("result"))]
    c.record("CAP-06", len(tied) >= 2, f"{len(tied)} validation scenario(s) reference a defined MOE id with a measured result; need 2+.", f"{len(tied)} scenarios tied to MOEs.")


# --- Registration ----------------------------------------------------------------------------------

def _milestone_validator(fn: Callable[[Dict[str, Any], Checker], None]) -> Callable[[Any, Checker], None]:
    def run(submission: Any, c: Checker) -> None:
        if not isinstance(submission, dict):
            raise ValueError("submit the milestone evidence as a dict (see the template in capstone/templates)")
        fn(submission, c)

    return run


for mid, spec in MILESTONES.items():
    LAB_SPECS[mid] = LabSpec("capstone", mid, "m16-capstone", "capstone/capstone-studio.ipynb", spec["title"], 1.0,
                             f"capstone_{mid.split('-', 1)[1]}", milestone_id=mid)
    register(mid, spec["requirements"], _milestone_validator(MILESTONE_VALIDATORS[mid]))

register("capstone", PACKAGE_REQUIREMENTS, _package)
