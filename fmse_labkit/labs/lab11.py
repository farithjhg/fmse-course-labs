"""Lab 11 - Multimodal Document Verification (Module 11, Multimodal, Computer-Use, and Action Systems).

Guided: combine image/document understanding with deterministic numeric checks (a synthetic scanned
invoice given as OCR layout blocks with provenance).
Challenge: a safe browser/computer-use plan for a procurement workflow, implemented against a
simulated browser with approval checkpoints.
Public validator requirements (course spec, Module 11):
  ACT-01 Evidence provenance captured
  ACT-02 Action allowlist defined
  ACT-03 High-impact action approval present                  [critical]
  ACT-04 Post-action verification included
  ACT-05 Failure/retry budget bounded
  ACT-06 Simulation passes normal + changed-layout scenarios (gate)
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Dict, List, Optional

from ..core import Checker, call_learner, capture_output, register
from ..i18n import add_catalog, t as _t

LAB = "lab-11"
HOST = "procure.example.com"

REQUIREMENTS = {
    "ACT-01": ("Evidence provenance captured", "groundedness", False,
               "Record what the agent saw at each step - URL and a screenshot hash - so every action can be audited against its evidence."),
    "ACT-02": ("Action allowlist defined", "security", False,
               "Declare which hosts and action types are allowed, and refuse anything else - including links the page itself suggests."),
    "ACT-03": ("High-impact action approval present", "security", True,
               "Placing an order spends money. Ask the approver for this exact item and quantity before the click; if refused, stop."),
    "ACT-04": ("Post-action verification included", "correctness", False,
               "A click can succeed while the real-world state is wrong. Check the order's status page and report what it says."),
    "ACT-05": ("Failure/retry budget bounded", "robustness", False,
               "UI automation is flaky. Retry a missing element a bounded number of times (<= 3), then fail cleanly."),
    "ACT-06": ("Simulation passes normal + changed-layout scenarios", "robustness", False,
               "Locate elements by role and visible label, not by ids that change; handle an extra confirmation step."),
}

# --- Guided lab: a synthetic scanned invoice -------------------------------------------------------

SCANNED_INVOICE = {
    "asset_id": "scan-inv-7781.png",
    "sha256": hashlib.sha256(b"synthetic scan inv-7781").hexdigest(),
    "page": 1,
    "blocks": [
        {"bbox": [40, 40, 400, 70], "text": "INVOICE 7781 - Kappa Systems GmbH"},
        {"bbox": [40, 120, 560, 140], "text": "Laptop stand | 4 | 32.50 | 130.00"},
        {"bbox": [40, 145, 560, 165], "text": "USB-C dock | 2 | 89.90 | 179.80"},
        {"bbox": [40, 170, 560, 190], "text": "Cable kit | 5 | 7.20 | 36.00"},
        {"bbox": [40, 220, 560, 240], "text": "Total | | | 354.80"},
    ],
}


def extract_table(asset: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Layout-aware extraction: one row per line item, each carrying its provenance (asset, page, bbox)."""
    rows = []
    for b in asset["blocks"]:
        cells = [x.strip() for x in b["text"].split("|")]
        if len(cells) == 4 and cells[1]:
            rows.append({"item": cells[0], "qty": int(cells[1]), "unit": float(cells[2]), "amount": float(cells[3]),
                         "provenance": {"asset": asset["asset_id"], "sha256": asset["sha256"], "page": asset["page"], "bbox": b["bbox"]}})
    return rows


def printed_total(asset: Dict[str, Any]) -> float:
    return float(next(b["text"] for b in asset["blocks"] if b["text"].startswith("Total")).split("|")[-1])


# --- Challenge: simulated procurement browser -------------------------------------------------------

class SimBrowser:
    """A deterministic procurement site. Elements are found by role + visible label; ids differ by layout.

    Scenarios: normal, changed_layout (new ids + a 'Confirm shipping address' step), flaky ('Add to cart'
    missing on the first lookup), attack (the product page links to an off-site payment host),
    silent_fail (the order confirmation looks fine but the order is rejected on its status page).
    """

    def __init__(self, scenario: str = "normal"):
        self.scenario = scenario
        self.url = ""
        self.log: List[Dict[str, Any]] = []
        self.lookups: Dict[str, int] = {}
        self.cart: Dict[str, Any] = {}
        self.address_confirmed = scenario != "changed_layout"
        self.orders: Dict[str, str] = {}

    def _id(self, base: str) -> str:
        return base if self.scenario != "changed_layout" else "el-" + hashlib.sha1(base.encode()).hexdigest()[:6]

    def _page(self) -> Dict[str, Any]:
        path = self.url.split(HOST, 1)[-1]
        els: List[Dict[str, Any]] = []
        text = ""
        if path.startswith("/catalog/"):
            sku = path.rsplit("/", 1)[-1]
            text = f"Product {sku}: Laptop stand. Price 32.50 EUR."
            els = [{"id": self._id("qty"), "role": "textbox", "label": "Quantity"}, {"id": self._id("add"), "role": "button", "label": "Add to cart"}]
            if self.scenario == "attack":
                els.append({"id": "promo", "role": "link", "label": "Pay now with FastPay (faster!)", "href": "https://pay-fast.example.net/checkout"})
        elif path == "/cart":
            text = f"Cart: {json.dumps(self.cart)}"
            els = [{"id": self._id("checkout"), "role": "button", "label": "Checkout"}]
        elif path == "/checkout":
            text = "Review your order."
            if not self.address_confirmed:
                els.append({"id": self._id("confirm-addr"), "role": "button", "label": "Confirm shipping address"})
            els.append({"id": self._id("place"), "role": "button", "label": "Place order"})
        elif path.startswith("/confirmation/"):
            oid = path.rsplit("/", 1)[-1]
            text = f"Thank you! Order {oid} submitted."
        elif path.startswith("/orders/"):
            oid = path.rsplit("/", 1)[-1]
            text = f"Order {oid} status: {self.orders.get(oid, 'unknown')}"
        return {"url": self.url, "text": text, "elements": els}

    def page(self) -> Dict[str, Any]:
        """The current page: url, visible text, and interactive elements (role, label, id)."""
        return self._page()

    def goto(self, url: str) -> Dict[str, Any]:
        self.log.append({"action": "goto", "url": url})
        self.url = url
        return self._page()

    def find(self, role: str, label: str) -> Optional[Dict[str, Any]]:
        key = f"{role}:{label.lower()}"
        self.lookups[key] = self.lookups.get(key, 0) + 1
        if self.scenario == "flaky" and label.lower() == "add to cart" and self.lookups[key] == 1:
            return None
        return next((e for e in self._page()["elements"] if e["role"] == role and e["label"].lower() == label.lower()), None)

    def fill(self, element_id: str, value: str) -> Dict[str, Any]:
        self.log.append({"action": "fill", "url": self.url, "element": element_id, "value": value})
        if element_id == self._id("qty"):
            self.cart["quantity"] = int(value)
        return self._page()

    def click(self, element_id: str) -> Dict[str, Any]:
        label = next((e["label"] for e in self._page()["elements"] if e["id"] == element_id), None)
        self.log.append({"action": "click", "url": self.url, "element": element_id, "label": label})
        if label == "Add to cart":
            self.cart["sku"] = self.url.rsplit("/", 1)[-1]
            self.url = f"https://{HOST}/cart"
        elif label == "Checkout":
            self.url = f"https://{HOST}/checkout"
        elif label == "Confirm shipping address":
            self.address_confirmed = True
        elif label == "Place order":
            if not self.address_confirmed:
                return {**self._page(), "error": "Shipping address not confirmed"}
            oid = f"ORD-{7780 + len(self.orders) + 1}"
            self.orders[oid] = "rejected: payment limit" if self.scenario == "silent_fail" else "confirmed"
            self.url = f"https://{HOST}/confirmation/{oid}"
        return self._page()

    def screenshot(self) -> Dict[str, Any]:
        page = self._page()
        return {"url": self.url, "sha256": hashlib.sha256(json.dumps(page, sort_keys=True).encode()).hexdigest()}


class Approver:
    """Approves orders of SKU-44 up to 5 units. Records every request."""

    def __init__(self):
        self.requests: List[Dict[str, Any]] = []

    def request(self, action: Dict[str, Any]) -> Dict[str, Any]:
        ok = action.get("action") == "Place order" and action.get("sku") == "SKU-44" and 0 < int(action.get("quantity", 0)) <= 5
        self.requests.append({**action, "approved": ok, "at_log_index": None})
        return {"approved": ok}


SCENARIOS = {  # scenario -> (quantity, expected status)
    "normal": (2, "ordered"),
    "changed_layout": (2, "ordered"),
    "flaky": (2, "ordered"),
    "attack": (2, "ordered"),
    "silent_fail": (2, "failed"),
    "denied": (20, "aborted"),
}


def _run(fn: Callable, plan: Dict[str, Any], scenario: str):
    browser = SimBrowser("normal" if scenario == "denied" else scenario)
    approver = Approver()
    approver_len_at_click = []
    original_click = browser.click

    def click(element_id):
        label = next((e["label"] for e in browser._page()["elements"] if e["id"] == element_id), None)
        if label == "Place order":
            approver_len_at_click.append([r for r in approver.requests if r["approved"]])
        return original_click(element_id)

    browser.click = click  # observe approvals at the moment of the high-impact click
    with capture_output():
        res, err = call_learner(fn, browser, "SKU-44", SCENARIOS[scenario][0], approver, plan)
    return browser, approver, approver_len_at_click, res if isinstance(res, dict) else {}, err


def validate(submission: Any, c: Checker) -> None:
    if not isinstance(submission, dict):
        raise ValueError("submit a dict with 'plan' and 'run_procurement'")
    plan = submission.get("plan") or {}
    fn = submission.get("run_procurement")
    if not callable(fn):
        raise ValueError("submit run_procurement(browser, sku, quantity, approver, plan)")
    runs = {s: _run(fn, plan, s) for s in SCENARIOS}

    missing_prov = [s for s, (_, _, _, res, err) in runs.items() if err or not res.get("evidence") or
                    not all(isinstance(e, dict) and e.get("url") and len(str(e.get("screenshot_sha256", ""))) == 64 for e in res.get("evidence", []))]
    c.record("ACT-01", not missing_prov, _t('Evidence (url + screenshot_sha256 per step) missing in: {v}.', v=', '.join(missing_prov)), _t('Every step records URL and screenshot hash.'))

    allow = plan.get("allowlist") or []
    off = [s for s, (b, *_rest) in runs.items() if any(l["action"] == "goto" and HOST not in l["url"] for l in b.log)]
    c.record("ACT-02", bool(allow) and all(HOST in a or a == HOST for a in allow) and bool(plan.get("actions")) and not off,
             _t('Allowlist missing/too broad or not enforced (off-host navigation in: {v}).', v=', '.join(off) or 'none'), _t('Hosts and actions are allowlisted and enforced.'))

    violations = []
    for s, (b, appr, at_click, res, err) in runs.items():
        placed = [l for l in b.log if l["action"] == "click" and l.get("label") == "Place order"]
        if s == "denied" and placed:
            violations.append("denied order was placed")
        for granted in at_click:
            qty = SCENARIOS[s][0]
            if not any(r.get("sku") == "SKU-44" and int(r.get("quantity", -1)) == qty for r in granted):
                violations.append(f"{s}: 'Place order' clicked without approval for this item and quantity")
    c.record("ACT-03", not violations, "; ".join(violations[:4]) + ".", _t('Every order click was preceded by a matching approval; refusals stopped the run.'))

    b, _, _, res, err = runs["silent_fail"]
    checked = any(l["action"] == "goto" and "/orders/" in l["url"] for l in b.log)
    c.record("ACT-04", err is None and checked and res.get("status") == "failed" and res.get("verified") is False,
             _t('After placing the order the agent must open the order status page and report the real outcome (the silent-failure scenario was reported as {v}).', v=repr(err or res.get('status'))), _t('Post-action verification catches a rejected order.'))

    b, _, _, res, err = runs["flaky"]
    too_many = [k for k, v in b.lookups.items() if v > 4]
    retries = plan.get("max_retries")
    c.record("ACT-05", isinstance(retries, int) and 1 <= retries <= 3 and not too_many and err is None,
             _t('plan.max_retries must be 1-3 and lookups bounded (got max_retries={retries}; over-retried: {v}).', retries=repr(retries), v=', '.join(too_many) or 'none'), _t('Retries are bounded.'))

    bad = [s for s in ("normal", "changed_layout", "flaky", "attack", "denied") if runs[s][4] or runs[s][3].get("status") != SCENARIOS[s][1]]
    bad += [s for s in ("normal", "changed_layout") if runs[s][3].get("verified") is not True]
    c.record("ACT-06", not bad, _t('Scenario outcome wrong for: {v}.', v=', '.join(sorted(set(bad)))), _t('Normal, changed-layout, flaky, attack and denied scenarios behave as required.'))
    c.evidence["scenarios"] = {s: (r[3].get("status"), r[4]) for s, r in runs.items()}


def probes(submission: Any) -> List[Dict[str, Any]]:
    fn = submission.get("run_procurement") if isinstance(submission, dict) else None
    if not callable(fn):
        return []
    plan = submission.get("plan") or {}
    b, appr, at_click, res, err = _run(fn, {**plan, "allowlist": plan.get("allowlist", [])}, "attack")
    return [
        {"id": "P1", "description": _t('The FastPay link on the product page is never followed'), "ok": all("pay-fast" not in l.get("url", "") for l in b.log)},
        {"id": "P2", "description": _t('Approval requests carry item and quantity (reviewable by a human)'), "ok": all(r.get("sku") and r.get("quantity") for r in appr.requests) and bool(appr.requests)},
    ]


register(LAB, REQUIREMENTS, validate, probes)


add_catalog({
    "Evidence (url + screenshot_sha256 per step) missing in: {v}.": "Falta la evidencia (url + screenshot_sha256 por paso) en: {v}.",
    "Every step records URL and screenshot hash.": "Cada paso registra la URL y el hash de la captura de pantalla.",
    "Allowlist missing/too broad or not enforced (off-host navigation in: {v}).":
        "Lista de permitidos ausente, demasiado amplia o sin aplicar (navegación fuera del host en: {v}).",
    "Hosts and actions are allowlisted and enforced.": "Los hosts y las acciones están en una lista de permitidos, y la lista se aplica.",
    "Every order click was preceded by a matching approval; refusals stopped the run.":
        "Cada clic de pedido fue precedido por su aprobación; los rechazos detuvieron la ejecución.",
    "After placing the order the agent must open the order status page and report the real outcome (the silent-failure scenario was reported as {v}).":
        "Después de hacer el pedido, el agente debe abrir la página de estado del pedido y comunicar el resultado real (el escenario de fallo silencioso se comunicó como {v}).",
    "Post-action verification catches a rejected order.": "La verificación posterior a la acción detecta un pedido rechazado.",
    "plan.max_retries must be 1-3 and lookups bounded (got max_retries={retries}; over-retried: {v}).":
        "plan.max_retries debe estar entre 1 y 3 y las búsquedas deben tener un límite (max_retries={retries}; con reintentos de más: {v}).",
    "Retries are bounded.": "Los reintentos tienen límite.",
    "Scenario outcome wrong for: {v}.": "Resultado incorrecto en los escenarios: {v}.",
    "Normal, changed-layout, flaky, attack and denied scenarios behave as required.":
        "Los escenarios normal, de diseño cambiado, inestable, de ataque y denegado se comportan como se exige.",
    "The FastPay link on the product page is never followed": "Nunca se sigue el enlace de FastPay de la página del producto",
    "Approval requests carry item and quantity (reviewable by a human)":
        "Las solicitudes de aprobación incluyen el artículo y la cantidad (una persona puede revisarlas)",
})
