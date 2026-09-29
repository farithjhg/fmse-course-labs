"""Lab 04 - Model Profiler (Module 4, Foundation Model Mechanics and Inference Economics).

Guided: a provider-neutral wrapper captures latency, token counts, success metrics, and cost estimates.
Challenge: design and run a mini benchmark on 20 tasks; produce a recommendation conditioned on
requirements rather than a universal "best model".
Public validator requirements (course spec, Module 04):
  PRF-01 Benchmark contains >=20 samples
  PRF-02 At least 2 model/config variants compared
  PRF-03 Quality metric defined
  PRF-04 Latency and cost captured
  PRF-05 Conclusion cites measured evidence and limitations
  PRF-06 Benchmark reproducible (gate: re-running the benchmark reproduces the reported results)

The simulated models are teaching instruments with documented, deterministic behaviour. Their
numbers say nothing about any real model; the unit costs are hypothetical inputs you choose.
"""

from __future__ import annotations

import copy
import hashlib
import re
import statistics
from typing import Any, Dict, List

from ..core import Checker, check_public, register
from ..model import approx_tokens

LAB = "lab-04"

REQUIREMENTS = {
    "PRF-01": ("Benchmark contains >=20 samples", "completeness", False,
               "A handful of tasks cannot separate two configurations from noise. Use at least 20, drawn from the task pool."),
    "PRF-02": ("At least 2 model/config variants compared", "completeness", False,
               "A characterization compares alternatives. Configure at least two distinct variants (model, effort or prompt style)."),
    "PRF-03": ("Quality metric defined", "correctness", False,
               "State what 'quality' means for this scenario and how it is computed, before looking at the numbers."),
    "PRF-04": ("Latency and cost captured", "latency", False,
               "Every variant needs measured latency and cost next to quality - the trade-off is the point of the exercise."),
    "PRF-05": ("Conclusion cites measured evidence and limitations", "groundedness", False,
               "A recommendation is conditional: under which requirements does each variant win, which measured numbers show it, and what could make this benchmark misleading?"),
    "PRF-06": ("Benchmark reproducible", "reproducibility", False,
               "Report the numbers the profiler actually produced for the configuration you submitted; anyone re-running it must get the same results."),
}

TASK_TYPES = ("extraction", "classification", "arithmetic", "reasoning")

# Scenario requirements the recommendation must be conditioned on.
SCENARIO = {
    "name": "Support-ticket triage assistant",
    "requirements": {
        "PR-QUAL": "Triage quality (exact match) shall be at least 0.80 on the benchmark.",
        "PR-LAT": "Median end-to-end latency shall be at most 1500 ms.",
        "PR-COST": "Mean cost per task shall be at most 0.0020 (hypothetical currency units).",
    },
}

MODELS = {
    # base accuracy per task type; ms per output token; reasoning tokens multiplier
    "sim-fast": {"acc": {"extraction": 0.9, "classification": 0.85, "arithmetic": 0.6, "reasoning": 0.45}, "ms_out": 8.0, "think": 0.0, "base_ms": 120},
    "sim-reasoning": {"acc": {"extraction": 0.92, "classification": 0.9, "arithmetic": 0.95, "reasoning": 0.88}, "ms_out": 12.0, "think": 6.0, "base_ms": 400},
    "sim-small": {"acc": {"extraction": 0.8, "classification": 0.78, "arithmetic": 0.4, "reasoning": 0.3}, "ms_out": 4.0, "think": 0.0, "base_ms": 60},
}


def task_pool() -> List[Dict[str, Any]]:
    """30 deterministic benchmark tasks with expected answers."""
    tasks = []
    for i in range(30):
        t = TASK_TYPES[i % 4]
        long_context = i % 5 == 0
        prompt = f"[{t}] task {i}: " + ("background " * (600 if long_context else 40))
        tasks.append({"id": f"T{i:02d}", "type": t, "prompt": prompt, "expected": f"A{i % 7}", "long_context": long_context})
    return tasks


def _u(*parts: Any) -> float:
    h = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def run_variant(variant: Dict[str, Any], task: Dict[str, Any], unit_costs: Dict[str, float]) -> Dict[str, Any]:
    """Profile one task on one variant. Deterministic.

    variant: {"name", "model": sim-fast|sim-reasoning|sim-small, "effort": low|high, "prompt_style": objective|procedural}
    unit_costs: {model: cost per 1K tokens} - hypothetical numbers you choose; real prices change and are never hard-coded here.
    """
    m = MODELS[variant["model"]]
    acc = m["acc"][task["type"]]
    if variant.get("effort") == "high":
        acc = min(0.99, acc + (0.06 if m["think"] else 0.02))
    if variant.get("prompt_style") == "procedural":
        # Documented behaviour: procedural scaffolding helps the fast models and slightly over-constrains the reasoning model.
        acc = acc - 0.04 if m["think"] else min(0.99, acc + 0.05)
    correct = _u(variant["model"], variant.get("effort"), variant.get("prompt_style"), task["id"]) < acc
    tin = approx_tokens(task["prompt"]) + (120 if variant.get("prompt_style") == "procedural" else 40)
    tout = 30
    reasoning = int(tout * m["think"] * (2 if variant.get("effort") == "high" else 1))
    ttft = m["base_ms"] + tin * 0.08 + reasoning * m["ms_out"]
    latency = ttft + tout * m["ms_out"]
    cost = (tin + tout + reasoning) / 1000 * float(unit_costs.get(variant["model"], 0.0))
    return {"task_id": task["id"], "type": task["type"], "correct": bool(correct), "input_tokens": tin, "output_tokens": tout,
            "reasoning_tokens": reasoning, "ttft_ms": round(ttft, 1), "latency_ms": round(latency, 1), "cost": round(cost, 7)}


def profile(variant: Dict[str, Any], task_ids: List[str], unit_costs: Dict[str, float]) -> List[Dict[str, Any]]:
    pool = {t["id"]: t for t in task_pool()}
    return [run_variant(variant, pool[i], unit_costs) for i in task_ids]


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    return {
        "quality": round(sum(r["correct"] for r in rows) / len(rows), 4) if rows else 0.0,
        "p50_latency_ms": round(statistics.median(r["latency_ms"] for r in rows), 1) if rows else 0.0,
        "mean_cost": round(sum(r["cost"] for r in rows) / len(rows), 7) if rows else 0.0,
    }


def validate(submission: Any, c: Checker) -> None:
    if not isinstance(submission, dict):
        raise ValueError("submit a dict with benchmark, variants, unit_costs, results and conclusion")
    pool = {t["id"] for t in task_pool()}
    bench = submission.get("benchmark") or {}
    ids = list(bench.get("task_ids") or [])
    unknown = [i for i in ids if i not in pool]
    c.record("PRF-01", len(set(ids)) >= 20 and not unknown,
             f"The benchmark has {len(set(ids))} distinct known tasks" + (f" and unknown ids {unknown[:5]}" if unknown else "") + "; at least 20 are required.",
             f"{len(set(ids))} tasks.")

    variants = [v for v in (submission.get("variants") or []) if isinstance(v, dict)]
    valid = [v for v in variants if v.get("name") and v.get("model") in MODELS]
    sigs = {(v.get("model"), v.get("effort"), v.get("prompt_style")) for v in valid}
    c.record("PRF-02", len(valid) >= 2 and len(sigs) >= 2, f"Found {len(sigs)} distinct valid variant configuration(s); at least 2 are required (models: {', '.join(MODELS)}).",
             f"{len(sigs)} variants compared.")

    metric = bench.get("quality_metric") or {}
    c.record("PRF-03", isinstance(metric, dict) and bool(metric.get("name")) and len(str(metric.get("definition", "")).split()) >= 8,
             "The quality metric needs a name and a definition of at least a sentence.", "Quality metric defined.")

    results = submission.get("results") or {}
    missing = [v["name"] for v in valid if not all(isinstance((results.get(v["name"]) or {}).get(k), (int, float)) for k in ("quality", "p50_latency_ms", "mean_cost"))]
    c.record("PRF-04", bool(valid) and not missing, f"Missing quality/latency/cost numbers for: {', '.join(missing) or 'all variants'}.", "Latency and cost captured for every variant.")

    concl = submission.get("conclusion") or {}
    text = " ".join(str(concl.get(k, "")) for k in ("recommendation", "evidence"))
    problems = []
    if not re.search(r"\d", text):
        problems.append("no measured numbers cited")
    if sum(1 for v in valid if v["name"] in text) < 2:
        problems.append("fewer than two variants referenced by name")
    if not any(rid in text for rid in SCENARIO["requirements"]):
        problems.append(f"recommendation not tied to a scenario requirement ({', '.join(SCENARIO['requirements'])})")
    if len(str(concl.get("limitations", "")).split()) < 12:
        problems.append("limitations missing or too short")
    if re.search(r"\b(best model|always better|universally)\b", text, re.I):
        problems.append("claims a universal winner")
    c.record("PRF-05", not problems, "Conclusion: " + "; ".join(problems) + ".", "Conclusion is conditional, evidenced and states limitations.")

    mismatch = []
    costs = submission.get("unit_costs") or {}
    if not ids or not valid:
        mismatch.append("nothing to re-run")
    for v in valid:
        try:
            fresh = summarize(profile(v, ids, costs))
        except KeyError:
            mismatch.append(v["name"])
            continue
        rep = results.get(v["name"]) or {}
        for k, tol in (("quality", 1e-6), ("p50_latency_ms", 0.51), ("mean_cost", 1e-6)):
            if not isinstance(rep.get(k), (int, float)) or abs(rep[k] - fresh[k]) > tol + abs(fresh[k]) * 1e-6:
                mismatch.append(f"{v['name']}.{k}")
    c.record("PRF-06", not mismatch, f"Re-running the submitted configuration does not reproduce: {', '.join(mismatch[:6])}.", "Re-running the benchmark reproduces every reported number.")
    c.evidence.update({"tasks": len(ids), "variants": len(valid)})


def probes(submission: Any) -> List[Dict[str, Any]]:
    if not isinstance(submission, dict):
        return []
    out = []

    def run(pid, description, target, mutate):
        s = copy.deepcopy({k: v for k, v in submission.items()})
        try:
            mutate(s)
        except Exception:  # noqa: BLE001
            return
        res = check_public(LAB, s)
        out.append({"id": pid, "description": f"{description} is caught by {target}", "ok": any(ch.id == target and ch.status == "fail" for ch in res.checks)})

    def fudge(s):
        name = s["variants"][0]["name"]
        s["results"][name]["quality"] = min(1.0, s["results"][name]["quality"] + 0.05)

    run("P1", "A reported quality nudged up by 5 points", "PRF-06", fudge)
    run("P2", "A 10-task benchmark", "PRF-01", lambda s: s["benchmark"].__setitem__("task_ids", s["benchmark"]["task_ids"][:10]))
    run("P3", "A conclusion that names a universal best model", "PRF-05", lambda s: s["conclusion"].__setitem__("recommendation", s["conclusion"].get("recommendation", "") + " It is the best model."))
    return out


register(LAB, REQUIREMENTS, validate, probes)
