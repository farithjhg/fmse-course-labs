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
from ..i18n import add_catalog, t as _t
from ..textutil import canonical, has_shall, mentions

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

def _req(text, dim, crit, hint):
    return (text, dim, crit, hint)


MILESTONES: Dict[str, Dict[str, Any]] = {
    "capstone-define": {"title": "DEFINE review", "critical": False, "requirements": {
        "DEF-01": _req("Critical requirements are verifiable", "traceability", True, "Each critical requirement needs a 'shall' statement and a verification method (test, analysis, inspection, demonstration)."),
        "DEF-02": _req("High-severity risks have a control and test plan", "security", True, "Every AI-FMEA row with severity >= 8 needs a mitigation and a linked verifying requirement or test."),
        "DEF-03": _req("Problem statement and ConOps are complete", "completeness", False, "Problem statement without a prescribed solution, 3+ stakeholder groups, nominal/exception/degraded scenarios, 3+ measurable MOEs."),
    }},
    "capstone-research": {"title": "RESEARCH review", "critical": False, "requirements": {
        "RSR-01": _req("Candidate choices supported by measured evidence", "groundedness", False, "Profile at least two candidate model/configurations with measured quality, latency and cost."),
        "RSR-02": _req("Data/evidence profile documents real data quality issues", "completeness", False, "Profile the reference datasets: formats, missing fields, duplicates, unknown master data. Name the rows."),
    }},
    "capstone-architect": {"title": "ARCHITECT review", "critical": False, "requirements": {
        "CAR-01": _req(">=3 alternatives with a weighted trade study", "completeness", False, "Three distinct architecture patterns, criteria tied to requirement ids, weights summing to 1."),
        "CAR-02": _req("Decision survives sensitivity review or documents boundary conditions", "robustness", False, "Perturb the top weights by +/-20%; either the decision holds or you state when it would change."),
        "CAR-03": _req("ADRs with revisit triggers", "operations", False, "Each ADR: context, decision, alternatives, consequences and measurable revisit triggers."),
    }},
    "capstone-create": {"title": "CREATE review", "critical": False, "requirements": {
        "CRE-01": _req("Core happy path executes", "correctness", False, "Your reconcile() must match the clean bank/ledger pairs in the reference data."),
        "CRE-02": _req("Exception paths execute with evidence", "robustness", False, "Duplicates, missing references, amount mismatches, unmatched lines and unknown vendors must each be reported with the row ids that evidence them."),
        "CRE-03": _req("Financial mutations stay behind explicit approval", "security", True, "Proposed actions are proposals: every action that changes money or records must require approval."),
    }},
    "capstone-verify": {"title": "VERIFY review", "critical": False, "requirements": {
        "VER-01": _req("Golden data categorized", "completeness", False, "10+ golden cases, each with category and severity, including protected (high-severity) cases."),
        "VER-02": _req("Deterministic and semantic scorers", "correctness", False, "At least one deterministic scorer and one semantic/model-graded or rubric scorer, both named in the suite."),
        "VER-03": _req("Metamorphic tests and no protected-case regression", "robustness", False, "2+ metamorphic transformations, and every protected case passing in the reported run."),
    }},
    "capstone-security": {"title": "SECURITY review", "critical": True, "requirements": {
        "CSC-01": _req("Threat model with red-team traces and mitigations", "security", False, "4+ threats, each with asset, trust boundary, control and the regression test or trace that proves the control."),
        "CSC-02": _req("No unresolved critical/high planted finding", "security", True, "Every critical/high finding must be resolved (mitigated and tested) - not accepted, not deferred."),
    }},
    "capstone-improve": {"title": "IMPROVE review", "critical": False, "requirements": {
        "IMP-01": _req("Baseline vs optimized result on held-out data", "reproducibility", False, "Report the baseline and optimized scores on a held-out split that was not used for tuning."),
        "IMP-02": _req("Improvement without violating protected constraints", "robustness", True, "Show that cost, latency and protected security cases are within their limits after optimization."),
    }},
    "capstone-release": {"title": "RELEASE review", "critical": False, "requirements": {
        "CRL-01": _req("Release manifest and CI gate", "reproducibility", False, "Manifest with code, prompt, tool-schema, model/config, data and eval versions; a gate that blocks protected regressions."),
        "CRL-02": _req("Observability, rollback drill and runbook", "operations", False, "Trace schema for model/retrieval/tool events, explicit rollback criteria with a passed drill, and a runbook with owner and kill switch."),
    }},
    "capstone-validate": {"title": "VALIDATE review", "critical": False, "requirements": {
        "VAL-01": _req("Representative user scenarios measured against MOEs", "operations", False, "2+ scenarios with representative users/data, each tied to an MOE with a measured result."),
        "VAL-02": _req("Remaining gaps documented", "completeness", False, "For any MOE not achieved, state the gap and the plan; list residual risks."),
    }},
}

PACKAGE_REQUIREMENTS = {
    "CAP-01": _req("All critical requirements trace to verification", "traceability", False, "Every critical requirement id must appear in the traceability matrix with at least one verification (test id or method)."),
    "CAP-02": _req("No unresolved high-severity security finding", "security", True, "An unresolved high-impact authorization or data-integrity flaw fails the capstone regardless of other scores."),
    "CAP-03": _req("Schema/domain integrity checks pass", "correctness", True, "Every match and discrepancy must reference real rows, no row may be matched twice, and matched amounts must agree."),
    "CAP-04": _req("Evaluation suite includes robustness/metamorphic cases", "robustness", False, "Your evaluation must include robustness categories and metamorphic transformations, not only happy-path cases."),
    "CAP-05": _req("Release/rollback/runbook complete", "operations", False, "Release manifest, rollback criteria and drill, and a runbook with owner, kill switch and rollback steps."),
    "CAP-06": _req("Validation evidence tied to MOEs", "operations", False, "Each validation scenario names the MOE it measures and the measured result."),
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
    bad = [_txt(r.get("id")) for r in crit if not has_shall(r.get("statement")) or not any(mentions(r.get("verification_method"), m) for m in VERIFY_METHODS)]
    c.record("DEF-01", bool(crit) and not bad, _t('Critical requirements missing or unverifiable: {v}.', v=', '.join(bad) or _t('none marked critical')), _t('{n_crit} critical requirements are verifiable.', n_crit=len(crit)))
    ids = {_txt(r.get("id")) for r in reqs}
    fmea = _list(p, "fmea")
    open_risks = [_txt(f.get("id")) for f in fmea if int(f.get("severity", 0) or 0) >= 8 and (not f.get("mitigations") or not any(_txt(x) in ids or _txt(x).startswith("T-") for x in (f.get("verification") or [])))]
    c.record("DEF-02", bool(fmea) and not open_risks, _t('High-severity risks without control/test plan: {v}.', v=', '.join(open_risks) or _t('no AI-FMEA')), _t('High-severity risks have controls and tests.'))
    conops = p.get("conops") or {}
    types = {canonical(s.get("type")) for s in _list(conops, "scenarios")}
    groups = {_txt(s.get("group")).lower() for s in _list(conops, "stakeholders")}
    moes = [m for m in _list(conops, "moes") if re.search(r"\d", _txt(m.get("target")))]
    ok = len(_txt(p.get("problem_statement")).split()) >= 15 and len(groups) >= 3 and {"nominal", "exception", "degraded"} <= types and len(moes) >= 3
    c.record("DEF-03", ok, _t('Need a problem statement (15+ words), 3+ stakeholder groups, nominal/exception/degraded scenarios and 3+ MOEs with numeric targets.'), _t('Problem definition and ConOps complete.'))


def _research(p: Dict[str, Any], c: Checker) -> None:
    cands = [m for m in _list(p, "model_profile") if all(isinstance(m.get(k), (int, float)) for k in ("quality", "p50_latency_ms", "cost_per_task"))]
    c.record("RSR-01", len(cands) >= 2 and bool(_txt(p.get("selection_rationale"))), _t('Profile 2+ candidates with measured quality, p50_latency_ms and cost_per_task, and give a selection_rationale.'), _t('{n_cands} candidates profiled.', n_cands=len(cands)))
    issues = _list(p, "data_profile")
    rows = {r for i in issues for r in (i.get("rows") or [])}
    real = rows & {"B05", "B07", "B09", "B11", "L09", "L10", "L11"}
    c.record("RSR-02", len(issues) >= 3 and len(real) >= 3, _t('Data profile lists {n_issues} issue(s) evidencing {n_real} planted row(s); need 3+ issues naming affected rows.', n_issues=len(issues), n_real=len(real)), _t('{n_issues} data quality issues documented.', n_issues=len(issues)))


def _architect(p: Dict[str, Any], c: Checker) -> None:
    alts = _list(p, "alternatives")
    pats = {_txt(a.get("pattern")) for a in alts if _txt(a.get("pattern"))}
    crits = _list(p, "criteria")
    try:
        w = sum(float(x["weight"]) for x in crits)
    except (KeyError, TypeError, ValueError):
        w = 0
    c.record("CAR-01", len(alts) >= 3 and len(pats) >= 3 and crits and abs(w - 1) < 1e-6 and all(x.get("requirements") for x in crits),
             _t('Need 3+ alternatives with distinct patterns and criteria linked to requirements with weights summing to 1.'), _t('Trade study complete.'))
    sens = _list(p, "sensitivity")
    c.record("CAR-02", len(sens) >= 4 and all(_txt(s.get("winner")) for s in sens) and (all(s.get("winner") == (p.get("decision") or {}).get("selected") for s in sens) or bool(_txt(p.get("boundary_conditions")))),
             _t('Record 4+ sensitivity runs (top-2 weights +/-20%); if the winner changes, document boundary_conditions.'), _t('Decision survives sensitivity review or documents its boundaries.'))
    adrs = _list(p, "adrs")
    good = [a for a in adrs if all(_txt(a.get(k)) for k in ("context", "decision", "consequences")) and a.get("alternatives") and any(re.search(r"\d|>|<", _txt(t)) for t in (a.get("revisit_triggers") or []))]
    c.record("CAR-03", len(good) >= 1 and len(good) == len(adrs), _t('{n_good} of {n_adrs} ADRs complete (context, decision, alternatives, consequences, measurable revisit_triggers).', n_good=len(good), n_adrs=len(adrs)), _t('{n_good} ADRs.', n_good=len(good)))


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
            c.fail(rid, _t('reconcile() could not be evaluated: {v}.', v=r['error']))
        return
    hit = len(EXPECTED_MATCHES & r["matches"])
    false = [m for m in r["matches"] if m not in EXPECTED_MATCHES]
    c.record("CRE-01", hit >= 7 and not false, _t('{hit}/{n_EXPECTED_MATCHES} clean pairs matched; false matches: {v}.', hit=hit, n_EXPECTED_MATCHES=len(EXPECTED_MATCHES), v=false[:4] or 'none'), _t('{hit}/{n_EXPECTED_MATCHES} clean pairs matched, no false matches.', hit=hit, n_EXPECTED_MATCHES=len(EXPECTED_MATCHES)))
    missed = [t for t, ok in r["found"].items() if not ok]
    c.record("CRE-02", len(missed) <= 1, _t('Exception paths not reported with evidence and explanation: {v}.', v=', '.join(missed)), _t('{v}/{n_PLANTED} planted issues reported with evidence.', v=len(PLANTED) - len(missed), n_PLANTED=len(PLANTED)))
    unguarded = [_txt(a.get("action")) for a in r["actions"] if not a.get("requires_approval")]
    c.record("CRE-03", bool(r["actions"]) and not unguarded, _t('Proposed actions without approval: {v}.', v=', '.join(unguarded) or 'no proposed actions produced'), _t('Every proposed financial action requires approval.'))
    c.evidence.update({"matched": hit, "planted_issues_found": len(PLANTED) - len(missed)})


def _verify(p: Dict[str, Any], c: Checker) -> None:
    golden = [g for g in _list(p, "golden_set") if _txt(g.get("category")) and _txt(g.get("severity"))]
    protected = [g for g in golden if _txt(g.get("severity")) in ("high", "critical")]
    c.record("VER-01", len(golden) >= 10 and bool(protected), _t('{n_golden} categorized golden cases ({n_protected} protected); need 10+ including protected cases.', n_golden=len(golden), n_protected=len(protected)), _t('{n_golden} golden cases.', n_golden=len(golden)))
    kinds = {_txt(s.get("type")) for s in _list(p, "scorers")}
    c.record("VER-02", bool(kinds & {"exact_match", "schema", "numeric_tolerance", "executable"}) and bool(kinds & {"semantic_similarity", "model_graded", "rubric", "human_review"}),
             _t('Declare at least one deterministic scorer (exact_match/schema/numeric_tolerance/executable) and one semantic scorer (semantic_similarity/model_graded/rubric/human_review).'), _t('Deterministic and semantic scorers declared.'))
    run = p.get("latest_run") or {}
    failing_protected = [g for g in (run.get("failed_case_ids") or []) if g in {_txt(x.get("id")) for x in protected}]
    c.record("VER-03", len(_list(p, "metamorphic")) >= 2 and not failing_protected and "failed_case_ids" in run,
             _t('Need 2+ metamorphic transformations and a latest_run with no failing protected case (failing: {v}).', v=', '.join(failing_protected) or 'none'), _t('Metamorphic tests present; no protected regression.'))


def _security(p: Dict[str, Any], c: Checker) -> None:
    threats = [t for t in _list(p, "threats") if all(_txt(t.get(k)) for k in ("asset", "trust_boundary", "control", "test"))]
    c.record("CSC-01", len(threats) >= 4, _t('{n_threats} complete threats (asset, trust_boundary, control, test); need 4+.', n_threats=len(threats)), _t('{n_threats} threats modelled.', n_threats=len(threats)))
    open_ = [_txt(f.get("id")) for f in _list(p, "findings") if _txt(f.get("severity")) in ("critical", "high") and _txt(f.get("status")) != "resolved"]
    c.record("CSC-02", bool(_list(p, "findings")) and not open_, _t('Unresolved critical/high findings: {v}.', v=', '.join(open_) or 'no findings recorded'), _t('No unresolved critical/high findings.'))


def _improve(p: Dict[str, Any], c: Checker) -> None:
    b, o = p.get("baseline") or {}, p.get("optimized") or {}
    ok = all(isinstance(x.get("heldout_score"), (int, float)) for x in (b, o)) and p.get("heldout_used_for_tuning") is False
    c.record("IMP-01", ok, _t('Report baseline and optimized heldout_score and set heldout_used_for_tuning to false (and mean it).'), _t('Held-out {v} -> {v2}.', v=b.get('heldout_score'), v2=o.get('heldout_score')))
    lim = p.get("constraints") or {}
    viol = [k for k in ("cost_per_task", "p95_latency_ms") if not isinstance(lim.get(k), (int, float)) or not isinstance(o.get(k), (int, float)) or o[k] > lim[k]]
    if o.get("protected_failures", 1) != 0:
        viol.append("protected_failures")
    if ok and o["heldout_score"] < b["heldout_score"]:
        viol.append("no improvement")
    c.record("IMP-02", not viol, _t('Constraint problems after optimization: {v}.', v=', '.join(viol)), _t('Improvement within cost/latency limits and no protected failures.'))


def _release(p: Dict[str, Any], c: Checker) -> None:
    m = p.get("manifest") or {}
    keys = ("code_version", "prompt_versions", "tool_schema_versions", "model", "dataset_version", "eval_suite_version")
    gate = p.get("ci_gate") or {}
    c.record("CRL-01", all(m.get(k) for k in keys) and gate.get("blocks_on_protected_regression") is True,
             _t('Manifest needs code/prompt/tool-schema/model/dataset/eval versions, and ci_gate.blocks_on_protected_regression must be true.'), _t('Manifest and CI gate complete.'))
    ev = set((p.get("trace_schema") or {}).get("events") or [])
    rb = p.get("rollback") or {}
    rbk = p.get("runbook") or {}
    ok = {"model_call", "retrieval", "tool_call"} <= ev and len(rb.get("criteria") or []) >= 2 and rb.get("drill_passed") is True and all(rbk.get(k) for k in ("owner", "kill_switch", "rollback_steps"))
    c.record("CRL-02", ok, _t('Need trace events model_call/retrieval/tool_call, 2+ rollback criteria with drill_passed true, and a runbook with owner, kill_switch and rollback_steps.'), _t('Observability, rollback drill and runbook complete.'))


def _validate_ms(p: Dict[str, Any], c: Checker) -> None:
    sc = [s for s in _list(p, "scenarios") if all(_txt(s.get(k)) for k in ("moe", "users", "result"))]
    c.record("VAL-01", len(sc) >= 2, _t('{n_sc} scenarios with moe, users and measured result; need 2+.', n_sc=len(sc)), _t('{n_sc} validation scenarios measured.', n_sc=len(sc)))
    unmet = [s for s in sc if s.get("achieved") is False]
    ok = all(_txt(s.get("gap_plan")) for s in unmet) and bool(p.get("residual_risks"))
    c.record("VAL-02", ok, _t('Every scenario with achieved=false needs a gap_plan, and residual_risks must be listed.'), _t('Gaps and residual risks documented.'))


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
    c.record("CAP-01", bool(crit) and not untraced, _t('Critical requirements without verification in the traceability matrix: {v}.', v=', '.join(untraced) or _t('none marked critical')), _t('{n_crit} critical requirements traced.', n_crit=len(crit)))

    s = p.get("security") or {}
    open_ = [_txt(f.get("id")) for f in _list(s, "findings") if _txt(f.get("severity")) in ("critical", "high") and _txt(f.get("status")) != "resolved"]
    c.record("CAP-02", bool(_list(s, "findings")) and not open_, _t('Unresolved high-severity findings: {v}.', v=', '.join(open_) or 'no security findings recorded'), _t('No unresolved high-severity security finding.'))

    r = _reconcile_checks(p.get("create") or {})
    if "error" in r:
        c.fail("CAP-03", _t('Integrity checks could not run: {v}.', v=r['error']))
    else:
        data = load_datasets()
        bank = {x["line_id"]: x for x in data["bank"]}
        ledger = {x["entry_id"]: x for x in data["ledger"]}
        problems = []
        seen_b, seen_l = set(), set()
        for b, l in r["matches"]:
            if b not in bank or l not in ledger:
                problems.append(_t('unknown rows {b}/{l}', b=b, l=l))
                continue
            if b in seen_b or l in seen_l:
                problems.append(_t('row matched twice ({b}/{l})', b=b, l=l))
            seen_b.add(b)
            seen_l.add(l)
            if _amount(bank[b]["amount"]) != _amount(ledger[l]["amount"]):
                problems.append(_t('amounts disagree {b}/{l}', b=b, l=l))
        for dsc in r["discrepancies"]:
            for ev in dsc.get("evidence") or []:
                if ev not in bank and ev not in ledger:
                    problems.append(_t('evidence {ev} does not exist', ev=ev))
        c.record("CAP-03", not problems, "; ".join(problems[:5]) + ".", _t('Matches and discrepancies reference real rows; amounts balance; no double matching.'))

    v = p.get("verify") or {}
    cats = {_txt(g.get("category")) for g in _list(v, "golden_set")}
    c.record("CAP-04", "robustness" in cats and len(_list(v, "metamorphic")) >= 2, _t('The evaluation suite needs robustness-category cases and 2+ metamorphic transformations.'), _t('Robustness and metamorphic cases included.'))
    rel = p.get("release") or {}
    rb, rbk = rel.get("rollback") or {}, rel.get("runbook") or {}
    c.record("CAP-05", bool(rel.get("manifest")) and rb.get("drill_passed") is True and len(rb.get("criteria") or []) >= 2 and all(rbk.get(k) for k in ("owner", "kill_switch", "rollback_steps")),
             _t('Release manifest, rollback criteria with a passed drill, and a complete runbook are required.'), _t('Release, rollback and runbook complete.'))
    val = p.get("validate") or {}
    moes = {_txt(m.get("id")) for m in _list(d.get("conops") or {}, "moes")}
    tied = [s for s in _list(val, "scenarios") if _txt(s.get("moe")) in moes and _txt(s.get("result"))]
    c.record("CAP-06", len(tied) >= 2, _t('{n_tied} validation scenario(s) reference a defined MOE id with a measured result; need 2+.', n_tied=len(tied)), _t('{n_tied} scenarios tied to MOEs.', n_tied=len(tied)))


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


add_catalog({
    # Milestone requirements and hints (the milestone titles come from requirements_es.py).
    "Critical requirements are verifiable": "Los requisitos críticos se pueden verificar",
    "Each critical requirement needs a 'shall' statement and a verification method (test, analysis, inspection, demonstration).":
        "Cada requisito crítico necesita una frase con 'deberá' y un método de verificación (prueba, análisis, inspección o demostración).",
    "High-severity risks have a control and test plan": "Los riesgos de gravedad alta tienen un plan de control y de prueba",
    "Every AI-FMEA row with severity >= 8 needs a mitigation and a linked verifying requirement or test.":
        "Cada fila del AI-FMEA con gravedad >= 8 necesita una mitigación y un requisito o una prueba de verificación enlazados.",
    "Problem statement and ConOps are complete": "El enunciado del problema y el ConOps están completos",
    "Problem statement without a prescribed solution, 3+ stakeholder groups, nominal/exception/degraded scenarios, 3+ measurable MOEs.":
        "Enunciado del problema sin una solución impuesta, 3 o más grupos de partes interesadas, escenarios nominal, de excepción y degradado, y 3 o más MOE medibles.",
    "Candidate choices supported by measured evidence": "Los candidatos elegidos se apoyan en evidencia medida",
    "Profile at least two candidate model/configurations with measured quality, latency and cost.":
        "Perfila al menos dos modelos o configuraciones candidatos con su calidad, latencia y costo medidos.",
    "Data/evidence profile documents real data quality issues": "El perfil de los datos y la evidencia documenta problemas reales de calidad de datos",
    "Profile the reference datasets: formats, missing fields, duplicates, unknown master data. Name the rows.":
        "Perfila los conjuntos de datos de referencia: formatos, campos que faltan, duplicados, datos maestros desconocidos. Nombra las filas.",
    ">=3 alternatives with a weighted trade study": ">=3 alternativas con un estudio de alternativas ponderado",
    "Three distinct architecture patterns, criteria tied to requirement ids, weights summing to 1.":
        "Tres patrones de arquitectura distintos, criterios ligados a IDs de requisitos y pesos que suman 1.",
    "Decision survives sensitivity review or documents boundary conditions":
        "La decisión resiste la revisión de sensibilidad o documenta sus condiciones límite",
    "Perturb the top weights by +/-20%; either the decision holds or you state when it would change.":
        "Perturba los pesos principales un +/-20%: o la decisión se mantiene, o indicas cuándo cambiaría.",
    "ADRs with revisit triggers": "ADR con disparadores de revisión",
    "Each ADR: context, decision, alternatives, consequences and measurable revisit triggers.":
        "Cada ADR: contexto, decisión, alternativas, consecuencias y disparadores de revisión medibles.",
    "Core happy path executes": "El camino feliz principal se ejecuta",
    "Your reconcile() must match the clean bank/ledger pairs in the reference data.":
        "Tu reconcile() debe emparejar los pares limpios de banco y libro mayor de los datos de referencia.",
    "Exception paths execute with evidence": "Los caminos de excepción se ejecutan con evidencia",
    "Duplicates, missing references, amount mismatches, unmatched lines and unknown vendors must each be reported with the row ids that evidence them.":
        "Los duplicados, las referencias que faltan, los importes que no cuadran, las líneas sin pareja y los proveedores desconocidos deben aparecer cada uno con los IDs de fila que los evidencian.",
    "Financial mutations stay behind explicit approval": "Las operaciones financieras no se ejecutan sin una aprobación explícita",
    "Proposed actions are proposals: every action that changes money or records must require approval.":
        "Las acciones propuestas son solo propuestas: toda acción que mueva dinero o cambie registros debe exigir aprobación.",
    "Golden data categorized": "Datos de referencia categorizados",
    "10+ golden cases, each with category and severity, including protected (high-severity) cases.":
        "10 o más casos de referencia, cada uno con categoría y gravedad, incluidos casos protegidos (de gravedad alta).",
    "Deterministic and semantic scorers": "Evaluadores deterministas y semánticos",
    "At least one deterministic scorer and one semantic/model-graded or rubric scorer, both named in the suite.":
        "Al menos un evaluador determinista y uno semántico, calificado por modelo o por rúbrica, ambos nombrados en el conjunto de pruebas.",
    "Metamorphic tests and no protected-case regression": "Pruebas metamórficas y ninguna regresión en casos protegidos",
    "2+ metamorphic transformations, and every protected case passing in the reported run.":
        "2 o más transformaciones metamórficas, y todos los casos protegidos pasan en la ejecución declarada.",
    "Threat model with red-team traces and mitigations": "Modelo de amenazas con trazas de red teaming y mitigaciones",
    "4+ threats, each with asset, trust boundary, control and the regression test or trace that proves the control.":
        "4 o más amenazas, cada una con activo, límite de confianza, control y la prueba de regresión o la traza que demuestra el control.",
    "No unresolved critical/high planted finding": "Ningún hallazgo de gravedad crítica o alta introducido a propósito queda sin resolver",
    "Every critical/high finding must be resolved (mitigated and tested) - not accepted, not deferred.":
        "Todo hallazgo crítico o alto debe resolverse (mitigado y probado): ni aceptado ni aplazado.",
    "Baseline vs optimized result on held-out data": "Resultado de la línea base frente al optimizado en el conjunto reservado",
    "Report the baseline and optimized scores on a held-out split that was not used for tuning.":
        "Indica las puntuaciones de la línea base y del optimizado en una división reservada que no se usó para el ajuste.",
    "Improvement without violating protected constraints": "Mejora sin incumplir las restricciones protegidas",
    "Show that cost, latency and protected security cases are within their limits after optimization.":
        "Demuestra que el costo, la latencia y los casos de seguridad protegidos quedan dentro de sus límites tras la optimización.",
    "Release manifest and CI gate": "Manifiesto de la versión y control de CI",
    "Manifest with code, prompt, tool-schema, model/config, data and eval versions; a gate that blocks protected regressions.":
        "Manifiesto con las versiones del código, del prompt, del esquema de herramientas, del modelo y su configuración, de los datos y de la evaluación; un control que bloquea las regresiones protegidas.",
    "Observability, rollback drill and runbook": "Observabilidad, simulacro de marcha atrás y runbook",
    "Trace schema for model/retrieval/tool events, explicit rollback criteria with a passed drill, and a runbook with owner and kill switch.":
        "Esquema de trazas para eventos de modelo, recuperación y herramientas; criterios de marcha atrás explícitos con un simulacro superado; y un runbook con responsable e interruptor de emergencia.",
    "Representative user scenarios measured against MOEs": "Escenarios representativos de usuarios medidos frente a las MOE",
    "2+ scenarios with representative users/data, each tied to an MOE with a measured result.":
        "2 o más escenarios con usuarios o datos representativos, cada uno ligado a una MOE con un resultado medido.",
    "Remaining gaps documented": "Brechas pendientes documentadas",
    "For any MOE not achieved, state the gap and the plan; list residual risks.":
        "Para cada MOE no alcanzada, indica la brecha y el plan; enumera los riesgos residuales.",
    # Validator messages.
    "Critical requirements missing or unverifiable: {v}.": "Requisitos críticos que faltan o no se pueden verificar: {v}.",
    "none marked critical": "ninguno marcado como crítico",
    "{n_crit} critical requirements are verifiable.": "{n_crit} requisitos críticos se pueden verificar.",
    "High-severity risks without control/test plan: {v}.": "Riesgos de gravedad alta sin plan de control y de prueba: {v}.",
    "High-severity risks have controls and tests.": "Los riesgos de gravedad alta tienen controles y pruebas.",
    "Need a problem statement (15+ words), 3+ stakeholder groups, nominal/exception/degraded scenarios and 3+ MOEs with numeric targets.":
        "Se necesita un enunciado del problema (15 palabras o más), 3 o más grupos de partes interesadas, escenarios nominal, de excepción y degradado, y 3 o más MOE con objetivos numéricos.",
    "Problem definition and ConOps complete.": "Definición del problema y ConOps completos.",
    "Profile 2+ candidates with measured quality, p50_latency_ms and cost_per_task, and give a selection_rationale.":
        "Perfila 2 o más candidatos con quality, p50_latency_ms y cost_per_task medidos, e incluye un selection_rationale.",
    "{n_cands} candidates profiled.": "{n_cands} candidatos perfilados.",
    "Data profile lists {n_issues} issue(s) evidencing {n_real} planted row(s); need 3+ issues naming affected rows.":
        "El perfil de datos enumera {n_issues} problema(s) que evidencian {n_real} fila(s) sembrada(s) a propósito; se necesitan 3 o más problemas que nombren las filas afectadas.",
    "{n_issues} data quality issues documented.": "{n_issues} problemas de calidad de datos documentados.",
    "Need 3+ alternatives with distinct patterns and criteria linked to requirements with weights summing to 1.":
        "Se necesitan 3 o más alternativas con patrones distintos, y criterios enlazados a requisitos con pesos que sumen 1.",
    "Trade study complete.": "Estudio de alternativas completo.",
    "Record 4+ sensitivity runs (top-2 weights +/-20%); if the winner changes, document boundary_conditions.":
        "Registra 4 o más ejecuciones de sensibilidad (los 2 pesos principales, +/-20%); si cambia el ganador, documenta boundary_conditions.",
    "Decision survives sensitivity review or documents its boundaries.": "La decisión resiste la revisión de sensibilidad o documenta sus límites.",
    "{n_good} of {n_adrs} ADRs complete (context, decision, alternatives, consequences, measurable revisit_triggers).":
        "{n_good} de {n_adrs} ADR completos (context, decision, alternatives, consequences, revisit_triggers medibles).",
    "{n_good} ADRs.": "{n_good} ADR.",
    "{hit}/{n_EXPECTED_MATCHES} clean pairs matched; false matches: {v}.": "{hit}/{n_EXPECTED_MATCHES} pares limpios emparejados; emparejamientos falsos: {v}.",
    "{hit}/{n_EXPECTED_MATCHES} clean pairs matched, no false matches.": "{hit}/{n_EXPECTED_MATCHES} pares limpios emparejados, sin emparejamientos falsos.",
    "Exception paths not reported with evidence and explanation: {v}.": "Caminos de excepción sin evidencia ni explicación: {v}.",
    "{v}/{n_PLANTED} planted issues reported with evidence.": "{v}/{n_PLANTED} problemas sembrados a propósito, reportados con evidencia.",
    "Proposed actions without approval: {v}.": "Acciones propuestas sin aprobación: {v}.",
    "Every proposed financial action requires approval.": "Toda acción financiera propuesta exige aprobación.",
    "{n_golden} categorized golden cases ({n_protected} protected); need 10+ including protected cases.":
        "{n_golden} casos de referencia categorizados ({n_protected} protegidos); se necesitan 10 o más, incluidos casos protegidos.",
    "{n_golden} golden cases.": "{n_golden} casos de referencia.",
    "Declare at least one deterministic scorer (exact_match/schema/numeric_tolerance/executable) and one semantic scorer (semantic_similarity/model_graded/rubric/human_review).":
        "Declara al menos un evaluador determinista (exact_match/schema/numeric_tolerance/executable) y uno semántico (semantic_similarity/model_graded/rubric/human_review).",
    "Deterministic and semantic scorers declared.": "Evaluadores deterministas y semánticos declarados.",
    "Need 2+ metamorphic transformations and a latest_run with no failing protected case (failing: {v}).":
        "Se necesitan 2 o más transformaciones metamórficas y un latest_run sin ningún caso protegido que falle (fallan: {v}).",
    "Metamorphic tests present; no protected regression.": "Hay pruebas metamórficas; ninguna regresión protegida.",
    "{n_threats} complete threats (asset, trust_boundary, control, test); need 4+.":
        "{n_threats} amenazas completas (asset, trust_boundary, control, test); se necesitan 4 o más.",
    "{n_threats} threats modelled.": "{n_threats} amenazas modeladas.",
    "Unresolved critical/high findings: {v}.": "Hallazgos críticos o altos sin resolver: {v}.",
    "No unresolved critical/high findings.": "Ningún hallazgo crítico o alto sin resolver.",
    "Report baseline and optimized heldout_score and set heldout_used_for_tuning to false (and mean it).":
        "Indica el heldout_score de la línea base y del optimizado, y pon heldout_used_for_tuning en false (y que sea verdad).",
    "Held-out {v} -> {v2}.": "Conjunto reservado {v} -> {v2}.",
    "Constraint problems after optimization: {v}.": "Problemas con las restricciones tras la optimización: {v}.",
    "Improvement within cost/latency limits and no protected failures.": "Mejora dentro de los límites de costo y latencia, sin fallos protegidos.",
    "Manifest needs code/prompt/tool-schema/model/dataset/eval versions, and ci_gate.blocks_on_protected_regression must be true.":
        "El manifiesto necesita las versiones de code/prompt/tool-schema/model/dataset/eval, y ci_gate.blocks_on_protected_regression debe ser true.",
    "Manifest and CI gate complete.": "Manifiesto y control de CI completos.",
    "Need trace events model_call/retrieval/tool_call, 2+ rollback criteria with drill_passed true, and a runbook with owner, kill_switch and rollback_steps.":
        "Se necesitan eventos de traza model_call/retrieval/tool_call, 2 o más criterios de marcha atrás con drill_passed en true, y un runbook con owner, kill_switch y rollback_steps.",
    "Observability, rollback drill and runbook complete.": "Observabilidad, simulacro de marcha atrás y runbook completos.",
    "{n_sc} scenarios with moe, users and measured result; need 2+.": "{n_sc} escenarios con moe, users y resultado medido; se necesitan 2 o más.",
    "{n_sc} validation scenarios measured.": "{n_sc} escenarios de validación medidos.",
    "Every scenario with achieved=false needs a gap_plan, and residual_risks must be listed.":
        "Cada escenario con achieved=false necesita un gap_plan, y hay que enumerar los residual_risks.",
    "Gaps and residual risks documented.": "Brechas y riesgos residuales documentados.",
    "Critical requirements without verification in the traceability matrix: {v}.": "Requisitos críticos sin verificación en la matriz de trazabilidad: {v}.",
    "{n_crit} critical requirements traced.": "{n_crit} requisitos críticos trazados.",
    "Unresolved high-severity findings: {v}.": "Hallazgos de gravedad alta sin resolver: {v}.",
    "No unresolved high-severity security finding.": "Ningún hallazgo de seguridad de gravedad alta sin resolver.",
    "The evaluation suite needs robustness-category cases and 2+ metamorphic transformations.":
        "El conjunto de pruebas de evaluación necesita casos de la categoría de robustez y 2 o más transformaciones metamórficas.",
    "Robustness and metamorphic cases included.": "Casos de robustez y metamórficos incluidos.",
    "Release manifest, rollback criteria with a passed drill, and a complete runbook are required.":
        "Se exigen el manifiesto de la versión, criterios de marcha atrás con un simulacro superado y un runbook completo.",
    "Release, rollback and runbook complete.": "Versión, marcha atrás y runbook completos.",
    "{n_tied} validation scenario(s) reference a defined MOE id with a measured result; need 2+.":
        "{n_tied} escenario(s) de validación hacen referencia a un ID de MOE definido con un resultado medido; se necesitan 2 o más.",
    "{n_tied} scenarios tied to MOEs.": "{n_tied} escenarios ligados a MOE.",
    "Integrity checks could not run: {v}.": "No se pudieron ejecutar las comprobaciones de integridad: {v}.",
    "Matches and discrepancies reference real rows; amounts balance; no double matching.":
        "Los emparejamientos y las discrepancias hacen referencia a filas reales; los importes cuadran; no hay emparejamientos dobles.",
    "reconcile() could not be evaluated: {v}.": "No se pudo evaluar reconcile(): {v}.",
    "unknown rows {b}/{l}": "filas desconocidas {b}/{l}",
    "row matched twice ({b}/{l})": "fila emparejada dos veces ({b}/{l})",
    "amounts disagree {b}/{l}": "los importes no coinciden {b}/{l}",
    "evidence {ev} does not exist": "la evidencia {ev} no existe",
    "no AI-FMEA": "sin AI-FMEA",
})
