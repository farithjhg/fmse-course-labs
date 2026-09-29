"""Phase 2 adapter: remote evaluation on agentic-ai.es.

Phase 1 of the course runs public validators locally and does not need this.
When the portal enables POST /api/academy/fmse/evaluate (hidden tests, signed
results), this function sends the same submission contract there. Until then it
explains that remote evaluation is not available and returns None — labs must
never depend on it.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional

from . import COURSE_ID, __version__

DEFAULT_ENDPOINT = "https://agentic-ai.es/api/academy/fmse/evaluate"


def submit_remote(lab_id: str, submission: Any, portal_token: Optional[str] = None, endpoint: Optional[str] = None):
    """Submit a JSON-serialisable submission for remote evaluation (optional, Phase 2).

    Returns the evaluator's JSON response, or None when remote evaluation is not
    available. The portal token, if any, travels in a header and is never printed.
    """
    url = endpoint or os.environ.get("FMSE_EVALUATOR_URL") or DEFAULT_ENDPOINT
    try:
        body = json.dumps({"course": COURSE_ID, "lab": str(lab_id), "submission": submission, "client_version": __version__}).encode()
    except TypeError:
        print("submit_remote: the submission must be JSON-serialisable (send artifacts/results, not functions).")
        return None
    headers = {"Content-Type": "application/json"}
    if portal_token:
        headers["Authorization"] = f"Bearer {portal_token}"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as err:
        if err.code in (404, 501):
            print("Remote evaluation is not available yet (Phase 2). Your public validation result is your evidence.")
        else:
            print(f"Remote evaluation failed with HTTP {err.code}. Public validation remains valid for the course.")
        return None
    except (urllib.error.URLError, TimeoutError, OSError):
        print("Remote evaluator unreachable. Public validation remains valid for the course.")
        return None
