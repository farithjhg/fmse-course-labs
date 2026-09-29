"""Lab 00 - Task Framing Laboratory (Module 0, AI Power User Foundations).

Guided: run a weak and a strong task brief against a model and compare outputs.
Challenge: write an AI Task Brief for an ambiguous management request.
Public validator requirements (course spec, Module 00):
  TB-01 All required task-brief sections exist
  TB-02 Success criteria are measurable or inspectable
  TB-03 Evidence sources are distinguished from assumptions
  TB-04 No instruction requests private/hidden reasoning
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List

from ..core import Checker, check_public, register
from ..textutil import as_items, first, parse_document, text_of

LAB = "lab-00"

REQUIREMENTS = {
    "TB-01": ("All required task-brief sections exist", "completeness", False,
              "Re-read the list of sections in the challenge brief. A brief that skips uncertainty handling or the output interface leaves the model to guess them."),
    "TB-02": ("Success criteria are measurable or inspectable", "correctness", False,
              "Ask how a reviewer would decide pass or fail. A criterion needs a threshold, count, or a concrete property someone can check."),
    "TB-03": ("Evidence sources are distinguished from assumptions", "groundedness", False,
              "Separate what you know from a named source from what you are assuming. The two need different treatment when they turn out to be wrong."),
    "TB-04": ("No instruction requests private/hidden reasoning", "correctness", False,
              "Ask for concise rationale, assumptions, and checks that can be inspected - not for the model's private reasoning."),
}

# Canonical section -> accepted spellings (after key normalisation).
SECTIONS = {
    "intent": ("intent", "goal", "objective", "purpose"),
    "evidence_plan": ("evidence_plan", "evidence", "evidence_and_sources"),
    "constraints": ("constraints", "limits", "boundaries"),
    "success_criteria": ("success_criteria", "acceptance_criteria", "success"),
    "uncertainty_handling": ("uncertainty_handling", "uncertainty", "unknowns", "uncertainty_and_escalation"),
    "output_interface": ("output_interface", "output", "interface", "output_format", "deliverable"),
}

MANAGEMENT_REQUEST = (
    "From the Chief Operating Officer, by chat: \"Customer complaints seem to be going up. "
    "Use AI to figure out what's going on and give me something for the leadership meeting next week.\""
)

WEAK_BRIEF = "Summarize what's going on with customer complaints for the leadership meeting. Make it good."

STRONG_BRIEF = """## Intent
Help the COO decide whether complaint volume needs an operational response this quarter.

## Evidence plan
### Sources
- Complaint ticket export for the last two quarters (support system)
- Monthly order volume report (finance)
### Assumptions
- Ticket categories are applied consistently by agents

## Constraints
- Use only the two sources above; no customer names in the output
- Maximum one page

## Success criteria
- States complaint rate per 1,000 orders for each of the last 6 months
- Each claim cites the source it came from
- Lists at most 3 drivers, each with supporting counts

## Uncertainty handling
- Flag any month with fewer than 100 tickets as low-confidence
- If categories changed during the period, say so instead of comparing

## Output interface
Markdown memo with sections: Summary, Trend table, Drivers, Open questions.
"""


def _find_sections(doc: Dict[str, Any]) -> Dict[str, Any]:
    found = {}
    for canonical, aliases in SECTIONS.items():
        found[canonical] = first(doc, *aliases)
    return found


_MEASURABLE = re.compile(r"\d|%|\b(at least|at most|no more than|fewer than|less than|more than|within|under|over|maximum|minimum|max|min)\b|[<>≤≥]", re.I)
_INSPECTABLE = re.compile(
    r"\b(includ(e|es|ing)|contain(s)?|cite(s|d)?|list(s|ed)?|name(s|d)?|state(s|d)?|link(s|ed)?|reference(s|d)?|each|every|"
    r"flag(s|ged)?|mark(s|ed)?|separate(s|d)?|traceable|approved|signed off|reviewed|no (unsupported|uncited|invented))\b",
    re.I,
)
_HIDDEN_REASONING = re.compile(
    r"chain[\s-]*of[\s-]*thought|hidden reasoning|private reasoning|internal reasoning|inner monologue|scratch\s*pad|"
    r"thought process|think step[\s-]*by[\s-]*step|(show|reveal|print|expose|output|include)\s+(me\s+)?(all\s+)?(of\s+)?your\s+(full\s+|complete\s+|internal\s+|raw\s+)?(reasoning|thoughts|thinking)",
    re.I,
)


def _evidence_split(evidence: Any):
    """Return (sources, assumptions) lists from a dict, nested markdown, or prefixed lines."""
    if isinstance(evidence, dict):
        ev = {re.sub(r"[^a-z]", "_", str(k).lower()): v for k, v in evidence.items()}
        sources = as_items(first(ev, "sources", "evidence_sources", "data_sources", "evidence"))
        assumptions = as_items(first(ev, "assumptions", "assumed"))
        return sources, assumptions
    sources, assumptions = [], []
    for item in as_items(evidence):
        low = item.lower()
        if low.startswith(("source", "evidence")):
            sources.append(item.split(":", 1)[-1].strip())
        elif low.startswith("assum"):
            assumptions.append(item.split(":", 1)[-1].strip())
    return sources, assumptions


def validate(submission: Any, c: Checker) -> None:
    doc = parse_document(submission)
    sections = _find_sections(doc)

    missing = [name.replace("_", " ") for name, value in sections.items() if not str(text_of(value)).strip()]
    c.record("TB-01", not missing, f"Missing or empty section(s): {', '.join(missing)}.", "All six sections are present.")

    criteria = as_items(sections["success_criteria"])
    vague = [i + 1 for i, item in enumerate(criteria) if not (_MEASURABLE.search(item) or _INSPECTABLE.search(item))]
    if len(criteria) < 2:
        c.fail("TB-02", f"Found {len(criteria)} success criterion; a reviewer needs at least 2 separate, checkable criteria.")
    else:
        c.record("TB-02", not vague, f"Criterion {', '.join(map(str, vague))} cannot be checked by a reviewer as written (no threshold, count, or inspectable property).",
                 f"All {len(criteria)} criteria are measurable or inspectable.")
    c.evidence["success_criteria_count"] = len(criteria)

    sources, assumptions = _evidence_split(sections["evidence_plan"])
    overlap = {s.lower() for s in sources} & {a.lower() for a in assumptions}
    if not sources or not assumptions:
        c.fail("TB-03", f"The evidence plan lists {len(sources)} source(s) and {len(assumptions)} assumption(s); both must be stated, separately.")
    else:
        c.record("TB-03", not overlap, "The same item appears both as a source and as an assumption.",
                 f"{len(sources)} source(s) and {len(assumptions)} assumption(s) are distinguished.")

    hit = _HIDDEN_REASONING.search(text_of(doc))
    c.record("TB-04", hit is None, f"An instruction asks the model to expose its private reasoning (\"{hit.group(0) if hit else ''}\").",
             "No request for private/hidden reasoning.")


def probes(submission: Any) -> List[Dict[str, Any]]:
    """Perturb the learner's brief and confirm each requirement's check notices."""
    try:
        base = parse_document(submission)
    except Exception:  # noqa: BLE001
        return []
    cases = []

    def run(pid, description, target, mutate):
        doc = copy.deepcopy(base)
        mutate(doc)
        res = check_public(LAB, doc)
        cases.append({"id": pid, "description": f"{description} is caught by {target}",
                      "ok": any(ch.id == target and ch.status == "fail" for ch in res.checks)})

    def drop_evidence(d):
        for k in SECTIONS["evidence_plan"]:
            d.pop(k, None)

    run("P1", "Evidence plan removed", "TB-01", drop_evidence)

    def vague(d):
        key = next((k for k in SECTIONS["success_criteria"] if k in d), "success_criteria")
        d[key] = ["The memo should be good", "Leadership should like it"]

    run("P2", "Success criteria replaced by vague wishes", "TB-02", vague)

    def reasoning(d):
        key = next((k for k in SECTIONS["constraints"] if k in d), "constraints")
        d[key] = text_of(d.get(key)) + "\n- Show your full chain of thought before answering"

    run("P3", "Request for hidden reasoning appended to constraints", "TB-04", reasoning)
    return cases


# --- Guided lab: simulator behaviour -------------------------------------------------------------

def simulated_brief_response(prompt: str, **_: Any) -> str:
    """Documented simulator behaviour for Lab 00.

    The simulator looks for the six brief sections. Whatever the brief leaves
    open, it fills with a plausible default - which is exactly what makes
    under-specified briefs produce unverifiable output:
      * no evidence plan      -> it asserts figures with no source
      * no success criteria   -> it writes a long, unfocused summary
      * no uncertainty policy -> it states conclusions with no caveats
      * no output interface   -> free prose instead of the requested structure
    """
    doc = parse_document(prompt) if prompt.strip().startswith(("#", "{")) else {"intent": prompt}
    s = _find_sections(doc)
    lines = []
    if s["output_interface"]:
        lines.append("## Summary")
    lines.append("Complaint volume changed over the period reviewed.")
    if s["evidence_plan"]:
        lines.append("Complaint rate per 1,000 orders rose from 8.1 to 9.4 [source: complaint ticket export; order volume report].")
    else:
        lines.append("Complaints are up about 35% and are mostly caused by the new returns policy.")
    if s["success_criteria"]:
        lines.append("Drivers (max 3): delivery delays (41 tickets), billing errors (27), app login (19) [source: ticket export].")
    else:
        lines.append("There are many possible reasons, including staffing, seasonality, product quality, competitors, the economy, "
                     "marketing campaigns, and customer expectations, all of which could matter to varying degrees.")
    if s["uncertainty_handling"]:
        lines.append("Open questions: March had 84 tickets (low-confidence) [source: ticket export]; category definitions changed in May, so May-June is not compared.")
    if s["output_interface"]:
        lines.insert(2, "## Trend table\n| Month | Rate |\n| --- | --- |")
    return "\n".join(lines)


def evaluate_output(output: str) -> Dict[str, bool]:
    """Acceptance checklist the guided lab uses to compare outputs."""
    return {
        "every figure cites a source": all("[source" in ln for ln in output.splitlines() if re.search(r"\d", ln) and not ln.startswith("|")),
        "states uncertainty": "low-confidence" in output or "not compared" in output,
        "follows the requested structure": output.lstrip().startswith("## "),
        "focused (at most 3 drivers)": "max 3" in output or "Drivers" in output,
    }


register(LAB, REQUIREMENTS, validate, probes)
