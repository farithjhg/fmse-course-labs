"""Artifacts and completion records — the evidence a learner carries back to agentic-ai.es.

A completion record is a learning-workflow document, not a certificate: it is
not signed in Phase 1 and the portal treats it as untrusted input. The shape is
fixed (schema "fmse.completion/v1") so the portal can validate it and a Phase 2
evaluator can later add a signature without changing any lab.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from . import COURSE_ID, COURSE_VERSION, __version__
from .core import CheckResult, lab_spec, title as lab_title
from .i18n import add_catalog, t
from .secrets import contains_secret, redact

RECORD_SCHEMA = "fmse.completion/v1"
# Keep in step with the portal's import limits (src/lib/academy/completion-record.ts).
MAX_ARTIFACT_CHARS = 24_000
MAX_RECORD_BYTES = 64_000
BEGIN_MARKER = "----- BEGIN FMSE COMPLETION RECORD -----"
END_MARKER = "----- END FMSE COMPLETION RECORD -----"


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _runtime() -> str:
    try:
        import google.colab  # type: ignore # noqa: F401

        return "colab"
    except ImportError:
        pass
    try:
        get_ipython  # type: ignore # noqa: B018
        return "jupyter"
    except NameError:
        return "python"


class GuidedLog:
    """Records guided-lab progress: steps run, predictions made, observations written.

    Guided work cannot be the only mastery evidence, but it is required evidence:
    the portal's gate checks that the guided lab was completed.
    """

    def __init__(self, lab_id: str, required_steps: Optional[List[str]] = None):
        self.lab_id = lab_spec(lab_id).lab_id
        self.required_steps = list(required_steps or [])
        self.steps: List[str] = []
        self.predictions: List[Dict[str, Any]] = []
        self.observations: Dict[str, str] = {}

    def step(self, name: str) -> None:
        if name not in self.steps:
            self.steps.append(name)
        print(t("  guided step recorded: {name}", name=name))

    def predict(self, question_id: str, prediction: Any) -> None:
        """Record a prediction BEFORE running the experiment it is about."""
        if prediction in (None, "", "?"):
            print(t("  prediction {qid} is empty - write down what you expect before running the next cell.", qid=repr(question_id)))
            return
        self.predictions = [p for p in self.predictions if p["id"] != question_id]
        self.predictions.append({"id": question_id, "prediction": str(prediction)[:500], "outcome": None})
        print(t("  prediction recorded: {qid}", qid=question_id))

    def outcome(self, question_id: str, outcome: Any) -> None:
        for p in self.predictions:
            if p["id"] == question_id:
                p["outcome"] = str(outcome)[:500]

    def observe(self, observations: Dict[str, str], min_chars: int = 20) -> bool:
        short = [k for k, v in observations.items() if len(str(v or "").strip()) < min_chars]
        if short:
            print(t("  observations too short to count: {fields} (write at least a sentence each)", fields=", ".join(short)))
            return False
        self.observations = {k: redact(str(v))[:1500] for k, v in observations.items()}
        print(t("  observations recorded"))
        return True

    @property
    def completed(self) -> bool:
        return all(s in self.steps for s in self.required_steps) and bool(self.predictions) and bool(self.observations)

    def missing(self) -> List[str]:
        out = [t("step '{s}'", s=s) for s in self.required_steps if s not in self.steps]
        if not self.predictions:
            out.append(t("at least one prediction"))
        if not self.observations:
            out.append(t("worksheet observations"))
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {
            "completed": self.completed,
            "steps": self.steps,
            "predictions": self.predictions,
            "observations": self.observations,
        }


def _serialise(content: Any, fmt: str) -> str:
    if isinstance(content, str):
        return content
    if fmt == "yaml":
        try:
            import yaml  # type: ignore

            return yaml.safe_dump(content, sort_keys=False, allow_unicode=True)
        except ImportError:
            pass
    return json.dumps(content, indent=2, ensure_ascii=False, default=str)


def export_artifact(
    lab_id: str,
    artifact: Any,
    *,
    title: Optional[str] = None,
    fmt: Optional[str] = None,
    out_dir: Union[str, Path] = "fmse_artifacts",
    artifact_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Write the artifact to disk and return its portable description.

    Secrets are redacted before anything is written. Content longer than the
    portal's local-storage limit is kept on disk (and in your Drive/GitHub copy)
    and referenced by path instead of being embedded in the completion record.
    """
    spec = lab_spec(lab_id)
    fmt = fmt or ("markdown" if isinstance(artifact, str) else "yaml")
    text = _serialise(artifact, fmt)
    leaked = contains_secret(text)
    if leaked:
        print(t("  WARNING: the artifact contained credential-shaped text; it was redacted before export."))
        text = redact(text)
    ext = {"yaml": "yaml", "markdown": "md", "json": "json", "python": "py"}.get(fmt, "txt")
    folder = Path(out_dir) / spec.lab_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{artifact_type or spec.artifact_type}.{ext}"
    path.write_text(text, encoding="utf-8")
    truncated = len(text) > MAX_ARTIFACT_CHARS
    described = {
        "type": artifact_type or spec.artifact_type,
        "title": (title or lab_title(spec))[:160],
        "format": fmt,
        "content": None if truncated else text,
        "reference": str(path),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "size_bytes": len(text.encode("utf-8")),
        "truncated": truncated,
        "redacted": bool(leaked),
    }
    note = t(" (too large to embed; the record references the file)") if truncated else ""
    print(t("  artifact exported: {path}{note}", path=path, note=note))
    return described


def make_completion_record(
    lab_id: str,
    score: Union[float, CheckResult],
    evidence: Optional[Dict[str, Any]] = None,
    *,
    artifact: Optional[Dict[str, Any]] = None,
    guided: Optional[GuidedLog] = None,
    probes: Optional[List[Dict[str, Any]]] = None,
    notebook: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the completion record the learner imports into agentic-ai.es.

    `score` may be a CheckResult from check_public (preferred: it carries the
    per-requirement checks) or a bare 0-1 score for evidence-only records.
    """
    spec = lab_spec(lab_id)
    if isinstance(score, CheckResult):
        result = score.to_dict()
        passed, value, checks = score.passed, score.score, result["checks"]
        merged_evidence = {**score.evidence, **(evidence or {})}
    else:
        value = float(score)
        passed = value >= spec.public_gate
        checks = []
        merged_evidence = dict(evidence or {})
    clean_evidence = json.loads(redact(json.dumps(merged_evidence, default=str)))
    record = {
        "schema": RECORD_SCHEMA,
        "course": COURSE_ID,
        "course_version": COURSE_VERSION,
        "lab_id": spec.lab_id,
        "validator_id": spec.validator_id,
        "module_id": spec.module_id,
        **({"milestone_id": spec.milestone_id} if spec.milestone_id else {}),
        "labkit_version": __version__,
        "created_at": _now(),
        "passed": bool(passed),
        "score": round(max(0.0, min(1.0, value)), 4),
        "public_gate": spec.public_gate,
        "checks": checks,
        "guided": guided.to_dict() if guided else {"completed": False, "steps": [], "predictions": [], "observations": {}},
        "artifact": artifact,
        "evidence": clean_evidence,
        "probes": [{"id": p["id"], "description": p["description"], "ok": bool(p.get("ok"))} for p in (probes or [])],
        "source": {"runtime": _runtime(), "notebook": os.path.basename(notebook or spec.notebook)},
        "signature": None,
    }
    size = len(json.dumps(record).encode())
    if size > MAX_RECORD_BYTES and artifact and artifact.get("content"):
        record["artifact"] = {**artifact, "content": None, "truncated": True}
        print(t("  record too large for the portal; artifact content replaced by its file reference."))
    if guided and not guided.completed:
        print(t("  note: guided lab not complete yet - missing {items}.", items=", ".join(guided.missing())))
    return record


def save_record(record: Dict[str, Any], out_dir: Union[str, Path] = "fmse_artifacts") -> Path:
    path = Path(out_dir) / (record.get("milestone_id") or record["lab_id"]) / "completion-record.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def show_record(record: Dict[str, Any], download: bool = True) -> str:
    """Print the record between markers for copy/paste, and offer a download in Colab."""
    text = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    path = save_record(record)
    status = t("PASSED") if record["passed"] else t("NOT PASSED")
    print(t("Completion record for {lab} ({status}, score {score}) saved to {path}", lab=record["lab_id"], status=status, score=f"{record['score']:.0%}", path=path))
    print(t("Copy everything between the markers (markers included) and paste it into"))
    print(t("agentic-ai.es/academy/fmse/learn/{module} -> 'Import lab result'.", module=record["module_id"]) + "\n")
    print(BEGIN_MARKER)
    print(text)
    print(END_MARKER)
    if download:
        try:
            from google.colab import files  # type: ignore

            files.download(str(path))
        except Exception:  # noqa: BLE001 - not in Colab, or downloads blocked
            pass
    return text


add_catalog({
    "  guided step recorded: {name}": "  paso guiado registrado: {name}",
    "  prediction {qid} is empty - write down what you expect before running the next cell.": "  la predicción {qid} está vacía: anota qué esperas que pase antes de ejecutar la siguiente celda.",
    "  prediction recorded: {qid}": "  predicción registrada: {qid}",
    "  observations too short to count: {fields} (write at least a sentence each)": "  observaciones demasiado breves para tenerlas en cuenta: {fields} (escribe al menos una oración en cada una)",
    "  observations recorded": "  observaciones registradas",
    "step '{s}'": "el paso '{s}'",
    "at least one prediction": "al menos una predicción",
    "worksheet observations": "las observaciones de la hoja de trabajo",
    "  WARNING: the artifact contained credential-shaped text; it was redacted before export.": "  AVISO: el artefacto contenía texto que parecía una credencial; se enmascaró antes de exportarlo.",
    " (too large to embed; the record references the file)": " (demasiado grande para incrustarlo; el registro remite al archivo)",
    "  artifact exported: {path}{note}": "  artefacto exportado: {path}{note}",
    "  record too large for the portal; artifact content replaced by its file reference.": "  registro demasiado grande para el portal; el contenido del artefacto se reemplazó por la referencia a su archivo.",
    "  note: guided lab not complete yet - missing {items}.": "  nota: el laboratorio guiado todavía no está completo; falta: {items}.",
    "Completion record for {lab} ({status}, score {score}) saved to {path}": "Registro de finalización de {lab} ({status}, puntuación {score}) guardado en {path}",
    "Copy everything between the markers (markers included) and paste it into": "Copia todo lo que hay entre los marcadores (incluidos los marcadores) y pégalo en",
    "agentic-ai.es/academy/fmse/learn/{module} -> 'Import lab result'.": "agentic-ai.es/academy/fmse/learn/{module} -> 'Importar el resultado del laboratorio'.",
})
