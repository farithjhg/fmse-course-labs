"""FMSE 2026 lab kit.

The stable notebook API from the course specification:

    fmse.check_public(lab_id, submission)
    fmse.export_artifact(lab_id, artifact)
    fmse.make_completion_record(lab_id, score, evidence)
    fmse.submit_remote(lab_id, submission, portal_token=None)   # Phase 2, optional

Public validators are intentionally visible: they teach how the system is
evaluated. They report which requirement failed and why, never the expected
implementation. Standard library only, so every lab runs on a fresh Colab
runtime without installing anything.
"""

__version__ = "1.1.1"
COURSE_ID = "fmse-2026"
COURSE_VERSION = "1.0"

from .i18n import get_language, set_language, t  # noqa: E402
from .core import Check, CheckResult, LAB_SPECS, check_public, lab_spec, probe, title  # noqa: E402
from .records import (  # noqa: E402
    GuidedLog,
    export_artifact,
    make_completion_record,
    save_record,
    show_record,
)
from .remote import submit_remote  # noqa: E402
from .secrets import get_secret, redact, secrets_check  # noqa: E402
from . import model, schema, data  # noqa: E402

# Importing the lab modules registers their validators.
from .labs import register_all as _register_all  # noqa: E402

_register_all()
from . import requirements_es  # noqa: E402,F401 - Spanish requirement texts and hints

__all__ = [
    "__version__",
    "COURSE_ID",
    "COURSE_VERSION",
    "Check",
    "CheckResult",
    "LAB_SPECS",
    "GuidedLog",
    "check_public",
    "data",
    "export_artifact",
    "get_language",
    "get_secret",
    "lab_spec",
    "make_completion_record",
    "model",
    "probe",
    "redact",
    "save_record",
    "schema",
    "secrets_check",
    "set_language",
    "show_record",
    "submit_remote",
    "t",
    "title",
]
