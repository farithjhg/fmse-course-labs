"""Lab 15 - CI Gate Simulator (Module 15, Production AI Engineering, CI/CD, and Observability).

Guided: run an evaluation matrix against two releases and decide whether deployment should proceed.
Challenge: build a release package with automated gates, observability schema, rollback criteria,
and incident runbook.
Public validator requirements (course spec, Module 15):
  REL-01 Release manifest complete
  REL-02 High-severity eval gate blocking                 [critical]
  REL-03 Rollback criteria explicit
  REL-04 Trace schema covers model/retrieval/tool events
  REL-05 Cost and latency SLOs linked to requirements
  REL-06 Release simulation PASS (gate)
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..core import Checker, call_learner, capture_output, register

LAB = "lab-15"

REQUIREMENTS = {
    "REL-01": ("Release manifest complete", "reproducibility", False,
               "A deployment is a configuration bundle: code, prompts, tool schemas, model/config, dataset and eval versions, and the thresholds used."),
    "REL-02": ("High-severity eval gate blocking", "security", True,
               "An average can improve while a protected case breaks. Any failing high-severity case must block, whatever the aggregate."),
    "REL-03": ("Rollback criteria explicit", "operations", False,
               "Write the conditions that trigger rollback as metric, threshold and window - and make them executable on canary metrics."),
    "REL-04": ("Trace schema covers model/retrieval/tool events", "operations", False,
               "Reconstructing a failure needs model calls, retrieval and tool calls in one trace, with ids, timing and versions."),
    "REL-05": ("Cost and latency SLOs linked to requirements", "cost", False,
               "Each SLO exists because a requirement does: give its threshold and the requirement id it verifies."),
    "REL-06": ("Release simulation PASS", "correctness", False,
               "Run your gate on every candidate: noise within tolerance promotes; protected regressions, SLO breaches and schema failures block."),
}

NFR_REQUIREMENTS = {
    "NFR-LAT-01": "p95 end-to-end latency shall not exceed 2000 ms.",
    "NFR-COST-01": "Mean cost per task shall not exceed 0.010.",
    "NFR-QUAL-01": "Task quality shall not drop by more than 2 points versus the current release.",
    "NFR-SAFE-01": "No high-severity protected case may fail.",
}

MANIFEST_KEYS = ("release_id", "code_version", "prompt_versions", "tool_schema_versions", "model", "dataset_version", "eval_suite_version", "thresholds")
TRACE_EVENTS = {
    "model_call": ("trace_id", "span_id", "timestamp", "latency_ms", "model", "prompt_version", "input_tokens", "output_tokens"),
    "retrieval": ("trace_id", "span_id", "timestamp", "latency_ms", "query", "source_ids"),
    "tool_call": ("trace_id", "span_id", "timestamp", "latency_ms", "tool", "outcome", "approval_id"),
}


def _cases(fail_ids=()):
    base = [("C-01", "high"), ("C-02", "high"), ("C-03", "critical"), ("C-04", "normal"), ("C-05", "normal"), ("C-06", "normal"), ("C-07", "normal"), ("C-08", "normal")]
    return [{"id": i, "severity": s, "passed": i not in fail_ids} for i, s in base]


CURRENT = {"release": "R-2026.09.1", "cases": _cases(("C-07",)), "metrics": {"quality": 0.86, "p95_latency_ms": 1650, "cost_per_task": 0.0072, "schema_failures": 0}}
CANDIDATES = {
    # Better on average, but breaks a protected (high-severity) case.
    "R-A": {"release": "R-A", "cases": _cases(("C-02",)), "metrics": {"quality": 0.90, "p95_latency_ms": 1500, "cost_per_task": 0.0070, "schema_failures": 0}},
    # Within tolerance: small quality noise, all protected cases pass.
    "R-B": {"release": "R-B", "cases": _cases(("C-06",)), "metrics": {"quality": 0.85, "p95_latency_ms": 1700, "cost_per_task": 0.0075, "schema_failures": 0}},
    # Latency SLO breach.
    "R-C": {"release": "R-C", "cases": _cases(), "metrics": {"quality": 0.89, "p95_latency_ms": 2600, "cost_per_task": 0.0080, "schema_failures": 0}},
    # Schema failures.
    "R-D": {"release": "R-D", "cases": _cases(), "metrics": {"quality": 0.88, "p95_latency_ms": 1600, "cost_per_task": 0.0071, "schema_failures": 3}},
}
EXPECTED = {"R-A": "block", "R-B": "promote", "R-C": "block", "R-D": "block"}

CANARIES = {
    "healthy": {"error_rate": 0.004, "p95_latency_ms": 1700, "protected_failures": 0, "cost_per_task": 0.0072},
    "error_spike": {"error_rate": 0.06, "p95_latency_ms": 1800, "protected_failures": 0, "cost_per_task": 0.0073},
    "protected_break": {"error_rate": 0.005, "p95_latency_ms": 1600, "protected_failures": 1, "cost_per_task": 0.0070},
}
CANARY_EXPECTED = {"healthy": False, "error_spike": True, "protected_break": True}


def validate(submission: Any, c: Checker) -> None:
    if not isinstance(submission, dict):
        raise ValueError("submit a dict with manifest, policy, gate, rollback, trace_schema and runbook")
    m = submission.get("manifest") or {}
    missing = [k for k in MANIFEST_KEYS if not m.get(k)]
    c.record("REL-01", not missing, f"Manifest missing: {', '.join(missing)}.", "Manifest versions code, prompts, tool schemas, model/config, data/eval and thresholds.")

    gate, policy = submission.get("gate"), submission.get("policy") or {}
    decisions = {}
    if callable(gate):
        with capture_output():
            for rid, cand in CANDIDATES.items():
                res, err = call_learner(gate, CURRENT, cand, policy)
                decisions[rid] = (res or {}) if isinstance(res, dict) and not err else {"decision": f"error: {err}"}
    ra = decisions.get("R-A", {})
    c.record("REL-02", ra.get("decision") == "block" and "C-02" in " ".join(map(str, ra.get("reasons", []))),
             f"A release that improves the average but fails protected case C-02 was {ra.get('decision', 'not evaluated')!r}; it must be blocked with a reason naming the case.",
             "Protected-case regressions block regardless of the aggregate.")

    rb = submission.get("rollback") or {}
    crit = [x for x in (rb.get("criteria") or []) if isinstance(x, dict) and all(str(x.get(k, "")).strip() for k in ("metric", "threshold", "window"))]
    fn = rb.get("should_rollback")
    wrong = []
    if callable(fn):
        for name, metrics in CANARIES.items():
            out, err = call_learner(fn, dict(metrics))
            if err or bool(out) != CANARY_EXPECTED[name]:
                wrong.append(name)
    else:
        wrong.append("no should_rollback function")
    runbook = submission.get("runbook") or {}
    rb_ok = bool(runbook.get("owner")) and len(runbook.get("rollback_steps") or []) >= 2 and bool(runbook.get("kill_switch"))
    c.record("REL-03", len(crit) >= 2 and not wrong and rb_ok,
             f"Need 2+ rollback criteria (metric, threshold, window), a should_rollback that decides the canaries correctly (wrong: {', '.join(wrong) or 'none'}), and a runbook with owner, rollback_steps and kill_switch.",
             "Rollback criteria are explicit, executable and backed by a runbook.")

    ts = (submission.get("trace_schema") or {}).get("events") or {}
    gaps = [f"{ev}.{f}" for ev, fields in TRACE_EVENTS.items() for f in fields if f not in (ts.get(ev) or {}).get("required", [])]
    c.record("REL-04", not gaps, f"Trace schema missing required fields: {', '.join(gaps[:8])}{'...' if len(gaps) > 8 else ''}.", "Model, retrieval and tool events are fully traceable.")

    slo = policy.get("slo") or {}
    bad = [k for k in ("p95_latency_ms", "cost_per_task") if not isinstance((slo.get(k) or {}).get("max"), (int, float)) or (slo.get(k) or {}).get("requirement") not in NFR_REQUIREMENTS]
    c.record("REL-05", not bad and decisions.get("R-C", {}).get("decision") == "block",
             f"SLOs need a numeric max and a requirement id from NFR_REQUIREMENTS (problems: {', '.join(bad) or 'none'}), and the gate must block the latency breach (R-C).",
             "Latency and cost SLOs trace to requirements and are enforced.")

    mismatch = [f"{rid}: {decisions.get(rid, {}).get('decision')!r} (expected {exp})" for rid, exp in EXPECTED.items() if decisions.get(rid, {}).get("decision") != exp]
    c.record("REL-06", not mismatch, f"Release simulation mismatches: {'; '.join(mismatch)}.", "All four candidates handled correctly.")
    c.evidence["decisions"] = {k: v.get("decision") for k, v in decisions.items()}


def naive_gate(current: Dict[str, Any], candidate: Dict[str, Any], policy: Dict[str, Any]) -> Dict[str, Any]:
    """Guided-lab starting point: promote whenever average quality does not drop."""
    ok = candidate["metrics"]["quality"] >= current["metrics"]["quality"]
    return {"decision": "promote" if ok else "block", "reasons": [] if ok else ["quality dropped"]}


def probes(submission: Any) -> List[Dict[str, Any]]:
    gate = submission.get("gate") if isinstance(submission, dict) else None
    if not callable(gate):
        return []
    policy = submission.get("policy") or {}
    critical_fail = {**CANDIDATES["R-B"], "cases": _cases(("C-03",))}
    res, err = call_learner(gate, CURRENT, critical_fail, policy)
    cost_breach = {**CANDIDATES["R-B"], "metrics": {**CANDIDATES["R-B"]["metrics"], "cost_per_task": 0.02}}
    res2, err2 = call_learner(gate, CURRENT, cost_breach, policy)
    return [
        {"id": "P1", "description": "A failing critical-severity case blocks", "ok": isinstance(res, dict) and res.get("decision") == "block"},
        {"id": "P2", "description": "A cost SLO breach blocks", "ok": isinstance(res2, dict) and res2.get("decision") == "block"},
    ]


register(LAB, REQUIREMENTS, validate, probes)
