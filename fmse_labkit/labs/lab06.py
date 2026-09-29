"""Lab 06 - Architecture Trade Study Workbench (Module 6, Architecture Patterns and Trade Studies).

Guided: complete candidate matrices and sensitivity plots from supplied benchmark data.
Challenge (design): three architectures for a high-volume support workflow with strict security
and cost constraints; select one only after measured/estimated trade analysis.
Public validator requirements (course spec, Module 06):
  ARC-01 >=3 credible alternatives
  ARC-02 Criteria trace to requirements
  ARC-03 Weights sum to 1
  ARC-04 Sensitivity analysis executed
  ARC-05 Decision includes reversal/revisit conditions
The architecture defense itself is assessed with the design rubric in the portal.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List

from ..core import Checker, check_public, register

LAB = "lab-06"

REQUIREMENTS = {
    "ARC-01": (">=3 credible alternatives", "completeness", False,
               "Generate genuinely different concepts - different patterns on the autonomy spectrum - each described well enough to be evaluated."),
    "ARC-02": ("Criteria trace to requirements", "traceability", False,
               "Every criterion should exist because a requirement exists. Name the requirement ids each criterion measures."),
    "ARC-03": ("Weights sum to 1", "correctness", False,
               "Weights express operational priority as shares of one whole; normalise them."),
    "ARC-04": ("Sensitivity analysis executed", "robustness", False,
               "Perturb the two highest weights by +/-20%, renormalise the rest, and recompute which alternative wins each time."),
    "ARC-05": ("Decision includes reversal/revisit conditions", "operations", False,
               "An ADR states when it should be revisited. Write triggers someone could observe, with thresholds."),
}

PATTERNS = ("single_call", "deterministic_pipeline", "prompt_chain", "workflow_orchestrator", "tool_using_agent", "multi_agent")

SCENARIO = {
    "name": "High-volume customer-support workflow",
    "requirements": {
        "SR-VOL-01": "The system shall process 50,000 tickets per day.",
        "SR-QUAL-01": "Tickets shall be routed to the correct queue at least 95% of the time.",
        "SR-LAT-01": "A routing decision shall be available within 5 s at the 95th percentile.",
        "SR-COST-01": "Model and tool cost shall not exceed 0.02 per ticket.",
        "SR-SEC-01": "Customer personal data shall not leave the tenant; refunds require human approval.",
        "SR-AUD-01": "Every automated action shall be traceable to its inputs and model version.",
    },
}

# Supplied (estimated) benchmark data per pattern, for the guided matrix.
BENCHMARK = {
    "single_call": {"routing_accuracy": 0.90, "cost_per_ticket": 0.004, "p95_latency_s": 1.8, "mutation_risk": "none", "auditability": "high"},
    "deterministic_pipeline": {"routing_accuracy": 0.93, "cost_per_ticket": 0.006, "p95_latency_s": 2.2, "mutation_risk": "none", "auditability": "high"},
    "prompt_chain": {"routing_accuracy": 0.95, "cost_per_ticket": 0.011, "p95_latency_s": 3.9, "mutation_risk": "low", "auditability": "medium"},
    "workflow_orchestrator": {"routing_accuracy": 0.96, "cost_per_ticket": 0.013, "p95_latency_s": 4.1, "mutation_risk": "low", "auditability": "high"},
    "tool_using_agent": {"routing_accuracy": 0.97, "cost_per_ticket": 0.031, "p95_latency_s": 9.5, "mutation_risk": "high", "auditability": "medium"},
    "multi_agent": {"routing_accuracy": 0.97, "cost_per_ticket": 0.058, "p95_latency_s": 14.0, "mutation_risk": "high", "auditability": "low"},
}


def weighted_totals(scores: Dict[str, Dict[str, float]], criteria: List[Dict[str, Any]]) -> Dict[str, float]:
    """Weighted sum per alternative; scores are 1-5 where higher is better on every criterion."""
    return {alt: round(sum(float(c["weight"]) * float(s.get(c["id"], 0)) for c in criteria), 6) for alt, s in scores.items()}


def winner(scores: Dict[str, Dict[str, float]], criteria: List[Dict[str, Any]]) -> str:
    totals = weighted_totals(scores, criteria)
    return max(sorted(totals), key=lambda a: totals[a])


def perturb(criteria: List[Dict[str, Any]], crit_id: str, delta: float) -> List[Dict[str, Any]]:
    """Scale one weight by (1+delta) and renormalise all weights to sum to 1 (the course's sensitivity convention)."""
    out = [dict(c) for c in criteria]
    for c in out:
        if c["id"] == crit_id:
            c["weight"] = float(c["weight"]) * (1 + delta)
    total = sum(float(c["weight"]) for c in out)
    for c in out:
        c["weight"] = float(c["weight"]) / total
    return out


def validate(submission: Any, c: Checker) -> None:
    if not isinstance(submission, dict):
        raise ValueError("submit a dict with alternatives, criteria, scores, sensitivity and decision")
    alts = [a for a in (submission.get("alternatives") or []) if isinstance(a, dict)]
    good = [a for a in alts if a.get("id") and a.get("pattern") in PATTERNS and len(str(a.get("description", "")).split()) >= 8]
    patterns = {a["pattern"] for a in good}
    c.record("ARC-01", len(good) >= 3 and len(patterns) >= 3,
             f"{len(good)} well-described alternative(s) using {len(patterns)} distinct pattern(s); need 3 of each (patterns: {', '.join(PATTERNS)}).",
             f"{len(good)} alternatives across {len(patterns)} patterns.")

    crits = [x for x in (submission.get("criteria") or []) if isinstance(x, dict)]
    untraced = [str(x.get("id", "?")) for x in crits if not x.get("requirements") or any(r not in SCENARIO["requirements"] for r in x.get("requirements", []))]
    c.record("ARC-02", bool(crits) and not untraced, f"Criteria without valid requirement links: {', '.join(untraced) or 'no criteria'} (use ids from SCENARIO['requirements']).",
             "Every criterion traces to scenario requirements.")

    try:
        weights = [float(x["weight"]) for x in crits]
    except (KeyError, TypeError, ValueError):
        weights = []
    total = sum(weights)
    c.record("ARC-03", bool(weights) and all(w > 0 for w in weights) and abs(total - 1) < 1e-6,
             f"Weights sum to {total:.4f}" + (" and include non-positive values" if any(w <= 0 for w in weights) else "") + "; they must be positive and sum to 1.",
             "Weights are positive and sum to 1.")

    scores = submission.get("scores") or {}
    sens = [s for s in (submission.get("sensitivity") or []) if isinstance(s, dict)]
    problems = []
    if len(crits) >= 2 and weights and scores:
        top2 = [x["id"] for x in sorted(crits, key=lambda x: -float(x["weight"]))[:2]]
        for cid in top2:
            for delta in (0.2, -0.2):
                row = next((s for s in sens if s.get("criterion") == cid and abs(float(s.get("delta", 0)) - delta) < 1e-9), None)
                if row is None:
                    problems.append(f"missing {cid} {delta:+.0%}")
                    continue
                expected = winner(scores, perturb(crits, cid, delta))
                if row.get("winner") != expected:
                    problems.append(f"{cid} {delta:+.0%} reports {row.get('winner')!r}")
    else:
        problems.append("no scored criteria to perturb")
    c.record("ARC-04", not problems, "Sensitivity analysis incomplete or not reproducible: " + "; ".join(problems[:4]) + ".", "Top-2 weights perturbed +/-20%; winners reproduce.")

    decision = submission.get("decision") or {}
    triggers = [t for t in (decision.get("revisit_triggers") or []) if isinstance(t, str) and re.search(r"\d|>|<|exceed|drops? below|above", t)]
    missing = [k for k in ("selected", "context", "rationale", "consequences") if not decision.get(k)]
    if decision.get("selected") not in {a.get("id") for a in alts}:
        missing.append("selected must be one of your alternative ids")
    c.record("ARC-05", not missing and bool(triggers), f"ADR incomplete: {', '.join(missing) or 'no measurable revisit trigger'}.",
             f"Decision recorded with {len(triggers)} measurable revisit trigger(s).")
    if weights and scores:
        c.evidence["baseline_winner"] = winner(scores, crits)


def probes(submission: Any) -> List[Dict[str, Any]]:
    if not isinstance(submission, dict):
        return []
    out = []

    def run(pid, description, target, mutate):
        s = copy.deepcopy(submission)
        try:
            mutate(s)
        except Exception:  # noqa: BLE001
            return
        res = check_public(LAB, s)
        out.append({"id": pid, "description": f"{description} is caught by {target}", "ok": any(ch.id == target and ch.status == "fail" for ch in res.checks)})

    run("P1", "Weights that sum to 1.1", "ARC-03", lambda s: s["criteria"][0].__setitem__("weight", float(s["criteria"][0]["weight"]) + 0.1))
    run("P2", "A sensitivity row with a guessed winner", "ARC-04", lambda s: s["sensitivity"][0].__setitem__("winner", "not-a-real-alternative"))
    run("P3", "An ADR without revisit triggers", "ARC-05", lambda s: s["decision"].__setitem__("revisit_triggers", []))
    return out


register(LAB, REQUIREMENTS, validate, probes)
