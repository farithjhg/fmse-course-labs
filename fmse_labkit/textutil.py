"""Shared parsing helpers for artifact validators (YAML/Markdown/dict submissions)."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List


def normalise_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")


def parse_document(submission: Any) -> Dict[str, Any]:
    """Accept a dict, a YAML/JSON string, or Markdown with '#'/'##' section headings."""
    if isinstance(submission, dict):
        return {normalise_key(k): v for k, v in submission.items()}
    if not isinstance(submission, str) or not submission.strip():
        raise ValueError("submission is empty; provide a dict, YAML/JSON text, or Markdown with section headings")
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
