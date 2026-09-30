"""Shared parsing helpers for artifact validators (YAML/Markdown/dict submissions)."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Dict, List

from .i18n import add_catalog, t


def normalise_key(key: str) -> str:
    # Accents are folded first, so a Spanish heading such as "Criterios de éxito" becomes criterios_de_exito.
    folded = unicodedata.normalize("NFKD", str(key)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", folded.strip().lower()).strip("_")


def parse_document(submission: Any) -> Dict[str, Any]:
    """Accept a dict, a YAML/JSON string, or Markdown with '#'/'##' section headings."""
    if isinstance(submission, dict):
        return {normalise_key(k): v for k, v in submission.items()}
    if not isinstance(submission, str) or not submission.strip():
        raise ValueError(t("submission is empty; provide a dict, YAML/JSON text, or Markdown with section headings"))
    text = submission.strip()
    if text.startswith("{"):
        return parse_document(json.loads(text))
    if not re.search(r"^#{1,3}\s", text, re.M):
        try:
            import yaml  # type: ignore

            data = yaml.safe_load(text)
            if isinstance(data, dict):
                return parse_document(data)
        except ImportError:
            pass
    return parse_markdown_sections(text)


def parse_markdown_sections(text: str) -> Dict[str, Any]:
    """'## Section' blocks -> {section: body}; '### Sub' inside a section -> nested dict."""
    doc: Dict[str, Any] = {}
    current, sub = None, None
    for line in text.splitlines():
        h2 = re.match(r"^#{1,2}\s+(.+?)\s*$", line)
        h3 = re.match(r"^#{3,4}\s+(.+?)\s*$", line)
        if h2:
            current, sub = normalise_key(h2.group(1)), None
            doc[current] = ""
        elif h3 and current:
            sub = normalise_key(h3.group(1))
            if not isinstance(doc[current], dict):
                doc[current] = {"_text": doc[current]} if str(doc[current]).strip() else {}
            doc[current][sub] = ""
        elif current:
            if sub:
                doc[current][sub] += line + "\n"
            else:
                doc[current] += line + "\n"
    return {k: (v.strip() if isinstance(v, str) else {sk: sv.strip() for sk, sv in v.items()}) for k, v in doc.items()}


def as_items(value: Any) -> List[str]:
    """A list, a Markdown bullet list or a multi-line string -> list of non-empty item strings."""
    if value is None:
        return []
    if isinstance(value, list):
        out = []
        for v in value:
            out.append(" ".join(f"{k}: {x}" for k, x in v.items()) if isinstance(v, dict) else str(v))
        return [o.strip() for o in out if str(o).strip()]
    if isinstance(value, dict):
        return [f"{k}: {v}" for k, v in value.items() if str(v).strip()]
    lines = [re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", ln).strip() for ln in str(value).splitlines()]
    return [ln for ln in lines if ln]


def text_of(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value or "")


def first(doc: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in doc and doc[k] not in (None, "", [], {}):
            return doc[k]
    return None


def has_number(text: str) -> bool:
    return bool(re.search(r"\d", text or ""))


add_catalog({
    "submission is empty; provide a dict, YAML/JSON text, or Markdown with section headings":
        "la entrega está vacía; envía un dict, texto en YAML o JSON, o Markdown con encabezados de sección",
})


# --- Answers written in Spanish -------------------------------------------------------------------
# Data keys stay English in every notebook, but the values learners type (scenario types, requirement
# categories, verification methods, free text) may be Spanish. Validators compare folded text.

def fold(text: Any) -> str:
    """Lower-case text with accents removed, so 'Excepción' and 'excepcion' compare equal."""
    return unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii").lower()


# English term -> Spanish equivalents (folded).
SPANISH_TERMS: Dict[str, tuple] = {
    "nominal": ("nominal",),
    "exception": ("excepcion",),
    "degraded": ("degradado", "degradada"),
    "test": ("prueba",),
    "analysis": ("analisis",),
    "inspection": ("inspeccion",),
    "demonstration": ("demostracion",),
    "functional": ("funcional",),
    "performance": ("rendimiento",),
    "interface": ("interfaz",),
    "security": ("seguridad",),
    "cost": ("coste", "costo"),
    "operational": ("operativo", "operativa", "operacional", "operacion"),
}


def mentions(text: Any, term: str) -> bool:
    """True if the text contains the English term or one of its Spanish equivalents."""
    folded = fold(text)
    return term in folded or any(es in folded for es in SPANISH_TERMS.get(term, ()))


def canonical(value: Any) -> str:
    """A single-word answer mapped to its English term ('Rendimiento' -> 'performance'); otherwise folded."""
    folded = fold(value).strip()
    for en, es in SPANISH_TERMS.items():
        if folded == en or folded in es:
            return en
    return folded


_SHALL = re.compile(r"\b(shall|debera|deberan)\b")


def has_shall(statement: Any) -> bool:
    """A binding requirement: 'shall', or its Spanish form 'deberá'."""
    return bool(_SHALL.search(fold(statement)))
