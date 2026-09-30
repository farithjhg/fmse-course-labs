"""Lab 09 - Context Budget Optimizer (Module 9, Context Engineering, Memory, and Caching).

Guided: observe degradation from noisy context, then implement a context selector/compactor.
Challenge: refactor a long-running agent trace to preserve decisions and tool state while reducing
context by >=40% with no regression on a verification set.
Public validator requirements (course spec, Module 09):
  CTX-01 Required facts preserved              (verification set: no quality regression)
  CTX-02 Stale/irrelevant context removed
  CTX-03 Stable vs dynamic context separated
  CTX-04 Context budget respected              [critical] (gate: reduction >= 40% and within budget)
  CTX-05 Memory/state ownership documented
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List

from ..core import Checker, call_learner, check_public, register
from ..i18n import add_catalog, t as _t
from ..model import approx_tokens

LAB = "lab-09"
BUDGET_TOKENS = 450
MIN_REDUCTION = 0.40

REQUIREMENTS = {
    "CTX-01": ("Required facts preserved", "correctness", False,
               "Compaction must keep decisions, constraints, open questions and tool-state handles verbatim enough to act on. Check against the verification set."),
    "CTX-02": ("Stale/irrelevant context removed", "cost", False,
               "Superseded tool results and social chatter cost tokens and can mislead. Select what is still true and useful."),
    "CTX-03": ("Stable vs dynamic context separated", "cost", False,
               "Stable instructions and tool definitions belong in a fixed prefix; everything that changes goes after it (this is also what makes prompt caching work)."),
    "CTX-04": ("Context budget respected", "cost", True,
               "Measure the compacted context. It must fit the budget and be at least 40% smaller than the raw trace."),
    "CTX-05": ("Memory/state ownership documented", "operations", False,
               "For each kind of state, say who owns it, where it lives, how long it is kept and how it is deleted. Secrets and guesses are never durable memory."),
}

MEMORY_TYPES = ("conversation_history", "working_state", "durable_memory", "retrieved_evidence", "application_state")

SYSTEM = "SYSTEM: You are the checkout incident assistant. Propose actions; humans approve every change."
TOOLS = "TOOLS: get_metrics(service, window) -> metrics; get_deploys(service) -> deploy list; page_oncall(team) -> page id"

# The verification set: fact id -> substring that must survive compaction.
FACTS = {
    "DEC-01": "declared SEV-2",
    "DEC-02": "froze deploys to checkout-api",
    "DEC-03": "roll back checkout-api to v2.14.1",
    "CON-01": "no customer data in the status page",
    "CON-02": "rollback needs ops lead approval",
    "Q-01": "is the payment-gateway timeout related",
    "Q-02": "why did canary not catch v2.15.0",
    "HANDLE-01": "page id PG-88213",
    "HANDLE-02": "rollback job RB-4471 status pending",
}


def build_trace() -> List[Dict[str, Any]]:
    """A deterministic 70-event incident thread with decisions, noise and superseded tool results."""
    t: List[Dict[str, Any]] = [
        {"id": "E000", "kind": "system", "text": SYSTEM},
        {"id": "E001", "kind": "tools", "text": TOOLS},
    ]
    chatter = ["thanks!", "on it", "joining the bridge now", "+1", "coffee break in 5?", "lol same", "brb", "ok"]
    n = 2
    for minute in range(10, 44):
        t.append({"id": f"E{n:03d}", "kind": "tool_result", "text": f"metrics checkout-api 10:{minute:02d} error_rate={0.5 + (minute % 7) * 0.9:.1f}% p95=1{minute % 9}00ms (SNAPSHOT-{minute})",
                  "superseded": minute < 43})
        n += 1
        if minute % 3 == 0:
            t.append({"id": f"E{n:03d}", "kind": "chatter", "text": f"{chatter[minute % len(chatter)]} (CHAT-{minute})"})
            n += 1
    events = [
        ("decision", "DEC-01: declared SEV-2 for checkout errors at 10:14 (IC: A. Moreau)"),
        ("constraint", "CON-01: no customer data in the status page updates (legal)"),
        ("decision", "DEC-02: froze deploys to checkout-api until the incident closes"),
        ("tool_result", "HANDLE-01: paged payments on-call, page id PG-88213"),
        ("question", "Q-01: is the payment-gateway timeout related to the error spike?"),
        ("constraint", "CON-02: rollback needs ops lead approval before execution"),
        ("decision", "DEC-03: roll back checkout-api to v2.14.1, approved by ops lead M. Rossi at 10:42"),
        ("tool_result", "HANDLE-02: rollback job RB-4471 status pending"),
        ("question", "Q-02: why did canary not catch v2.15.0 before full rollout?"),
    ]
    for i, (kind, text) in enumerate(events):
        pos = 6 + i * 6
        t.insert(pos, {"id": f"F{i:02d}", "kind": kind, "text": text})
    return t


def trace_text(trace: List[Dict[str, Any]]) -> str:
    return "\n".join(e["text"] for e in trace)


def validate(submission: Any, c: Checker) -> None:
    if not isinstance(submission, dict):
        raise ValueError("submit a dict with 'compact' and 'memory_policy'")
    trace = build_trace()
    raw_tokens = approx_tokens(trace_text(trace))
    fn = submission.get("compact")
    res, err = call_learner(fn, copy.deepcopy(trace), BUDGET_TOKENS) if callable(fn) else (None, _t("no 'compact' function"))
    res = res if isinstance(res, dict) else {}
    stable, dynamic = str(res.get("stable") or ""), str(res.get("dynamic") or "")
    full = stable + "\n" + dynamic
    lost = [f for f, s in FACTS.items() if f not in full or s.lower() not in full.lower()]
    c.record("CTX-01", not err and not lost, (f"{err}." if err else _t('Facts lost in compaction: {v}.', v=', '.join(lost))), _t('All {n_FACTS} verification facts preserved.', n_FACTS=len(FACTS)))

    stale_ids = [e["text"].split("(")[-1].rstrip(")") for e in trace if e.get("superseded")]
    chat_ids = [e["text"].split("(")[-1].rstrip(")") for e in trace if e["kind"] == "chatter"]
    kept_stale = [s for s in stale_ids if s in full]
    kept_chat = [s for s in chat_ids if s in full]
    latest_kept = "SNAPSHOT-43" in full
    c.record("CTX-02", not err and not kept_stale and not kept_chat and latest_kept,
             _t('Kept {n_kept_stale} superseded snapshot(s) and {n_kept_chat} chatter line(s)', n_kept_stale=len(kept_stale), n_kept_chat=len(kept_chat)) + ("" if latest_kept else _t('; the latest metrics snapshot was dropped')) + ".",
             _t('Only the latest snapshot survives; chatter removed.'))

    separated = SYSTEM in stable and TOOLS in stable and SYSTEM not in dynamic and TOOLS not in dynamic and not any(f in stable for f in FACTS)
    c.record("CTX-03", not err and separated, _t('The stable prefix must hold the system instructions and tool definitions verbatim, and nothing that changes during the incident.'),
             _t('Stable prefix and dynamic context are separated.'))

    tokens = approx_tokens(full)
    reduction = 1 - tokens / raw_tokens
    c.record("CTX-04", not err and tokens <= BUDGET_TOKENS and reduction >= MIN_REDUCTION,
             _t('Compacted context is {tokens} tokens ({reduction:.0%} smaller than {raw_tokens}); needs <= {BUDGET_TOKENS} and >= {MIN_REDUCTION:.0%} reduction.', tokens=tokens, reduction=reduction, raw_tokens=raw_tokens, BUDGET_TOKENS=BUDGET_TOKENS, MIN_REDUCTION=MIN_REDUCTION),
             _t('{tokens} tokens, {reduction:.0%} reduction.', tokens=tokens, reduction=reduction))
    c.evidence.update({"raw_tokens": raw_tokens, "compacted_tokens": tokens, "reduction": round(reduction, 3)})

    policy = submission.get("memory_policy") or {}
    problems = []
    for mt in MEMORY_TYPES:
        entry = policy.get(mt) if isinstance(policy, dict) else None
        if not isinstance(entry, dict) or not all(str(entry.get(k, "")).strip() for k in ("owner", "retention", "deletion")):
            problems.append(mt)
    secret_ok = isinstance(policy, dict) and any(re.search(r"secret|credencial", str(v).lower()) for v in policy.values())
    if not secret_ok:
        problems.append(_t('no rule excluding secrets from memory'))
    c.record("CTX-05", not problems, _t('Memory policy incomplete (owner, retention, deletion) for: {v}.', v=', '.join(problems)), _t('Ownership, retention and deletion documented for every state type.'))


def naive_context(trace: List[Dict[str, Any]]) -> str:
    """Guided-lab baseline: replay the whole transcript."""
    return trace_text(trace)


def probes(submission: Any) -> List[Dict[str, Any]]:
    fn = submission.get("compact") if isinstance(submission, dict) else None
    if not callable(fn):
        return []
    out = []
    trace = build_trace() + [{"id": "E999", "kind": "decision", "text": "DEC-04: open a postmortem ticket PM-311"}]
    res, _ = call_learner(fn, trace, BUDGET_TOKENS)
    out.append({"id": "P1", "description": _t('A decision added late in the thread survives compaction'), "ok": isinstance(res, dict) and "PM-311" in str(res.get("dynamic", "")) + str(res.get("stable", ""))})
    trace2 = build_trace() + [{"id": "E998", "kind": "chatter", "text": "my api key is " + "sk-" + "fmse-canary-deadbeefdeadbeefdead" + ", can someone check?"}]
    res, _ = call_learner(fn, trace2, BUDGET_TOKENS)
    out.append({"id": "P2", "description": _t('A credential pasted into chat never reaches the compacted context'), "ok": isinstance(res, dict) and "deadbeefdeadbeef" not in str(res)})
    res, _ = call_learner(fn, build_trace(), 200)
    out.append({"id": "P3", "description": _t('A tighter budget (200) is respected or the compactor says it cannot fit'), "ok": isinstance(res, dict) and (approx_tokens(str(res.get("stable", "")) + str(res.get("dynamic", ""))) <= 200 or bool(res.get("over_budget")))})
    return out


register(LAB, REQUIREMENTS, validate, probes)


add_catalog({
    "no 'compact' function": "no hay función 'compact'",
    "Facts lost in compaction: {v}.": "Hechos perdidos en la compactación: {v}.",
    "All {n_FACTS} verification facts preserved.": "Se conservan los {n_FACTS} hechos de verificación.",
    "Only the latest snapshot survives; chatter removed.": "Solo sobrevive la instantánea más reciente; el ruido de la conversación se elimina.",
    "The stable prefix must hold the system instructions and tool definitions verbatim, and nothing that changes during the incident.":
        "El prefijo estable debe contener, palabra por palabra, las instrucciones de sistema y las definiciones de herramientas, y nada que cambie durante el incidente.",
    "Stable prefix and dynamic context are separated.": "El prefijo estable y el contexto dinámico están separados.",
    "Compacted context is {tokens} tokens ({reduction:.0%} smaller than {raw_tokens}); needs <= {BUDGET_TOKENS} and >= {MIN_REDUCTION:.0%} reduction.":
        "El contexto compactado tiene {tokens} tokens ({reduction:.0%} menos que {raw_tokens}); debe quedar en <= {BUDGET_TOKENS} con una reducción >= {MIN_REDUCTION:.0%}.",
    "{tokens} tokens, {reduction:.0%} reduction.": "{tokens} tokens, {reduction:.0%} de reducción.",
    "Memory policy incomplete (owner, retention, deletion) for: {v}.":
        "Política de memoria incompleta (responsable, retención, borrado) en: {v}.",
    "Ownership, retention and deletion documented for every state type.":
        "Responsable, retención y borrado documentados para cada tipo de estado.",
    "no rule excluding secrets from memory": "no hay ninguna regla que excluya los secretos de la memoria",
    "A decision added late in the thread survives compaction": "Una decisión añadida al final del hilo sobrevive a la compactación",
    "A credential pasted into chat never reaches the compacted context": "Una credencial pegada en el chat nunca llega al contexto compactado",
    "A tighter budget (200) is respected or the compactor says it cannot fit":
        "Un presupuesto más ajustado (200) se respeta, o el compactador avisa de que no cabe",
    "Kept {n_kept_stale} superseded snapshot(s) and {n_kept_chat} chatter line(s)":
        "Se conservaron {n_kept_stale} instantánea(s) obsoleta(s) y {n_kept_chat} línea(s) de ruido de conversación",
    "; the latest metrics snapshot was dropped": "; se descartó la instantánea de métricas más reciente",
})
