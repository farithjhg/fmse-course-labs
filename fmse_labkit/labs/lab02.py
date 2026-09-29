"""Lab 02 - ConOps Builder (Module 2, Problem Formulation and Concept of Operations).

Guided: complete structured cells that produce a validated ConOps from a provided scenario.
Challenge (design): the CFO's bank-reconciliation "agent" request.
Public validator requirements (course spec, Module 02):
  CON-01 Problem statement does not prescribe a solution
  CON-02 At least 3 stakeholder groups
  CON-03 Nominal + exception + degraded scenario included
  CON-04 At least 3 measurable MOEs
  CON-05 Non-goals explicitly stated
The design defense (is an agent necessary?) is written in the portal reflection.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List

from ..core import Checker, check_public, register
from ..textutil import as_items, first, has_number, parse_document, text_of

LAB = "lab-02"

REQUIREMENTS = {
    "CON-01": ("Problem statement does not prescribe a solution", "correctness", False,
               "Describe the operational pain and the decision it affects. If the statement names an agent, a chatbot, RAG, or a model, it is describing a solution."),
    "CON-02": ("At least 3 stakeholder groups", "completeness", False,
               "Think beyond the requester: who is affected, who operates it, who must approve, who audits it?"),
    "CON-03": ("Nominal + exception + degraded scenario included", "robustness", False,
               "What happens when a dependency is unavailable or confidence is low? That is the degraded mode, and it is different from an exception."),
    "CON-04": ("At least 3 measurable MOEs", "correctness", False,
               "An MOE needs a stakeholder outcome, a metric, and a target someone could observe in realistic use."),
    "CON-05": ("Non-goals explicitly stated", "completeness", False,
               "Say what the system will deliberately not do. Non-goals bound the scope as much as goals do."),
}

CHALLENGE_REQUEST = (
    'A CFO says: "I want an AI agent that reconciles bank statements against Excel and tells us what is wrong."'
)

# Terms that name a solution rather than a problem.
SOLUTION_TERMS = re.compile(
    r"\b((an?|the|our)\s+(ai\s+|autonomous\s+|software\s+|intelligent\s+)?agent\b|ai\s+agents?|agentic|chat\s*bots?|(ai|virtual)\s+assistants?|copilot|llms?|large language models?|gpt[\w.-]*|gemini|claude|"
    r"rag|retrieval[- ]augmented|vector (database|store|db)|embeddings?|fine[- ]?tun\w*|prompts?|neural|machine learning model|"
    r"(use|using|with|via|build|deploy)\s+(an?\s+)?(ai|genai|generative ai)\b|ai[- ]powered|ai model)",
    re.I,
)


def _scenarios(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = first(doc, "scenarios", "operational_scenarios")
    out = []
    if isinstance(raw, list):
        for s in raw:
            if isinstance(s, dict):
                out.append({str(k).lower(): v for k, v in s.items()})
    elif isinstance(raw, dict):  # markdown: ### Nominal / ### Exception ...
        for k, v in raw.items():
            if k != "_text":
                out.append({"type": k, "description": v, "observable_outcome": v})
    return out


def _stakeholder_groups(doc: Dict[str, Any]) -> List[str]:
    raw = first(doc, "stakeholders", "actors", "stakeholder_groups")
    groups = []
    if isinstance(raw, list):
        for s in raw:
            if isinstance(s, dict):
                g = s.get("group") or s.get("name") or s.get("role")
                if g:
                    groups.append(str(g).strip().lower())
            elif str(s).strip():
                groups.append(str(s).split(":")[0].strip().lower())
    else:
        groups = [i.split(":")[0].strip().lower() for i in as_items(raw)]
    return sorted(set(g for g in groups if g))


def _moes(doc: Dict[str, Any]) -> List[Dict[str, str]]:
    raw = first(doc, "moes", "measures_of_effectiveness", "moe")
    out = []
    if isinstance(raw, list):
        for m in raw:
            if isinstance(m, dict):
                low = {str(k).lower(): str(v) for k, v in m.items()}
                out.append({"text": " ".join(low.values()), "target": low.get("target", ""), "metric": low.get("metric", ""),
                            "validation": low.get("validation_condition", low.get("validation", ""))})
            else:
                out.append({"text": str(m), "target": str(m), "metric": str(m), "validation": str(m)})
    else:
        for item in as_items(raw):
            out.append({"text": item, "target": item, "metric": item, "validation": item})
    return out


def validate(submission: Any, c: Checker) -> None:
    doc = parse_document(submission)

    problem = text_of(first(doc, "problem_statement", "problem", "problem_definition")).strip()
    words = len(problem.split())
    hit = SOLUTION_TERMS.search(problem)
    if words < 15:
        c.fail("CON-01", f"The problem statement has {words} words; it needs to describe the pain, who has it, and the consequence.")
    else:
        c.record("CON-01", hit is None, f"The problem statement presupposes a solution (\"{hit.group(0) if hit else ''}\").",
                 "The problem statement describes the need without prescribing a solution.")

    groups = _stakeholder_groups(doc)
    c.record("CON-02", len(groups) >= 3, f"Found {len(groups)} distinct stakeholder group(s); at least 3 are required.",
             f"{len(groups)} stakeholder groups identified.")
    c.evidence["stakeholder_groups"] = len(groups)

    scenarios = _scenarios(doc)
    types = {str(s.get("type", "")).strip().lower() for s in scenarios}
    missing_types = [t for t in ("nominal", "exception", "degraded") if not any(t in x for x in types)]
    no_outcome = [str(s.get("id") or s.get("title") or s.get("type")) for s in scenarios
                  if not str(s.get("observable_outcome") or s.get("outcome") or "").strip()]
    if missing_types:
        c.fail("CON-03", f"Missing scenario type(s): {', '.join(missing_types)}.")
    else:
        c.record("CON-03", not no_outcome, f"Scenario(s) without an observable outcome: {', '.join(no_outcome)}.",
                 "Nominal, exception and degraded scenarios each have an observable outcome.")

    moes = _moes(doc)
    measurable = [m for m in moes if has_number(m["target"]) and m["metric"].strip() and m["validation"].strip()]
    c.record("CON-04", len(measurable) >= 3,
             f"{len(measurable)} of {len(moes)} MOE(s) have a metric, a numeric target, and a validation condition; at least 3 are required.",
             f"{len(measurable)} measurable MOEs.")
    c.evidence["measurable_moes"] = len(measurable)

    non_goals = as_items(first(doc, "non_goals", "nongoals", "out_of_scope_goals"))
    c.record("CON-05", len(non_goals) >= 1, "No non-goals stated.", f"{len(non_goals)} non-goal(s) stated.")


def probes(submission: Any) -> List[Dict[str, Any]]:
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

    def solutionise(d):
        key = next((k for k in ("problem_statement", "problem", "problem_definition") if k in d), "problem_statement")
        d[key] = text_of(d.get(key)) + " We will build an AI agent with RAG to fix this."

    run("P1", "A solution smuggled into the problem statement", "CON-01", solutionise)

    def drop_degraded(d):
        key = next((k for k in ("scenarios", "operational_scenarios") if k in d), None)
        if isinstance(d.get(key), list):
            d[key] = [s for s in d[key] if "degraded" not in str(s.get("type", "")).lower()]
        elif isinstance(d.get(key), dict):
            d[key] = {k: v for k, v in d[key].items() if "degraded" not in k}

    run("P2", "Removing the degraded scenario", "CON-03", drop_degraded)

    def vague_moes(d):
        key = next((k for k in ("moes", "measures_of_effectiveness", "moe") if k in d), "moes")
        d[key] = [{"name": "Faster close", "metric": "speed", "target": "much faster", "validation_condition": "ask the CFO"}]

    run("P3", "MOEs without numeric targets", "CON-04", vague_moes)
    return cases


# Guided lab scenario: an IT service-desk triage request (the challenge uses a different domain).
GUIDED_SCENARIO = (
    "The head of IT support says: 'Our service desk is drowning in tickets. Password resets and access requests "
    "take the same queue as outages, and outages wait too long. Fix triage.'"
)

GUIDED_CONOPS_STARTER: Dict[str, Any] = {
    "problem_statement": "",  # TODO in the guided cells
    "system_boundary": {"in_scope": ["Classifying and routing incoming tickets"], "out_of_scope": ["Resolving tickets"]},
    "stakeholders": [
        {"group": "Service desk agents", "interest": "A queue ordered by urgency"},
        {"group": "Employees raising tickets", "interest": "Outages handled first"},
    ],
    "assumptions": ["Ticket text is available at submission time"],
    "scenarios": [
        {"id": "S1", "type": "nominal", "title": "Password reset routed to self-service", "observable_outcome": "Ticket closed via self-service link within 10 minutes"},
    ],
    "moes": [
        {"id": "MOE-1", "name": "Outage response", "metric": "median minutes from outage ticket to first agent action", "target": "under 15 minutes",
         "validation_condition": "Measured on live tickets over 4 weeks after rollout"},
    ],
    "non_goals": [],
}


register(LAB, REQUIREMENTS, validate, probes)
