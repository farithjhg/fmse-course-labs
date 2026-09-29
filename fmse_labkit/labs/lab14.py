"""Lab 14 - Optimize a Measured Pipeline (Module 14, Optimization Engineering with DSPy and Multi-Objective Search).

Guided: establish a baseline, split data, run a lightweight optimizer, and compare metrics.
Challenge: improve held-out quality by a defined margin without violating cost/latency or
high-severity safety constraints.
Public validator requirements (course spec, Module 14):
  OPT-01 Train/dev/test split present
  OPT-02 Baseline recorded
  OPT-03 Optimization log retained
  OPT-04 Held-out test not used for tuning                                [critical]
  OPT-05 Pareto comparison produced
  OPT-06 Held-out improvement >= 0.05 with no protected-case regression  [critical]

`SimProgram` stands in for a compiled prompt program (instruction + few-shot demos). Its behaviour
is deterministic and documented so the optimisation *discipline* can be graded: candidate
instructions differ in which labels they handle, demos help the label they show, and every demo
costs tokens. The same loop maps directly onto DSPy optimizers (MIPROv2, GEPA) - see references R10, R11.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from ..core import Checker, register

LAB = "lab-14"
LABELS = ("billing", "technical", "account", "security_incident", "other")
PROTECTED = "security_incident"
MAX_COST = 420  # tokens per call
MARGIN = 0.05

REQUIREMENTS = {
    "OPT-01": ("Train/dev/test split present", "reproducibility", False,
               "Split once, before optimising: disjoint train (demos), dev (selection) and test (final, untouched) sets, each large enough to mean something."),
    "OPT-02": ("Baseline recorded", "reproducibility", False,
               "Record the unoptimised program and its measured scores first; improvement only means something against it."),
    "OPT-03": ("Optimization log retained", "reproducibility", False,
               "Keep every trial: the candidate program, the split it was scored on, its score and its cost."),
    "OPT-04": ("Held-out test not used for tuning", "correctness", True,
               "Selection and demos must come from train/dev only. Touching the test set while tuning makes the final number meaningless."),
    "OPT-05": ("Pareto comparison produced", "cost", False,
               "Compare candidates on quality AND cost; mark which are dominated, and choose from the non-dominated set under the constraints."),
    "OPT-06": ("Held-out improvement with no protected-case regression", "robustness", True,
               "Optimise for the scalar only if protected rows (security incidents) do not get worse and cost stays within the limit."),
}

INSTRUCTIONS = {
    "I0": {"text": "Classify the ticket.", "acc": {"billing": 0.75, "technical": 0.75, "account": 0.55, "security_incident": 0.6, "other": 0.5}, "tokens": 60},
    "I1": {"text": "Classify the support ticket into billing, technical, account, security_incident or other.", "acc": {"billing": 0.8, "technical": 0.8, "account": 0.7, "security_incident": 0.65, "other": 0.6}, "tokens": 110},
    "I2": {"text": "Classify the ticket. Anything mentioning unauthorised access, phishing or leaked credentials is security_incident.",
           "acc": {"billing": 0.72, "technical": 0.72, "account": 0.62, "security_incident": 0.92, "other": 0.55}, "tokens": 140},
    "I3": {"text": "You are a triage expert. Think about the customer's goal, then label: billing, technical, account, security_incident, other. Security first.",
           "acc": {"billing": 0.82, "technical": 0.8, "account": 0.75, "security_incident": 0.88, "other": 0.62}, "tokens": 190},
    # A candidate that games the scalar: great on common labels, drops security incidents.
    "I4": {"text": "Classify quickly; when unsure answer technical.", "acc": {"billing": 0.9, "technical": 0.95, "account": 0.8, "security_incident": 0.3, "other": 0.7}, "tokens": 70},
}
DEMO_TOKENS = 45
DEMO_BOOST = 0.07


def dataset() -> List[Dict[str, Any]]:
    """90 labelled tickets (synthetic). security_incident rows are protected (high severity)."""
    counts = {"billing": 22, "technical": 24, "account": 16, "security_incident": 14, "other": 14}
    rows, i = [], 0
    for label, n in counts.items():
        for k in range(n):
            rows.append({"id": f"X{i:03d}", "label": label, "severity": "high" if label == PROTECTED else "normal", "text": f"({label} ticket #{k})"})
            i += 1
    return rows


def _u(*parts: Any) -> float:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


class SimProgram:
    def __init__(self, instruction: str, demos: Optional[List[str]] = None):
        if instruction not in INSTRUCTIONS:
            raise ValueError(f"unknown instruction {instruction}")
        self.instruction = instruction
        self.demos = list(demos or [])
        self._labels = {r["id"]: r["label"] for r in dataset()}

    @property
    def cost(self) -> int:
        return INSTRUCTIONS[self.instruction]["tokens"] + DEMO_TOKENS * len(self.demos)

    def predict(self, row: Dict[str, Any]) -> str:
        acc = INSTRUCTIONS[self.instruction]["acc"][row["label"]]
        shown = sum(1 for d in self.demos if self._labels.get(d) == row["label"])
        acc = min(0.98, acc + DEMO_BOOST * min(shown, 2))
        # Each row has a fixed difficulty; a program answers it correctly when its accuracy for that
        # label exceeds the difficulty. Better programs therefore fix a superset of rows (no luck involved).
        if _u("difficulty", row["id"]) < acc:
            return row["label"]
        return "technical" if row["label"] != "technical" else "other"

    def to_dict(self) -> Dict[str, Any]:
        return {"instruction": self.instruction, "demos": list(self.demos)}


def score(program: SimProgram, ids: List[str], label: Optional[str] = None) -> float:
    rows = [r for r in dataset() if r["id"] in set(ids) and (label is None or r["label"] == label)]
    return round(sum(program.predict(r) == r["label"] for r in rows) / len(rows), 4) if rows else 0.0


def feedback(program: SimProgram, ids: List[str]) -> List[str]:
    """GEPA-style textual feedback on failures: which labels are being missed, and as what."""
    misses: Dict[str, int] = {}
    for r in dataset():
        if r["id"] in set(ids):
            p = program.predict(r)
            if p != r["label"]:
                misses[f"{r['label']} -> {p}"] = misses.get(f"{r['label']} -> {p}", 0) + 1
    return [f"{k}: {v} miss(es)" for k, v in sorted(misses.items(), key=lambda x: -x[1])]


def _program(d: Any) -> Optional[SimProgram]:
    try:
        return SimProgram(d["instruction"], d.get("demos") or [])
    except Exception:  # noqa: BLE001
        return None


def validate(submission: Any, c: Checker) -> None:
    if not isinstance(submission, dict):
        raise ValueError("submit a dict with splits, baseline, optimization_log, pareto and selected")
    all_ids = {r["id"] for r in dataset()}
    sp = submission.get("splits") or {}
    train, dev, test = (set(sp.get(k) or []) for k in ("train", "dev", "test"))
    disjoint = not (train & dev or train & test or dev & test)
    known = (train | dev | test) <= all_ids
    covered = len(train | dev | test) >= 0.9 * len(all_ids)
    c.record("OPT-01", disjoint and known and covered and len(test) >= 15 and len(dev) >= 10 and len(train) >= 10,
             f"Splits must be disjoint, use known ids, cover >= 90% of the data, with test >= 15 and dev/train >= 10 (got train {len(train)}, dev {len(dev)}, test {len(test)}{', overlapping' if not disjoint else ''}).",
             f"train {len(train)} / dev {len(dev)} / test {len(test)}, disjoint.")

    base = submission.get("baseline") or {}
    bprog = _program(base.get("program") or {})
    ok = bprog is not None and test and abs(float(base.get("test_score", -1)) - score(bprog, list(test))) < 1e-6
    c.record("OPT-02", bool(ok), "Record the baseline program and the test score it actually achieves (recomputed value differs or is missing).", "Baseline recorded and reproducible.")

    log = [e for e in (submission.get("optimization_log") or []) if isinstance(e, dict)]
    complete = [e for e in log if _program(e.get("program") or {}) and e.get("split") in ("train", "dev", "test") and isinstance(e.get("score"), (int, float)) and isinstance(e.get("cost"), (int, float))]
    c.record("OPT-03", len(complete) >= 5 and len(complete) == len(log), f"{len(complete)} of {len(log)} log entries are complete (program, split, score, cost); at least 5 trials are required.",
             f"{len(log)} trials logged.")

    sel = submission.get("selected") or {}
    sprog = _program(sel.get("program") or {})
    leaks = [e.get("trial", "?") for e in log if e.get("split") == "test" or set((e.get("program") or {}).get("demos") or []) - train]
    if sprog is None or set(sprog.demos) - train:
        leaks.append("selected program uses non-train demos")
    c.record("OPT-04", not leaks and sprog is not None, f"The test set (or non-train demos) was used during tuning: {', '.join(map(str, leaks[:5]))}.", "Only train/dev were used for tuning.")

    pareto = [p for p in (submission.get("pareto") or []) if isinstance(p, dict) and _program(p.get("program") or {})]
    pts = [(_program(p["program"]), p) for p in pareto]
    wrong = []
    measured = [(score(pr, list(dev)), pr.cost) for pr, _ in pts]
    for i, (pr, p) in enumerate(pts):
        q, cost = measured[i]
        dom = any((q2 >= q and c2 <= cost) and (q2 > q or c2 < cost) for j, (q2, c2) in enumerate(measured) if j != i)
        if bool(p.get("dominated")) != dom or abs(float(p.get("quality", -1)) - q) > 1e-6 or int(p.get("cost", -1)) != cost:
            wrong.append(f"{pr.instruction}+{len(pr.demos)}demos")
    # The selection must be on the frontier of the *eligible* candidates (within cost, no protected regression on dev).
    bprot = score(bprog, list(dev), PROTECTED) if bprog else 0.0
    eligible = [i for i, (pr, _) in enumerate(pts) if pr.cost <= MAX_COST and score(pr, list(dev), PROTECTED) >= bprot]
    sel_idx = next((i for i, (pr, _) in enumerate(pts) if sprog is not None and pr.to_dict() == sprog.to_dict()), None)
    sel_listed = sel_idx in eligible and not any(
        (measured[j][0] >= measured[sel_idx][0] and measured[j][1] <= measured[sel_idx][1]) and (measured[j][0] > measured[sel_idx][0] or measured[j][1] < measured[sel_idx][1])
        for j in eligible if j != sel_idx)
    c.record("OPT-05", len(pts) >= 3 and not wrong and sel_listed,
             f"Pareto set needs 3+ candidates with dev quality, cost and correct 'dominated' flags, and the selected program must be listed and non-dominated among the eligible candidates (within cost, no protected regression) (flag mismatches: {', '.join(wrong[:4]) or 'none'}).",
             f"{len(pts)} candidates compared; selection is on the frontier.")

    if sprog is None or bprog is None or not test:
        c.fail("OPT-06", "Cannot evaluate: missing selected or baseline program, or test split.")
    else:
        t_sel, t_base = score(sprog, list(test)), score(bprog, list(test))
        p_sel, p_base = score(sprog, list(test), PROTECTED), score(bprog, list(test), PROTECTED)
        problems = []
        if t_sel < t_base + MARGIN:
            problems.append(f"held-out quality {t_sel:.2f} vs baseline {t_base:.2f} (needs +{MARGIN:.2f})")
        if p_sel < p_base:
            problems.append(f"protected {PROTECTED} accuracy fell from {p_base:.2f} to {p_sel:.2f}")
        if sprog.cost > MAX_COST:
            problems.append(f"cost {sprog.cost} tokens exceeds {MAX_COST}")
        c.record("OPT-06", not problems, "; ".join(problems) + ".", f"Held-out {t_base:.2f} -> {t_sel:.2f}; protected {p_base:.2f} -> {p_sel:.2f}; cost {sprog.cost}.")
        c.evidence.update({"test_baseline": t_base, "test_selected": t_sel, "protected_baseline": p_base, "protected_selected": p_sel, "cost": sprog.cost})


def probes(submission: Any) -> List[Dict[str, Any]]:
    if not isinstance(submission, dict):
        return []
    sp = submission.get("splits") or {}
    gaming = SimProgram("I4")
    test = list(sp.get("test") or [])
    return [
        {"id": "P1", "description": "The scalar-gaming candidate (I4) would be rejected by the protected-case rule",
         "ok": bool(test) and score(gaming, test, PROTECTED) < score(SimProgram("I0"), test, PROTECTED)},
        {"id": "P2", "description": "No trial in the log was scored on the test split", "ok": all(e.get("split") != "test" for e in submission.get("optimization_log") or [])},
    ]


register(LAB, REQUIREMENTS, validate, probes)
