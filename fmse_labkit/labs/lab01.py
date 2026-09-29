"""Lab 01 - Build a Typed Model Call (Module 1, Engineering Bootcamp for AI Systems).

Guided: execute a working (happy-path) API wrapper against a mock model endpoint,
validate its output against a JSON Schema, and inspect failures.
Challenge: implement call_and_validate() with timeout, bounded retry, schema
validation, and deterministic business-rule checks.
Public validator requirements (course spec, Module 01):
  API-01 Valid response passes
  API-02 Malformed JSON fails gracefully
  API-03 Schema mismatch returns typed error
  API-04 Retry count is bounded
  API-05 Business-rule violation returns typed error   (from the challenge brief)
  SEC-01 Secret is not printed or persisted in notebook output   [critical]
  MAN-01 Experiment manifest exported                             (from the gate)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..core import Checker, call_learner, capture_output, register
from ..schema import validate as schema_validate
from ..secrets import contains_secret

LAB = "lab-01"

REQUIREMENTS = {
    "API-01": ("Valid response passes", "correctness", False,
               "Start from the happy path: a response that parses and satisfies the schema and the business rule should come back as a success with the parsed data."),
    "API-02": ("Malformed JSON fails gracefully", "robustness", False,
               "Parsing untrusted text can raise. Decide which result status represents that, and return it instead of letting the exception escape."),
    "API-03": ("Schema mismatch returns typed error", "schema", False,
               "Valid JSON is not the same as a valid contract. Report schema violations as their own typed status, separate from parse failures."),
    "API-04": ("Retry count is bounded", "cost", False,
               "Every retry costs time and money. Count attempts and stop at the configured bound, whatever the endpoint keeps returning."),
    "API-05": ("Business-rule violation returns typed error", "correctness", False,
               "A schema cannot check arithmetic. Apply the deterministic business rule after schema validation and report its failure as its own status."),
    "SEC-01": ("Secret is not printed or persisted in notebook output", "security", True,
               "Look at everything your function prints, logs, raises, or returns. None of it may contain the credential value."),
    "MAN-01": ("Experiment manifest exported", "reproducibility", False,
               "Revisit lesson 1.4: the manifest records model, prompt version, dataset version, and metrics."),
}

STATUSES = ("ok", "invalid_json", "schema_error", "business_rule_error", "transport_error", "timeout")

INVOICE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["invoice_id", "currency", "total", "line_items"],
    "additionalProperties": False,
    "properties": {
        "invoice_id": {"type": "string", "pattern": r"^INV-\d{4}$"},
        "currency": {"type": "string", "enum": ["EUR", "USD", "GBP"]},
        "total": {"type": "number", "minimum": 0},
        "line_items": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["description", "amount"],
                "properties": {"description": {"type": "string", "minLength": 1}, "amount": {"type": "number", "minimum": 0}},
            },
        },
    },
}

BUSINESS_RULES = ["total must equal the sum of line_items[].amount (tolerance 0.01)"]

REQUEST = {"task": "extract_invoice_summary", "document": "Invoice INV-0042 ... (synthetic)"}


@dataclass
class CallResult:
    """Typed result every call_and_validate() implementation returns."""

    status: str  # one of STATUSES
    data: Optional[Dict[str, Any]] = None
    errors: List[str] = field(default_factory=list)
    attempts: int = 0


class MockTimeout(TimeoutError):
    """Raised by the mock endpoint when a call exceeds its timeout."""


@dataclass
class MockResponse:
    status_code: int
    text: str

    def json(self) -> Any:
        return json.loads(self.text)


_VALID = {"invoice_id": "INV-0042", "currency": "EUR", "total": 120.0,
          "line_items": [{"description": "Consulting", "amount": 100.0}, {"description": "Travel", "amount": 20.0}]}


class MockModelEndpoint:
    """A fake model HTTP endpoint with scripted behaviour.

    Scenarios: valid, malformed_json, schema_mismatch, business_rule,
    transient_then_valid, always_503, timeout, auth_echo.
    Requires an 'Authorization: Bearer <key>' header and a timeout_s argument,
    like a real service. `calls` counts requests received.
    """

    SCENARIOS = ("valid", "malformed_json", "schema_mismatch", "business_rule", "transient_then_valid", "always_503", "timeout", "auth_echo")

    def __init__(self, scenario: str = "valid", expected_key: Optional[str] = None):
        if scenario not in self.SCENARIOS:
            raise ValueError(f"unknown scenario {scenario!r}")
        self.scenario = scenario
        self._expected_key = expected_key
        self.calls = 0

    def post(self, payload: Dict[str, Any], *, headers: Dict[str, str], timeout_s: float) -> MockResponse:
        self.calls += 1
        if not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
            raise ValueError("timeout_s must be a positive number of seconds")
        auth = (headers or {}).get("Authorization", "")
        if self.scenario == "auth_echo":
            # A badly behaved service that echoes the credential in its error body.
            return MockResponse(401, json.dumps({"error": f"invalid credential {auth}"}))
        if not auth.startswith("Bearer ") or (self._expected_key and auth != f"Bearer {self._expected_key}"):
            return MockResponse(401, json.dumps({"error": "missing or invalid credentials"}))
        if self.scenario == "timeout":
            raise MockTimeout(f"no response within {timeout_s}s")
        if self.scenario == "always_503" or (self.scenario == "transient_then_valid" and self.calls == 1):
            return MockResponse(503, json.dumps({"error": "model overloaded, retry later"}))
        if self.scenario == "malformed_json":
            return MockResponse(200, '{"invoice_id": "INV-0042", "currency": "EUR", "total": 120.0, "line_items": [')
        if self.scenario == "schema_mismatch":
            return MockResponse(200, json.dumps({"invoice_id": "42", "total": "120.00", "line_items": []}))
        if self.scenario == "business_rule":
            return MockResponse(200, json.dumps({**_VALID, "total": 150.0}))
        return MockResponse(200, json.dumps(_VALID))


def simple_call(endpoint: MockModelEndpoint, request: Dict[str, Any], api_key: str) -> Dict[str, Any]:
    """The guided lab's working wrapper: one call, parse, schema-validate. Happy path only.

    It has no timeout policy, no retry, no business rule, and it raises on every
    failure — the guided lab asks you to observe exactly how it fails.
    """
    response = endpoint.post(request, headers={"Authorization": f"Bearer {api_key}"}, timeout_s=10)
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}")
    data = response.json()
    errors = schema_validate(data, INVOICE_SCHEMA)
    if errors:
        raise ValueError(f"schema violations: {errors}")
    return data


# Fake credential used to detect leaks; assembled at runtime so secret scanners do not flag the source.
CANARY_KEY = "sk-" + "fmse-canary-" + "7f3a9c2e1b5d4a6f8e0c"


def _run(fn: Callable, scenario: str, max_retries: int = 2):
    endpoint = MockModelEndpoint(scenario, expected_key=CANARY_KEY)
    result, err = call_learner(fn, endpoint, REQUEST, INVOICE_SCHEMA, api_key=CANARY_KEY, timeout_s=2.0, max_retries=max_retries)
    return endpoint, result, err


def _status(result: Any) -> Optional[str]:
    return getattr(result, "status", None) if result is not None else None


def validate(submission: Any, c: Checker) -> None:
    if not isinstance(submission, dict) or not callable(submission.get("call_and_validate")):
        for rid in ("API-01", "API-02", "API-03", "API-04", "API-05", "SEC-01"):
            c.fail(rid, "Submit a dict with your call_and_validate function under the key 'call_and_validate'.")
        fn = None
    else:
        fn = submission["call_and_validate"]

    if fn is not None:
        runs = {}
        with capture_output() as (out, errbuf):
            for scenario in ("valid", "malformed_json", "schema_mismatch", "business_rule", "transient_then_valid", "always_503", "timeout", "auth_echo"):
                runs[scenario] = _run(fn, scenario)
        printed = out.getvalue() + errbuf.getvalue()

        ep, res, err = runs["valid"]
        ok = err is None and _status(res) == "ok" and isinstance(getattr(res, "data", None), dict) and res.data.get("total") == 120.0
        c.record("API-01", ok, f"A valid response did not come back as status 'ok' with the parsed data ({err or 'status ' + repr(_status(res))}).",
                 "Valid response returns status 'ok' with parsed data.")

        ep, res, err = runs["malformed_json"]
        c.record("API-02", err is None and _status(res) == "invalid_json",
                 f"Truncated JSON did not return status 'invalid_json' ({err or 'status ' + repr(_status(res))}).",
                 "Truncated JSON returns a typed 'invalid_json' result without raising.")

        ep, res, err = runs["schema_mismatch"]
        c.record("API-03", err is None and _status(res) == "schema_error" and bool(getattr(res, "errors", None)),
                 f"A schema-violating response did not return status 'schema_error' with error details ({err or 'status ' + repr(_status(res))}).",
                 "Schema violations return 'schema_error' with details.")

        ep, res, err = runs["business_rule"]
        c.record("API-05", err is None and _status(res) == "business_rule_error",
                 f"A schema-valid response whose total does not match its line items was not rejected as 'business_rule_error' ({err or 'status ' + repr(_status(res))}).",
                 "Business-rule violations return 'business_rule_error'.")

        problems = []
        ep, res, err = runs["always_503"]
        if err or ep.calls > 3:
            problems.append(f"a permanently failing endpoint was called {ep.calls} times with max_retries=2")
        elif _status(res) != "transport_error":
            problems.append(f"a permanently failing endpoint returned status {_status(res)!r} instead of 'transport_error'")
        elif getattr(res, "attempts", None) != ep.calls:
            problems.append("CallResult.attempts does not match the number of calls made")
        ep, res, err = runs["timeout"]
        if err or ep.calls > 3 or _status(res) != "timeout":
            problems.append(f"a timing-out endpoint gave {err or 'status ' + repr(_status(res))} after {ep.calls} call(s)")
        ep, res, err = runs["transient_then_valid"]
        if err or _status(res) != "ok":
            problems.append("a single transient 503 was not recovered by a retry")
        c.record("API-04", not problems, "; ".join(problems) + ".", "Retries recover transient failures and stop at the bound.")
        c.evidence["calls_on_permanent_failure"] = runs["always_503"][0].calls

        leaks = []
        if all(res is None for _, res, _ in runs.values()):
            c.fail("SEC-01", "Cannot verify credential handling: the function did not return a result in any scenario.")
        if CANARY_KEY in printed:
            leaks.append("printed output")
        for scenario, (_, res, err) in runs.items():
            if CANARY_KEY in repr(res) or CANARY_KEY in str(err or ""):
                leaks.append(f"the {scenario} result")
        c.record("SEC-01", not leaks, f"The credential value appeared in {', '.join(sorted(set(leaks)))}.",
                 "The credential never appears in output, results, or errors.")

    manifest = submission.get("manifest") if isinstance(submission, dict) else None
    if not isinstance(manifest, dict):
        c.fail("MAN-01", "No experiment manifest found under the key 'manifest'.")
    else:
        missing = [k for k in ("model", "prompt_version", "dataset_version", "metrics") if not manifest.get(k)]
        metrics = manifest.get("metrics")
        numeric = isinstance(metrics, dict) and any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in metrics.values())
        if missing:
            c.fail("MAN-01", f"The manifest is missing: {', '.join(missing)}.")
        elif not numeric:
            c.fail("MAN-01", "The manifest's metrics contain no measured numeric values.")
        elif contains_secret(json.dumps(manifest, default=str), [CANARY_KEY]):
            c.fail("MAN-01", "The manifest contains credential-shaped text; manifests are shared, keys are not.")
        else:
            c.record("MAN-01", True, "", "Manifest records model, prompt version, dataset version and metrics.")


def run_experiment(fn: Callable, trials_per_scenario: int = 1) -> Dict[str, Any]:
    """Run your implementation across every scenario and return metrics for the experiment manifest."""
    statuses: Dict[str, str] = {}
    total_calls = 0
    with capture_output():
        for scenario in MockModelEndpoint.SCENARIOS:
            for _ in range(trials_per_scenario):
                ep, res, err = _run(fn, scenario)
                total_calls += ep.calls
                statuses[scenario] = err or _status(res) or "none"
    expected = {"valid": "ok", "malformed_json": "invalid_json", "schema_mismatch": "schema_error", "business_rule": "business_rule_error",
                "transient_then_valid": "ok", "always_503": "transport_error", "timeout": "timeout", "auth_echo": "transport_error"}
    correct = sum(1 for s, st in statuses.items() if expected[s] == st)
    return {
        "scenarios": len(statuses),
        "typed_status_accuracy": round(correct / len(statuses), 3),
        "total_endpoint_calls": total_calls,
        "mean_calls_per_scenario": round(total_calls / len(statuses), 2),
        "statuses": statuses,
    }


def probes(submission: Any) -> List[Dict[str, Any]]:
    """Adversarial endpoint conditions beyond the public suite."""
    fn = submission.get("call_and_validate") if isinstance(submission, dict) else None
    if not callable(fn):
        return []
    cases = []
    with capture_output():
        ep, res, err = _run(fn, "always_503", max_retries=0)
        cases.append({"id": "P1", "description": "max_retries=0 makes exactly one call", "ok": err is None and ep.calls == 1})
        ep, res, err = _run(fn, "always_503", max_retries=5)
        cases.append({"id": "P2", "description": "max_retries=5 makes at most 6 calls", "ok": err is None and ep.calls <= 6})
        ep, res, err = _run(fn, "auth_echo")
        cases.append({"id": "P3", "description": "401 is not retried (retrying cannot fix a credential)", "ok": err is None and ep.calls == 1})
    return cases


register(LAB, REQUIREMENTS, validate, probes)
