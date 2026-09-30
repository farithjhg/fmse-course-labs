"""Language of the lab kit's messages: English (default) or Spanish.

Spanish notebooks call ``fmse.set_language("es")`` in their setup cell. Every
learner-facing message goes through ``t()``: the English text is the key, and
each lab module registers its Spanish templates with ``add_catalog``. A missing
translation falls back to English (a test fails if any key is missing).

Validators never depend on the language setting: they accept answers written in
either language. Only the messages change.
"""

from __future__ import annotations

from typing import Any, Dict

LANGUAGES = ("en", "es")
_lang = "en"
_catalog: Dict[str, str] = {}


def set_language(lang: str) -> str:
    """Choose the language of the kit's messages ("en" or "es"). Returns the active language."""
    global _lang
    _lang = lang if lang in LANGUAGES else "en"
    return _lang


def get_language() -> str:
    return _lang


def add_catalog(entries: Dict[str, str]) -> None:
    """Register Spanish templates, keyed by the exact English template."""
    for en, es in entries.items():
        if en in _catalog and _catalog[en] != es:
            raise ValueError(f"conflicting Spanish translation for {en!r}")
        _catalog[en] = es


def t(template: str, /, **values: Any) -> str:
    """The message in the active language, with ``{name}`` placeholders filled."""
    text = _catalog.get(template, template) if _lang == "es" else template
    return text.format(**values) if values else text


def catalog() -> Dict[str, str]:
    return dict(_catalog)
