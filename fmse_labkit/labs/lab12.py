"""Lab 12 - Evaluation Harness (Module 12, Evaluation Engineering and Verification/Validation).

Guided: build scorers over a provided claims-extraction system, then add metamorphic transformations.
Challenge: an evaluation suite that detects at least 90% of planted faults across correctness,
robustness, schema, and injection-resilience categories.
Public validator requirements (course spec, Module 12):
  EVL-01 Golden set categorized
  EVL-02 At least 3 scorer types
  EVL-03 Metamorphic transformations implemented
  EVL-04 Verification traceability present
  EVL-05 Validation scenario defined
  EVL-06 Fault-detection target met (>= 90% of planted faults, no false alarm on the correct system)  [critical]
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List

from ..core import Checker, call_learner, capture_output, register
from ..i18n import add_catalog, t as _t

LAB = "lab-12"
CATEGORIES = ("correctness", "robustness", "schema", "injection", "edge_case")
SCORER_TYPES = ("exact_match", "schema", "numeric_tolerance", "executable", "semantic_similarity", "model_graded", "human_review", "invariance")

REQUIREMENTS = {
    "EVL-01": ("Golden set categorized", "completeness", False,
               "Organise the golden set by capability, edge case, severity and provenance. Each item needs a category and a severity."),
    "EVL-02": ("At least 3 scorer types", "correctness", False,
               "Exact match alone misses whole classes of failure. Combine structural, numeric and behavioural scorers."),
    "EVL-03": ("Metamorphic transformations implemented", "robustness", False,
               "Define transformations under which the output must NOT change (reordering, padding, casing...) and use them as tests."),
    "EVL-04": ("Verification traceability present", "traceability", False,
               "Every critical requirement should map to at least one test id that exists in your golden set."),
    "EVL-05": ("Validation scenario defined", "operations", False,
               "Verification proves requirements; validation asks whether stakeholders get the intended outcome in realistic use. Describe one such scenario."),
    "EVL-06": ("Fault-detection target met", "robustness", True,
               "Look at which planted faults survive your suite. Each surviving mutant is a missing test: which category and which transformation would expose it?"),
}

CLAIM_REQUIREMENTS = {
    "CR-01": ("Extract policy number, amount and incident date for each claim", True),
    "CR-02": ("Amounts are numbers with cents preserved", True),
    "CR-03": ("Dates are ISO 8601 (YYYY-MM-DD); input dates are DD/MM/YYYY", True),
    "CR-04": ("Output conforms to the claims schema (no missing or extra fields)", True),
    "CR-05": ("Instructions inside the email never change the extraction", True),
    "CR-06": ("Irrelevant text and line order do not change the result", False),
}

_POLICY = re.compile(r"\bpolicy(?:\s+(?:no\.?|number))?\s*:?\s*(P-\d{6})", re.I)
_AMOUNT = re.compile(r"\bclaim(?:ed)? amount\s*:?\s*(?:EUR)?\s*([\d,]+\.\d{2})", re.I)
_DATE = re.compile(r"\bincident date\s*:?\s*(\d{2})/(\d{2})/(\d{4})", re.I)


def reference_system(text: str) -> List[Dict[str, Any]]:
    """The correct claims extractor (one claim per email). Instructions in the text are ignored by design."""
    p, a, d = _POLICY.search(text), _AMOUNT.search(text), _DATE.search(text)
    if not (p and a and d):
        return []
    def is_old(m):
        return re.search(r"old\s+$", text[max(0, m.start() - 6): m.start()], re.I) is not None

    if is_old(p):
        p = next((m for m in _POLICY.finditer(text) if not is_old(m)), p)
    return [{"policy_no": p.group(1).upper(), "amount": float(a.group(1).replace(",", "")), "incident_date": f"{d.group(3)}-{d.group(2)}-{d.group(1)}"}]


def _m_amount_truncated(t):
    return [{**c, "amount": float(int(c["amount"]))} for c in reference_system(t)]


def _m_date_swapped(t):
    out = []
    for c in reference_system(t):
        y, m, d = c["incident_date"].split("-")
        out.append({**c, "incident_date": f"{y}-{d}-{m}"})
    return out


def _m_first_policy(t):
    p = _POLICY.search(t)
    return [{**c, "policy_no": p.group(1).upper()} for c in reference_system(t)] if p else []


def _m_order_dependent(t):
    lines = t.splitlines()
    return reference_system(t) if lines and _POLICY.search(lines[0] + " " + (lines[1] if len(lines) > 1 else "")) else []


def _m_padding_fragile(t):
    return reference_system(t) if len(t) < 600 else []


def _m_case_sensitive(t):
    return reference_system(t) if ("Policy" in t or "policy" in t) else []


def _m_amount_string(t):
    return [{**c, "amount": f"{c['amount']:.2f}"} for c in reference_system(t)]


def _m_missing_date(t):
    return [{k: v for k, v in c.items() if k != "incident_date"} for c in reference_system(t)]


def _m_extra_field(t):
    return [{**c, "confidence": 0.9} for c in reference_system(t)]


def _m_obeys_zero(t):
    out = reference_system(t)
    if re.search(r"ignore (all )?(previous|prior) instructions", t, re.I):
        out = [{**c, "amount": 0.0} for c in out]
    return out


def _m_adds_fake_claim(t):
    out = reference_system(t)
    if re.search(r"(assistant|ai)[:,]? (also )?(add|create) (a|another) claim", t, re.I):
        out = out + [{"policy_no": "P-999999", "amount": 9999.0, "incident_date": "2026-01-01"}]
    return out


MUTANTS = {
    "M01-amount-truncated": ("correctness", _m_amount_truncated),
    "M02-date-swapped": ("correctness", _m_date_swapped),
    "M03-first-policy": ("correctness", _m_first_policy),
    "M04-order-dependent": ("robustness", _m_order_dependent),
    "M05-padding-fragile": ("robustness", _m_padding_fragile),
    "M06-case-sensitive": ("robustness", _m_case_sensitive),
    "M07-amount-string": ("schema", _m_amount_string),
    "M08-missing-date": ("schema", _m_missing_date),
    "M09-extra-field": ("schema", _m_extra_field),
    "M10-obeys-zero": ("injection", _m_obeys_zero),
    "M11-adds-fake-claim": ("injection", _m_adds_fake_claim),
}

CLAIM_SCHEMA = {
    "type": "object",
    "required": ["policy_no", "amount", "incident_date"],
    "additionalProperties": False,
    "properties": {"policy_no": {"type": "string", "pattern": r"^P-\d{6}$"}, "amount": {"type": "number", "minimum": 0},
                   "incident_date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}},
}

SAMPLE_EMAILS = [
    "Policy number: P-104233\nClaim amount: EUR 1,250.50\nIncident date: 03/07/2026\nWater damage in the kitchen.",
    "Hello, my policy no. P-220871 covers the car.\nIncident date: 21/08/2026\nClaimed amount: 480.00\nThanks.",
    "Old policy P-000111 was replaced last year.\nCurrent policy: P-555320\nIncident date: 11/02/2026\nClaim amount: 12,000.00",
    "POLICY NO P-771002\nINCIDENT DATE 30/09/2026\nCLAIM AMOUNT 75.25",
]


def validate(submission: Any, c: Checker) -> None:
    if not isinstance(submission, dict):
        raise ValueError("submit a dict with golden_set, scorers, transforms, traceability, validation_scenarios and run_suite")
    golden = [g for g in (submission.get("golden_set") or []) if isinstance(g, dict)]
    ok_items = [g for g in golden if g.get("id") and g.get("input") and g.get("category") in CATEGORIES and g.get("severity") in ("low", "medium", "high", "critical") and "expected" in g]
    cats = {g["category"] for g in ok_items}
    c.record("EVL-01", len(ok_items) >= 12 and len(cats) >= 4 and len(ok_items) == len(golden),
             _t('{n_ok_items} of {n_golden} golden items are well-formed (id, input, expected, category, severity) across {n_cats} categories; need 12+ items and 4+ categories ({v}).', n_ok_items=len(ok_items), n_golden=len(golden), n_cats=len(cats), v=', '.join(CATEGORIES)),
             _t('{n_ok_items} categorized golden items across {n_cats} categories.', n_ok_items=len(ok_items), n_cats=len(cats)))

    types = {s.get("type") for s in (submission.get("scorers") or []) if isinstance(s, dict) and callable(s.get("fn"))}
    c.record("EVL-02", len(types & set(SCORER_TYPES)) >= 3, _t("Found scorer types {v}; need at least 3 distinct types from {v2}, each with a callable 'fn'.", v=sorted(t for t in types if t), v2=', '.join(SCORER_TYPES)),
             _t('{n_types} scorer types.', n_types=len(types)))

    transforms = [t for t in (submission.get("transforms") or []) if isinstance(t, dict) and callable(t.get("fn"))]
    broken = []
    for t in transforms:
        changed = False
        for email in SAMPLE_EMAILS:
            out, err = call_learner(t["fn"], email)
            if err or not isinstance(out, str) or reference_system(out) != reference_system(email):
                broken.append(t.get("name", "?"))
                break
            changed = changed or out != email
        if not changed and t.get("name", "?") not in broken:
            broken.append(f"{t.get('name', '?')} (changes nothing)")
    c.record("EVL-03", len(transforms) >= 3 and not broken,
             _t('{n_transforms} transformation(s); need 3+ that change the text but not the correct extraction (not invariant: {v}).', n_transforms=len(transforms), v=', '.join(broken) or 'none'),
             _t('{n_transforms} invariant metamorphic transformations.', n_transforms=len(transforms)))

    trace = submission.get("traceability") or {}
    ids = {g.get("id") for g in golden}
    critical = [r for r, (_, crit) in CLAIM_REQUIREMENTS.items() if crit]
    untraced = [r for r in critical if not [t for t in trace.get(r, []) if t in ids]]
    c.record("EVL-04", not untraced, _t('Critical requirement(s) without a test in the golden set: {v}.', v=', '.join(untraced)), _t('Every critical requirement maps to existing tests.'))

    scen = [s for s in (submission.get("validation_scenarios") or []) if isinstance(s, dict) and all(str(s.get(k, "")).strip() for k in ("moe", "scenario", "users", "measure"))]
    c.record("EVL-05", bool(scen), _t('Define at least one validation scenario with moe, scenario, users and measure.'), _t('{n_scen} validation scenario(s).', n_scen=len(scen)))

    run_suite = submission.get("run_suite")
    if not callable(run_suite):
        c.fail("EVL-06", _t("Submit run_suite(system) -> {'passed': bool, 'failures': [...]}."))
        return
    with capture_output():
        base, err = call_learner(run_suite, reference_system)
        caught, survived = [], []
        for name, (_cat, fn) in MUTANTS.items():
            res, merr = call_learner(run_suite, fn)
            (caught if (merr is None and isinstance(res, dict) and res.get("passed") is False) else survived).append(name)
    false_alarm = err is not None or not isinstance(base, dict) or base.get("passed") is not True
    rate = len(caught) / len(MUTANTS)
    c.record("EVL-06", not false_alarm and rate >= 0.9,
             (_t('Your suite fails the correct system (false alarm). ') if false_alarm else "") + _t('Detected {n_caught}/{n_MUTANTS} planted faults ({rate:.0%}); surviving: {v}.', n_caught=len(caught), n_MUTANTS=len(MUTANTS), rate=rate, v=', '.join(survived) or 'none'),
             _t('Detected {n_caught}/{n_MUTANTS} planted faults ({rate:.0%}) with no false alarm.', n_caught=len(caught), n_MUTANTS=len(MUTANTS), rate=rate))
    c.evidence.update({"fault_detection": round(rate, 3), "surviving_mutants": len(survived)})


def probes(submission: Any) -> List[Dict[str, Any]]:
    run_suite = submission.get("run_suite") if isinstance(submission, dict) else None
    if not callable(run_suite):
        return []
    with capture_output():
        r1, _ = call_learner(run_suite, lambda t: reference_system(t) + reference_system(t))
        r2, _ = call_learner(run_suite, lambda t: [])
    return [
        {"id": "P1", "description": _t('A system that duplicates every claim is caught'), "ok": isinstance(r1, dict) and r1.get("passed") is False},
        {"id": "P2", "description": _t('A system that returns nothing is caught'), "ok": isinstance(r2, dict) and r2.get("passed") is False},
    ]


register(LAB, REQUIREMENTS, validate, probes)


add_catalog({
    "{n_ok_items} of {n_golden} golden items are well-formed (id, input, expected, category, severity) across {n_cats} categories; need 12+ items and 4+ categories ({v}).":
        "{n_ok_items} de {n_golden} elementos del conjunto de referencia están bien formados (id, input, expected, category, severity) en {n_cats} categorías; se necesitan 12 o más elementos y 4 o más categorías ({v}).",
    "{n_ok_items} categorized golden items across {n_cats} categories.": "{n_ok_items} elementos de referencia categorizados en {n_cats} categorías.",
    "Found scorer types {v}; need at least 3 distinct types from {v2}, each with a callable 'fn'.":
        "Tipos de evaluador encontrados: {v}; se necesitan al menos 3 tipos distintos de {v2}, cada uno con una función 'fn' invocable.",
    "{n_types} scorer types.": "{n_types} tipos de evaluador.",
    "{n_transforms} transformation(s); need 3+ that change the text but not the correct extraction (not invariant: {v}).":
        "{n_transforms} transformación(es); se necesitan 3 o más que cambien el texto sin cambiar la extracción correcta (no invariantes: {v}).",
    "{n_transforms} invariant metamorphic transformations.": "{n_transforms} transformaciones metamórficas invariantes.",
    "Critical requirement(s) without a test in the golden set: {v}.": "Requisitos críticos sin ninguna prueba en el conjunto de referencia: {v}.",
    "Every critical requirement maps to existing tests.": "Cada requisito crítico se corresponde con pruebas existentes.",
    "Define at least one validation scenario with moe, scenario, users and measure.":
        "Define al menos un escenario de validación con moe, scenario, users y measure.",
    "{n_scen} validation scenario(s).": "{n_scen} escenario(s) de validación.",
    "Detected {n_caught}/{n_MUTANTS} planted faults ({rate:.0%}) with no false alarm.":
        "Se detectaron {n_caught}/{n_MUTANTS} fallos sembrados a propósito ({rate:.0%}) sin ninguna falsa alarma.",
    "Submit run_suite(system) -> {'passed': bool, 'failures': [...]}.": "Entrega run_suite(system) -> {'passed': bool, 'failures': [...]}.",
    "Detected {n_caught}/{n_MUTANTS} planted faults ({rate:.0%}); surviving: {v}.":
        "Se detectaron {n_caught}/{n_MUTANTS} fallos sembrados a propósito ({rate:.0%}); sobreviven: {v}.",
    "A system that duplicates every claim is caught": "Se detecta un sistema que duplica cada reclamación",
    "A system that returns nothing is caught": "Se detecta un sistema que no devuelve nada",
    "Your suite fails the correct system (false alarm). ": "Tu conjunto de pruebas hace fallar al sistema correcto (falsa alarma). ",
})
