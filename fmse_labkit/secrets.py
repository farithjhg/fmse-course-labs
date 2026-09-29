"""Learner-owned secrets: read them, check for them, never display them.

Provider keys belong to the learner. In Colab they come from the Secrets panel
(key icon in the left sidebar, accessed with google.colab.userdata); elsewhere
from environment variables. Values are never printed, logged, returned in
check results, or written into exported artifacts.
"""

from __future__ import annotations

import os
import re
from typing import Dict, Iterable, List, Optional

# Names the labs look for. Only presence is ever reported.
KNOWN_SECRET_NAMES = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")

# Shapes of common credentials, used to redact anything that slipped into an artifact.
SECRET_PATTERNS = [
    re.compile(r"sk-(?:proj-|ant-|fmse-)?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"xox[abpr]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password)\b\s*[:=]\s*['\"]?[A-Za-z0-9_\-./+]{12,}"),
]

REDACTED = "[REDACTED]"
_seen_values: set = set()


def _colab_secret(name: str) -> Optional[str]:
    try:
        from google.colab import userdata  # type: ignore
    except ImportError:
        return None
    try:
        return userdata.get(name)
    except Exception:  # noqa: BLE001 - missing secret or notebook access not granted
        return None


def get_secret(name: str) -> Optional[str]:
    """Return a secret from Colab Secrets or the environment, or None. Never prints it."""
    value = _colab_secret(name) or os.environ.get(name) or None
    if value:
        _seen_values.add(value)
    return value


def secrets_check(names: Iterable[str] = KNOWN_SECRET_NAMES) -> Dict[str, bool]:
    """Report which secrets are available — presence only, never values."""
    status = {n: bool(get_secret(n)) for n in names}
    for n, present in status.items():
        print(f"  {n:<20} {'available' if present else 'not set'}")
    if not any(status.values()):
        print("  No provider key found. Every lab runs fully offline with the built-in simulator;")
        print("  a key is only needed for the optional real-provider experiments.")
    return status


def redact(text: str, extra_values: Iterable[str] = ()) -> str:
    """Remove credential-shaped strings and any secret value read in this session."""
    if not text:
        return text
    out = str(text)
    for v in list(_seen_values) + [v for v in extra_values if v]:
        if len(v) >= 8:
            out = out.replace(v, REDACTED)
    for pattern in SECRET_PATTERNS:
        out = pattern.sub(REDACTED, out)
    return out


def contains_secret(text: str, extra_values: Iterable[str] = ()) -> List[str]:
    """Names of the patterns/values found (for reporting), empty if clean."""
    found = []
    s = str(text or "")
    for v in list(_seen_values) + [v for v in extra_values if v]:
        if len(v) >= 8 and v in s:
            found.append("known secret value")
    for pattern in SECRET_PATTERNS:
        if pattern.search(s):
            found.append(pattern.pattern[:24])
    return found
