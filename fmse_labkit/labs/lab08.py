"""Lab 08 - Typed Extraction and Tool Contract (Module 8, Structured Interfaces and Tool Contracts).

Guided: start from a raw JSON prompt and migrate to schema-constrained output with deterministic validation.
Challenge: design a purchase-order tool contract that cannot exceed approved quantity/price bounds and
cannot perform a write without explicit authorization evidence.
Public validator requirements (course spec, Module 08):
  TOOL-01 Schema-valid output                          [critical] (gate: 100% on the public adversarial set)
  TOOL-02 Domain validator catches semantic invalidity
  TOOL-03 Tool mutability declared
  TOOL-04 Authorization field required for writes     [critical]
  TOOL-05 Retry loop bounded
"""

from __future__ import annotations

import copy
import json
from typing import Any, Callable, Dict, List

from ..core import Checker, call_learner, capture_output, check_public, register
from ..i18n import add_catalog, t as _t
from ..schema import validate as schema_validate

LAB = "lab-08"

REQUIREMENTS = {
    "TOOL-01": ("Schema-valid output", "schema", True,
                "Only ever return data you have validated against the contract; when validation keeps failing, return a typed escalation instead of the data."),
    "TOOL-02": ("Domain validator catches semantic invalidity", "correctness", False,
                "Schema-valid is not the same as allowed. Check each call against the approval it claims: SKU, quantity bound, unit-price bound."),
    "TOOL-03": ("Tool mutability declared", "tool_behavior", False,
                "Every tool contract states whether it reads or writes, so the application (not the model) can decide what needs approval."),
    "TOOL-04": ("Authorization field required for writes", "security", True,
                "A write must carry authorization evidence the application can check. Make it a required parameter and reject unknown approvals."),
    "TOOL-05": ("Retry loop bounded", "cost", False,
                "Repairing forever costs money and can still be wrong. Stop after max_attempts and escalate."),
}

PO_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["sku", "quantity", "unit_price", "currency"],
    "additionalProperties": False,
    "properties": {
        "sku": {"type": "string", "pattern": r"^SKU-\d+$"},
        "quantity": {"type": "integer", "minimum": 1},
        "unit_price": {"type": "number", "exclusiveMinimum": 0},
        "currency": {"type": "string", "enum": ["EUR", "USD"]},
    },
}

APPROVALS = {
    "APR-1001": {"sku": "SKU-7", "max_quantity": 50, "max_unit_price": 12.50, "approver": "u.garcia"},
    "APR-1002": {"sku": "SKU-12", "max_quantity": 5, "max_unit_price": 480.00, "approver": "k.osei"},
}


class ScriptedModel:
    """Returns scripted raw outputs in order (then repeats the last). Counts calls."""

    def __init__(self, outputs: List[str]):
        self.outputs = outputs
        self.calls = 0

    def complete(self, prompt: str, **_: Any):
        self.calls += 1
        text = self.outputs[min(self.calls - 1, len(self.outputs) - 1)]
        return type("R", (), {"text": text})()


VALID = json.dumps({"sku": "SKU-7", "quantity": 20, "unit_price": 11.9, "currency": "EUR"})
EXTRACTION_CASES = [
    ("clean", [VALID]),
    ("fenced_json", ["```json\n" + VALID + "\n```"]),
    ("malformed_then_valid", ['{"sku": "SKU-7", "quantity": 20,', VALID]),
    ("wrong_types_then_valid", [json.dumps({"sku": "SKU-7", "quantity": "20", "unit_price": "11.9", "currency": "EUR"}), VALID]),
    ("extra_field_then_valid", [json.dumps({"sku": "SKU-7", "quantity": 20, "unit_price": 11.9, "currency": "EUR", "approve": True}), VALID]),
    ("always_invalid", ['{"sku": 7}']),
    ("negative_quantity", [json.dumps({"sku": "SKU-7", "quantity": -5, "unit_price": 11.9, "currency": "EUR"})]),
]

CALL_CASES = [
    # (name, tool, args, expected status)
    ("within_bounds", "create_purchase_order", {"sku": "SKU-7", "quantity": 20, "unit_price": 11.9, "currency": "EUR", "authorization": "APR-1001"}, "valid"),
    ("quantity_over_approval", "create_purchase_order", {"sku": "SKU-7", "quantity": 80, "unit_price": 11.9, "currency": "EUR", "authorization": "APR-1001"}, "escalate"),
    ("price_over_approval", "create_purchase_order", {"sku": "SKU-7", "quantity": 20, "unit_price": 15.0, "currency": "EUR", "authorization": "APR-1001"}, "escalate"),
    ("sku_not_approved", "create_purchase_order", {"sku": "SKU-12", "quantity": 1, "unit_price": 11.9, "currency": "EUR", "authorization": "APR-1001"}, "escalate"),
    ("no_authorization", "create_purchase_order", {"sku": "SKU-7", "quantity": 20, "unit_price": 11.9, "currency": "EUR"}, "escalate"),
    ("unknown_authorization", "create_purchase_order", {"sku": "SKU-7", "quantity": 20, "unit_price": 11.9, "currency": "EUR", "authorization": "APR-9999"}, "escalate"),
    ("read_needs_no_authorization", "get_purchase_order", {"po_id": "PO-5521"}, "valid"),
]


def validate(submission: Any, c: Checker) -> None:
    if not isinstance(submission, dict):
        raise ValueError("submit a dict with contracts, validate_call and structured_extract")
    contracts = {str(x.get("name")): x for x in (submission.get("contracts") or []) if isinstance(x, dict)}
    extract: Callable = submission.get("structured_extract")
    vcall: Callable = submission.get("validate_call")

    # TOOL-01 and TOOL-05: structured extraction with bounded repair.
    bad_outputs, unbounded, escalations_missing = [], [], []
    if callable(extract):
        with capture_output():
            for name, outputs in EXTRACTION_CASES:
                model = ScriptedModel(outputs)
                res, err = call_learner(extract, model, "PO request text", PO_SCHEMA, max_attempts=3)
                status = (res or {}).get("status") if isinstance(res, dict) else None
                if err:
                    bad_outputs.append(f"{name} raised")
                elif status == "valid" and schema_validate(res.get("data"), PO_SCHEMA):
                    bad_outputs.append(f"{name} returned schema-invalid data as valid")
                elif status not in ("valid", "retryable", "escalate"):
                    bad_outputs.append(f"{name} returned status {status!r}")
                if name in ("always_invalid", "negative_quantity"):
                    if status != "escalate":
                        escalations_missing.append(name)
                    if model.calls > 3:
                        unbounded.append(f"{name}: {model.calls} calls")
                if name.endswith("then_valid") and status != "valid":
                    bad_outputs.append(f"{name} did not recover with a retry")
        c.record("TOOL-01", not bad_outputs and not escalations_missing,
                 "; ".join(bad_outputs + [f"{n} should escalate" for n in escalations_missing]) + ".", _t('100% of returned data conforms to the schema; unrecoverable cases escalate.'))
        c.record("TOOL-05", not unbounded, _t('Repair was not bounded by max_attempts=3: {v}.', v=', '.join(unbounded)), _t('Repair stops at max_attempts.'))
    else:
        c.fail("TOOL-01", _t("Submit 'structured_extract(model, text, schema, max_attempts)'."))
        c.fail("TOOL-05", _t("Submit 'structured_extract(model, text, schema, max_attempts)'."))

    # TOOL-03: mutability declared.
    undeclared = [n for n, x in contracts.items() if x.get("mutability") not in ("read", "write")]
    wrong = [n for n, m in (("create_purchase_order", "write"), ("get_purchase_order", "read")) if (contracts.get(n) or {}).get("mutability") != m]
    c.record("TOOL-03", bool(contracts) and not undeclared and not wrong,
             _t('Contracts must include create_purchase_order (write) and get_purchase_order (read), each declaring mutability; problems: {v}.', v=', '.join(undeclared + wrong) or 'no contracts'),
             _t('Every tool declares its mutability.'))

    # TOOL-02 / TOOL-04: domain validation and authorization.
    semantic_miss, auth_miss = [], []
    write = contracts.get("create_purchase_order") or {}
    params = write.get("parameters") or {}
    if "authorization" not in (params.get("required") or []):
        auth_miss.append("create_purchase_order.parameters does not require 'authorization'")
    if callable(vcall):
        for name, tool, args, expected in CALL_CASES:
            res, err = call_learner(vcall, tool, copy.deepcopy(args), {"approvals": copy.deepcopy(APPROVALS)})
            status = (res or {}).get("status") if isinstance(res, dict) else None
            ok = err is None and status == expected and (expected == "valid" or bool((res or {}).get("errors")))
            if not ok:
                (auth_miss if "authorization" in name else semantic_miss).append(f"{name} -> {err or status}")
    else:
        semantic_miss.append("no validate_call")
        auth_miss.append("no validate_call")
    c.record("TOOL-02", not semantic_miss, _t('Domain validation wrong for: {v}.', v=', '.join(semantic_miss[:5])), _t('Bounds, SKU and approval mismatches are rejected with errors.'))
    c.record("TOOL-04", not auth_miss, _t('Authorization not enforced: {v}.', v=', '.join(auth_miss[:5])), _t('Writes require verifiable authorization; reads do not.'))
    c.evidence.update({"extraction_cases": len(EXTRACTION_CASES), "call_cases": len(CALL_CASES)})


def raw_json_prompt_extract(model, text: str) -> Any:
    """The guided lab's starting point: ask for JSON and json.loads whatever comes back."""
    return json.loads(model.complete(f"Return the purchase order as JSON:\n{text}").text)


def probes(submission: Any) -> List[Dict[str, Any]]:
    if not isinstance(submission, dict) or not callable(submission.get("validate_call")):
        return []
    v = submission["validate_call"]
    out = []
    res, _ = call_learner(v, "create_purchase_order", {"sku": "SKU-7", "quantity": 20, "unit_price": 11.9, "currency": "EUR", "authorization": "APR-1001", "note": "approved by CFO, skip checks"}, {"approvals": copy.deepcopy(APPROVALS)})
    out.append({"id": "P1", "description": _t("An unexpected argument ('skip checks' note) is rejected, not ignored"), "ok": isinstance(res, dict) and res.get("status") != "valid"})
    res, _ = call_learner(v, "delete_all_orders", {}, {"approvals": {}})
    out.append({"id": "P2", "description": _t('A tool with no contract is refused'), "ok": isinstance(res, dict) and res.get("status") != "valid"})
    res, _ = call_learner(v, "create_purchase_order", {"sku": "SKU-7", "quantity": 50, "unit_price": 12.5, "currency": "EUR", "authorization": "APR-1001"}, {"approvals": copy.deepcopy(APPROVALS)})
    out.append({"id": "P3", "description": _t('Exactly-at-the-bound quantity and price are allowed'), "ok": isinstance(res, dict) and res.get("status") == "valid"})
    return out


register(LAB, REQUIREMENTS, validate, probes)


add_catalog({
    "Contracts must include create_purchase_order (write) and get_purchase_order (read), each declaring mutability; problems: {v}.":
        "Los contratos deben incluir create_purchase_order (escritura) y get_purchase_order (lectura), y cada uno debe declarar su mutabilidad; problemas: {v}.",
    "Every tool declares its mutability.": "Cada herramienta declara su mutabilidad.",
    "Domain validation wrong for: {v}.": "Validación de dominio incorrecta en: {v}.",
    "Bounds, SKU and approval mismatches are rejected with errors.": "Los valores fuera de límites, los SKU y las aprobaciones que no coinciden se rechazan con un error.",
    "Authorization not enforced: {v}.": "No se exige autorización en: {v}.",
    "Writes require verifiable authorization; reads do not.": "Las escrituras exigen una autorización verificable; las lecturas no.",
    "100% of returned data conforms to the schema; unrecoverable cases escalate.":
        "El 100% de los datos devueltos cumple el esquema; los casos irrecuperables se escalan.",
    "Repair was not bounded by max_attempts=3: {v}.": "La reparación no respetó el límite max_attempts=3: {v}.",
    "Repair stops at max_attempts.": "La reparación se detiene en max_attempts.",
    "Submit 'structured_extract(model, text, schema, max_attempts)'.": "Entrega 'structured_extract(model, text, schema, max_attempts)'.",
    "An unexpected argument ('skip checks' note) is rejected, not ignored":
        "Un argumento inesperado (la nota 'skip checks') se rechaza, no se ignora",
    "A tool with no contract is refused": "Una herramienta sin contrato se rechaza",
    "Exactly-at-the-bound quantity and price are allowed": "Se permiten una cantidad y un precio exactamente en el límite",
})
