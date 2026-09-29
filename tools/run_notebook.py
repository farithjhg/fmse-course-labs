#!/usr/bin/env python3
"""Execute a lab notebook's code cells in order, without Jupyter.

Used by the test suites (no nbclient/ipykernel dependency). Shell (!) and magic
(%) lines are skipped. `overrides` replaces top-level assignments by name — the
tests use it to play the learner (fill predictions, worksheets, submissions)
without editing the notebook.

    python3 tools/run_notebook.py labs/lab-00-task-framing.ipynb
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]


def _strip_ipython(source: str) -> str:
    return "\n".join(("pass  # " + ln) if ln.lstrip().startswith(("!", "%")) else ln for ln in source.splitlines())


def run_notebook(path: Path, overrides: Optional[Dict[str, Any]] = None, workdir: Optional[Path] = None, quiet: bool = True) -> Dict[str, Any]:
    nb = json.loads(Path(path).read_text(encoding="utf-8"))
    overrides = overrides or {}
    ns: Dict[str, Any] = {"__name__": "__main__"}
    ns.update(overrides)
    workdir = workdir or Path(tempfile.mkdtemp(prefix="fmse-nb-"))
    old_cwd = os.getcwd()
    os.chdir(workdir)
    # The bootstrap looks for a local checkout from the cwd upwards; point it at this repo.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    out = io.StringIO()
    try:
        for i, cell in enumerate(nb["cells"]):
            if cell["cell_type"] != "code":
                continue
            tree = ast.parse(_strip_ipython("".join(cell["source"])))
            tree.body = [
                node for node in tree.body
                if not (isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) and t.id in overrides for t in node.targets))
                and not (isinstance(node, ast.FunctionDef) and node.name in overrides)
            ]
            code = compile(tree, f"{Path(path).name}[cell {i}]", "exec")
            with contextlib.redirect_stdout(out) if quiet else contextlib.nullcontext():
                exec(code, ns)  # noqa: S102 - executing our own notebooks in tests
    finally:
        os.chdir(old_cwd)
    ns["__stdout__"] = out.getvalue()
    ns["__workdir__"] = workdir
    return ns


if __name__ == "__main__":
    result = run_notebook(Path(sys.argv[1]), quiet=False)
    print("\nOK - executed", sys.argv[1])
