"""Lab 03 - Requirements and AI-FMEA Workbench (Module 3).

Guided: write requirements in YAML, calculate RPN values, run a linter that
checks uniqueness, verifiability metadata, and traceability.
Challenge: an invoice-to-payment assistant with planted failure modes; produce
12+ requirements and an AI-FMEA covering at least 10 failure modes, including
indirect prompt injection and excessive agency.
Public validator requirements (course spec, Module 03):
  REQ-01 Every requirement has ID, statement, rationale, verification method
  REQ-02 No duplicate IDs
  REQ-03 At least one requirement in each required category
  REQ-04 RPN arithmetic correct
  REQ-05 Every high-severity failure has at least one mitigation and verification link  [critical]
  REQ-06 At least 12 requirements and 10 failure modes, including indirect prompt injection and excessive agency (challenge brief)
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List

from ..core import Checker, check_public, register
from ..textutil import parse_document

LAB = "lab-03"
REQUIRED_CATEGORIES = ("functional", "performance", "interface", "security", "cost", "operational")
VERIFICATION_METHODS = ("test", "analysis", "inspection", "demonstration")
HIGH_SEVERITY = 8  # severity 8-10 on the course's 1-10 scale

REQUIREMENTS = {
    "REQ-01": ("Every requirement has ID, statement, rationale, verification method", "traceability", False,
               "A requirement nobody can verify is a wish. Each needs a 'shall' statement, a reason it exists, and how you will prove it (test, analysis, inspection or demonstration)."),
    "REQ-02": ("No duplicate IDs", "correctness", False,
               "Traceability breaks the moment two items share an identifier. IDs must be unique across requirements and across failure modes."),
    "REQ-03": ("At least one requirement in each required category", "completeness", False,
               "Revisit lesson 3.2: functional behaviour is only one category. Look for performance, interface, security, cost and operational obligations too."),
    "REQ-04": ("RPN arithmetic correct", "correctness", False,
               "RPN is Severity x Occurrence x Detection, each on a 1-10 scale. Recompute every row rather than estimating the product."),
    "REQ-05": ("Every high-severity failure has at least one mitigation and verification link", "traceability", True,
               "For each failure with severity 8 or more: which control reduces it, and which requirement proves that control works?"),
    "REQ-06": ("At least 12 requirements and 10 failure modes, including indirect prompt injection and excessive agency", "completeness", False,
               "The assistant reads documents it did not write and can trigger payments. Which failure modes does that create?"),
}

SCENARIO = (
    "An invoice-to-payment assistant reads supplier invoices (PDF text), extracts payee, amount, IBAN and due date, "
    "matches them to purchase orders, and proposes payments for approval in the ERP. Suppliers can put any text in an invoice."
)

# Guided lab starter: deliberately flawed (duplicate id, missing verification, wrong RPN, missing categories).
GUIDED_STARTER = """
requirements:
  - id: FR-01
    category: functional
    statement: The assistant shall extract the payee name, amount, currency, IBAN and due date from each invoice.
    rationale: Payment proposals need all five fields.
    verification_method: test
  - id: FR-01
    category: functional
    statement: The assistant shall match each invoice to an open purchase order.
    rationale: Unmatched invoices must not be paid.
  - id: PR-01
    category: performance
    statement: Extraction shall complete within 30 seconds per invoice at the 95th percentile.
    rationale: The AP team processes 400 invoices per day.
    verification_method: test
fmea:
  - id: FM-01
    failure_mode: Amount extracted from the wrong total line
    effect: Supplier overpaid
    severity: 8
    occurrence: 4
    detection: 5
    rpn: 150
    mitigations: []
    verification: []
"""


def _as_list(doc: Dict[str, Any], *keys: str) -> List[Dict[str, Any]]:
    for k in keys:
        v = doc.get(k)
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
    return []


def _norm(d: Dict[str, Any]) -> Dict[str, Any]:
    return {re.sub(r"[^a-z0-9]+", "_", str(k).lower()).strip("_"): v for k, v in d.items()}


def _int(v: Any):
    try:
        i = int(v)
        return i if 1 <= i <= 10 else None
    except (TypeError, ValueError):
        return None


def validate(submission: Any, c: Checker) -> None:
    doc = parse_document(submission)
    reqs = [_norm(r) for r in _as_list(doc, "requirements", "system_requirements")]
    fmea = [_norm(f) for f in _as_list(doc, "fmea", "ai_fmea", "failure_modes")]

    incomplete = []
    for r in reqs:
        rid = str(r.get("id") or "?")
        stmt = str(r.get("statement") or "")
        method = str(r.get("verification_method") or r.get("verification") or "").lower()
        if not r.get("id") or "shall" not in stmt.lower() or not str(r.get("rationale") or "").strip() or not any(m in method for m in VERIFICATION_METHODS):
            incomplete.append(rid)
    if not reqs:
        c.fail("REQ-01", "No requirements found under 'requirements'.")
    else:
        c.record("REQ-01", not incomplete, f"Requirement(s) {', '.join(incomplete[:8])} lack a 'shall' statement, a rationale, or a verification method (test/analysis/inspection/demonstration).",
                 f"All {len(reqs)} requirements are complete and verifiable.")

    ids = [str(x.get("id")) for x in reqs + fmea if x.get("id")]
    dups = sorted({i for i in ids if ids.count(i) > 1})
    c.record("REQ-02", bool(ids) and not dups, f"Duplicate id(s): {', '.join(dups)}." if dups else "No ids found.", "All ids are unique.")

    cats = {str(r.get("category") or "").strip().lower() for r in reqs}
    missing = [k for k in REQUIRED_CATEGORIES if k not in cats]
    c.record("REQ-03", not missing, f"No requirement in categor{'y' if len(missing) == 1 else 'ies'}: {', '.join(missing)}.", "Every required category is covered.")

    wrong = []
    for f in fmea:
        s, o, d = _int(f.get("severity")), _int(f.get("occurrence")), _int(f.get("detection"))
        try:
            rpn = int(f.get("rpn"))
        except (TypeError, ValueError):
            rpn = None
        if None in (s, o, d) or rpn != s * o * d:
            wrong.append(str(f.get("id") or "?"))
    if not fmea:
        c.fail("REQ-04", "No AI-FMEA rows found under 'fmea'.")
    else:
        c.record("REQ-04", not wrong, f"RPN is missing or wrong (or a score is outside 1-10) for: {', '.join(wrong[:8])}.", "RPN arithmetic is correct on every row.")

    req_ids = {str(r.get("id")) for r in reqs if r.get("id")}
    uncovered = []
    for f in fmea:
        if (_int(f.get("severity")) or 0) >= HIGH_SEVERITY:
            mitig = f.get("mitigations") or f.get("mitigation")
            links = f.get("verification") or f.get("verified_by") or []
            links = [links] if isinstance(links, str) else list(links or [])
            if not mitig or not any(str(l) in req_ids for l in links):
                uncovered.append(str(f.get("id") or "?"))
    high = sum(1 for f in fmea if (_int(f.get("severity")) or 0) >= HIGH_SEVERITY)
    c.record("REQ-05", bool(fmea) and not uncovered,
             f"High-severity failure(s) without a mitigation or without a verification link to an existing requirement: {', '.join(uncovered[:8])}." if fmea else "No failure modes to check.",
             f"All {high} high-severity failures have mitigations linked to verifying requirements.")

    text = " ".join(str(f.get("failure_mode", "")) + " " + str(f.get("cause", "")) for f in fmea).lower()
    has_injection = bool(re.search(r"(indirect|document|invoice|embedded).{0,40}injection|injection.{0,40}(document|invoice|indirect)", text))
    has_agency = bool(re.search(r"excessive agency|over-?privileg|unauthori[sz]ed (payment|action|write)|autonomous (payment|action)", text))
    problems = []
    if len(reqs) < 12:
        problems.append(f"{len(reqs)} requirements (need 12+)")
    if len(fmea) < 10:
        problems.append(f"{len(fmea)} failure modes (need 10+)")
    if not has_injection:
        problems.append("no indirect prompt injection failure mode")
    if not has_agency:
        problems.append("no excessive agency failure mode")
    c.record("REQ-06", not problems, "Coverage gaps: " + "; ".join(problems) + ".", f"{len(reqs)} requirements and {len(fmea)} failure modes, including injection and agency.")
    c.evidence.update({"requirements": len(reqs), "failure_modes": len(fmea), "high_severity": high})


def rpn(severity: int, occurrence: int, detection: int) -> int:
    """Risk Priority Number - a prioritization aid, not a probability."""
    return int(severity) * int(occurrence) * int(detection)


def lint(submission: Any) -> None:
    """Guided-lab linter: the same checks as the validator, printed as a lint report."""
    check_public(LAB, submission).show()


def probes(submission: Any) -> List[Dict[str, Any]]:
    try:
        base = parse_document(submission)
    except Exception:  # noqa: BLE001
        return []
    out = []

    def run(pid, description, target, mutate):
        doc = copy.deepcopy(base)
        try:
            mutate(doc)
        except Exception:  # noqa: BLE001
            return
        res = check_public(LAB, doc)
        out.append({"id": pid, "description": f"{description} is caught by {target}", "ok": any(ch.id == target and ch.status == "fail" for ch in res.checks)})

    def dup(d):
        rs = d["requirements"]
        rs.append(dict(rs[0]))

    run("P1", "A duplicated requirement id", "REQ-02", dup)

    def bad_rpn(d):
        d["fmea"][0]["rpn"] = int(d["fmea"][0]["rpn"]) + 1

    run("P2", "An off-by-one RPN", "REQ-04", bad_rpn)

    def strip(d):
        for f in d["fmea"]:
            if int(f["severity"]) >= HIGH_SEVERITY:
                f["mitigations"] = []
                return

    run("P3", "A high-severity failure with its mitigations removed", "REQ-05", strip)
    return out


register(LAB, REQUIREMENTS, validate, probes)
