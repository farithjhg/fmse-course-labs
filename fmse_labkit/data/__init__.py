"""Datasets shipped with the labkit (small, synthetic, public)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DIR = Path(__file__).parent


def load(name: str) -> Any:
    """Load a bundled JSON dataset by name, e.g. load('lab05_corpus')."""
    path = _DIR / f"{name}.json"
    if not path.exists():
        available = sorted(p.stem for p in _DIR.glob("*.json"))
        raise FileNotFoundError(f"No dataset {name!r}. Available: {', '.join(available) or 'none'}")
    return json.loads(path.read_text(encoding="utf-8"))
