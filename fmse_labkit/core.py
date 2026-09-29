"""Validator result contract, lab registry and the public check runner.

Result contract (course specification, "Validator result contract"):

    class CheckResult: lab_id, passed, score, checks[]
    class Check:       id, status ("pass" | "fail" | "warn"), dimension, message, hint

Validators must teach by reporting which requirement failed, not by revealing
the expected implementation, and they must fail safely: an exception raised by
learner code is reported as a failed requirement, never as a crash.
"""

from __future__ import annotations

import contextlib
import io
import traceback
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

from . import COURSE_ID, COURSE_VERSION

STATUSES = ("pass", "fail", "warn")


@dataclass
class Check:
    id: str
    status: str
    dimension: str
    message: str
    hint: Optional[str] = None
    critical: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CheckResult:
    lab_id: str
    passed: bool
    score: float
    checks: List[Check] = field(default_factory=list)
    public_gate: float = 1.0
    evidence: Dict[str, Any] = field(default_factory=dict)

    @property
    def failed_requirements(self) -> List[str]:
        return [c.id for c in self.checks if c.status == "fail"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lab_id": self.lab_id,
            "passed": self.passed,
            "score": round(self.score, 4),
            "public_gate": self.public_gate,
            "checks": [c.to_dict() for c in self.checks],
            "failed_requirements": self.failed_requirements,
        }

    def show(self) -> "CheckResult":
        """Print requirement-oriented feedback. Status is spelled out, never colour-only."""
        verdict = "PASSED" if self.passed else "NOT PASSED"
        print(f"{self.lab_id}: {verdict} - score {self.score:.0%} (gate {self.public_gate:.0%})")
        for c in self.checks:
            label = c.status.upper()
            crit = " [critical]" if c.critical else ""
            print(f"  {label:<4}  {c.id:<7} {c.dimension}{crit}: {c.message}")
            if c.status != "pass" and c.hint:
                print(f"        Hint: {c.hint}")
        if not self.passed:
            critical_failed = [c.id for c in self.checks if c.critical and c.status == "fail"]
            if critical_failed:
                print(f"  Critical requirement(s) failed: {', '.join(critical_failed)}. A critical gate cannot be offset by other scores.")
        return self

    def _repr_pretty_(self, p, cycle):  # IPython display without colour dependence
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.show()
        p.text(buf.getvalue())


@dataclass
class LabSpec:
    lab_id: str
    validator_id: str
    module_id: str
    notebook: str
    title: str
    public_gate: float
    artifact_type: str
    milestone_id: Optional[str] = None
    # requirement id -> (text, dimension, critical, hint)
    requirements: Dict[str, tuple] = field(default_factory=dict)
    validator: Optional[Callable[[Any, "Checker"], None]] = None
    prober: Optional[Callable[[Any], List[Dict[str, Any]]]] = None


# The full roadmap is registered from day one so identifiers are stable; lab
# modules attach requirements and validators to their entry.
LAB_SPECS: Dict[str, LabSpec] = {}


def _spec(lab_id, validator_id, module_id, notebook, title, gate, artifact_type):
    LAB_SPECS[lab_id] = LabSpec(lab_id, validator_id, module_id, notebook, title, gate, artifact_type)


_spec("lab-00", "00-task-framing", "m00-ai-power-user", "labs/lab-00-task-framing.ipynb", "Task Framing Laboratory", 1.0, "ai_task_brief")
_spec("lab-01", "01-typed-model-call", "m01-engineering-bootcamp", "labs/lab-01-typed-model-call.ipynb", "Build a Typed Model Call", 1.0, "typed_interface_contract")
_spec("lab-02", "02-conops-builder", "m02-problem-conops", "labs/lab-02-conops-builder.ipynb", "ConOps Builder", 1.0, "conops")
_spec("lab-03", "03-ai-fmea", "m03-requirements-fmea", "labs/lab-03-ai-fmea.ipynb", "Requirements and AI-FMEA Workbench", 1.0, "srs_traceability_fmea")
_spec("lab-04", "04-model-profiler", "m04-model-mechanics", "labs/lab-04-model-profiler.ipynb", "Model Profiler", 1.0, "model_characterization_report")
_spec("lab-05", "05-rag-first-principles", "m05-rag-grounding", "labs/lab-05-rag-first-principles.ipynb", "RAG from First Principles", 1.0, "information_architecture")
_spec("lab-06", "06-trade-study", "m06-architecture-trade-studies", "labs/lab-06-trade-study.ipynb", "Architecture Trade Study Workbench", 1.0, "architecture_specification")
_spec("lab-07", "07-prompt-systems", "m07-prompt-systems", "labs/lab-07-prompt-systems.ipynb", "Prompt Manifest Laboratory", 0.8, "prompt_manifest")
_spec("lab-08", "08-tool-contracts", "m08-structured-interfaces", "labs/lab-08-tool-contracts.ipynb", "Typed Extraction and Tool Contract", 1.0, "interface_specification")
_spec("lab-09", "09-context-budget", "m09-context-engineering", "labs/lab-09-context-budget.ipynb", "Context Budget Optimizer", 1.0, "context_architecture")
_spec("lab-10", "10-safe-agent-mcp", "m10-agents-mcp", "labs/lab-10-safe-agent-mcp.ipynb", "Safe Tool-Using Agent", 1.0, "agent_architecture")
_spec("lab-11", "11-multimodal-verification", "m11-multimodal-action", "labs/lab-11-multimodal-verification.ipynb", "Multimodal Document Verification", 1.0, "action_safety_design")
_spec("lab-12", "12-evaluation-harness", "m12-evaluation-vv", "labs/lab-12-evaluation-harness.ipynb", "Evaluation Harness", 1.0, "evaluation_plan")
_spec("lab-13", "13-break-the-agent", "m13-security-red-teaming", "labs/lab-13-break-the-agent.ipynb", "Break the Agent", 1.0, "threat_model")
_spec("lab-14", "14-optimization", "m14-optimization-dspy", "labs/lab-14-optimization.ipynb", "Optimize a Measured Pipeline", 1.0, "optimization_report")
_spec("lab-15", "15-production", "m15-production-operations", "labs/lab-15-production.ipynb", "CI Gate Simulator", 1.0, "production_runbook")
_spec("capstone", "capstone", "m16-capstone", "capstone/capstone-studio.ipynb", "Capstone Studio", 1.0, "capstone_package")


def lab_spec(lab_id: str) -> LabSpec:
    """Resolve 'lab-07', '07', '07-prompt-systems' or 'capstone-define' to a spec."""
    key = str(lab_id).strip()
    if key in LAB_SPECS:
        return LAB_SPECS[key]
    for spec in LAB_SPECS.values():
        if key == spec.validator_id or key == spec.lab_id.replace("lab-", ""):
            return spec
    raise KeyError(f"Unknown lab id {lab_id!r}. Known labs: {', '.join(sorted(LAB_SPECS))}")


def register(lab_id: str, requirements: Dict[str, tuple], validator, prober=None, public_gate: Optional[float] = None):
    spec = lab_spec(lab_id)
    spec.requirements = requirements
    spec.validator = validator
    spec.prober = prober
    if public_gate is not None:
        spec.public_gate = public_gate


class Checker:
    """Collects checks for one validation run; enforces that every requirement is reported once."""

    def __init__(self, spec: LabSpec):
        self.spec = spec
        self.checks: Dict[str, Check] = {}
        self.evidence: Dict[str, Any] = {}

    def record(self, req_id: str, ok: bool, fail: str, ok_msg: str = "Requirement met.", warn: bool = False) -> bool:
        text, dimension, critical, hint = self.spec.requirements[req_id]
        if req_id in self.checks and self.checks[req_id].status == "fail":
            return False  # first failure wins; keep the most specific message
        status = "pass" if ok else ("warn" if warn else "fail")
        self.checks[req_id] = Check(req_id, status, dimension, ok_msg if ok else fail, None if ok else hint, critical)
        return ok

    def fail(self, req_id: str, message: str) -> bool:
        return self.record(req_id, False, message)


@contextlib.contextmanager
def capture_output():
    """Capture stdout/stderr (used by security checks that look for leaked secrets)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        yield out, err


def call_learner(fn, *args, **kwargs):
    """Run learner code; return (value, error message). Never raises."""
    try:
        return fn(*args, **kwargs), None
    except NotImplementedError:
        return None, "the function is not implemented yet (raises NotImplementedError)"
    except Exception as exc:  # noqa: BLE001 - validators must fail safely
        last = traceback.extract_tb(exc.__traceback__)[-1:] if exc.__traceback__ else []
        where = f" (line {last[0].lineno})" if last else ""
        return None, f"raised {type(exc).__name__}: {str(exc)[:200]}{where}"


def check_public(lab_id: str, submission: Any) -> CheckResult:
    """Run the public validators for a lab against a submission."""
    spec = lab_spec(lab_id)
    if spec.validator is None:
        raise NotImplementedError(f"{spec.lab_id} has no public validator in labkit {__import__('fmse_labkit').__version__}.")
    checker = Checker(spec)
    try:
        spec.validator(submission, checker)
    except Exception as exc:  # noqa: BLE001 - a validator bug must not look like a learner pass
        for rid in spec.requirements:
            if rid not in checker.checks:
                checker.fail(rid, f"Could not evaluate this requirement: submission raised {type(exc).__name__}: {str(exc)[:160]}")
    for rid in spec.requirements:  # any requirement the validator did not reach is a failure
        if rid not in checker.checks:
            checker.fail(rid, "Not evaluated: an earlier structural problem prevented this check.")
    ordered = [checker.checks[r] for r in spec.requirements]
    passed_n = sum(1 for c in ordered if c.status in ("pass", "warn"))
    score = passed_n / len(ordered) if ordered else 0.0
    critical_ok = all(c.status != "fail" for c in ordered if c.critical)
    passed = score + 1e-9 >= spec.public_gate and critical_ok
    return CheckResult(spec.lab_id, passed, score, ordered, spec.public_gate, checker.evidence)


def probe(lab_id: str, submission: Any) -> List[Dict[str, Any]]:
    """Robustness / adversarial probes: each returns {id, description, ok} where ok means the stated property holds."""
    spec = lab_spec(lab_id)
    if spec.prober is None:
        return []
    results = spec.prober(submission)
    for r in results:
        label = "HOLDS" if r.get("ok") else "VIOLATED"
        print(f"  {label:<8} {r['id']}: {r['description']}")
    return results


__all__ = [
    "Check",
    "CheckResult",
    "Checker",
    "LAB_SPECS",
    "LabSpec",
    "call_learner",
    "capture_output",
    "check_public",
    "lab_spec",
    "probe",
    "register",
    "COURSE_ID",
    "COURSE_VERSION",
]
