#!/usr/bin/env python3
"""Build labs/*.ipynb from labsrc/*.lab and write manifest.json.

Lab sources are plain text so they review well in pull requests:

    %%md
    # FMSE Lab 00 - Task Framing Laboratory
    %%code
    print("hello")
    %%setup          <- replaced by the standard idempotent labkit bootstrap

Every notebook must contain the canonical section headings, in order (course
specification, "Canonical Colab Notebook Structure"); the build fails otherwise.

    python3 tools/build_notebooks.py           # build
    python3 tools/build_notebooks.py --check   # fail if any output is stale
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "labsrc"

CANONICAL_SECTIONS = [
    "## 0. Mission and competency target",
    "## 1. Requirements and acceptance criteria",
    "## 2. Environment setup",
    "## 3. Secrets check",
    "## 4. Guided experiment",
    "## 5. Predict before you run",
    "## 6. Challenge",
    "## 7. Public validation",
    "## 8. Robustness / adversarial probes",
    "## 9. Engineering reflection",
    "## 10. Export artifact / completion result",
]

# Published location of this folder; the bootstrap downloads the labkit from the
# portal mirror first and GitHub second. Keep in step with content/fmse/course.yaml.
PORTAL_MIRROR = "https://agentic-ai.es/academy/fmse/labs"
GITHUB_RAW = "https://raw.githubusercontent.com/farithjhg/fmse-course-labs/main"


def labkit_version() -> str:
    text = (ROOT / "fmse_labkit" / "__init__.py").read_text()
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def setup_code(lab_id: str) -> str:
    return f'''# Idempotent: safe to re-run, and it never prints secrets.
LAB_ID = "{lab_id}"
LABKIT_VERSION = "{labkit_version()}"
LABKIT_SOURCES = [
    "{PORTAL_MIRROR}",  # agentic-ai.es mirror
    "{GITHUB_RAW}",  # GitHub (public repositories only)
]
import hashlib, json, os, pathlib, sys, urllib.request


def _fmse_bootstrap():
    """Make fmse_labkit importable: installed copy, local checkout, cached download, or verified download."""
    try:
        import fmse_labkit
        if fmse_labkit.__version__ == LABKIT_VERSION:
            return "fmse_labkit already loaded"
    except ImportError:
        pass
    here = pathlib.Path.cwd().resolve()
    for folder in [here, *here.parents]:
        if (folder / "fmse_labkit" / "__init__.py").exists():
            sys.path.insert(0, str(folder))
            return f"using the labkit in {{folder}}"
    target = pathlib.Path("fmse_labkit_dist").resolve()
    marker = target / f".labkit-{{LABKIT_VERSION}}"
    if marker.exists():
        sys.path.insert(0, str(target))
        return "using the previously downloaded labkit"
    problems = []
    for base in [os.environ.get("FMSE_LABKIT_URL")] + LABKIT_SOURCES:
        if not base:
            continue
        base = base.rstrip("/")
        try:
            manifest = json.loads(urllib.request.urlopen(base + "/manifest.json", timeout=20).read())
            if manifest.get("labkit_version") != LABKIT_VERSION:
                raise RuntimeError(f"mirror serves labkit {{manifest.get('labkit_version')}}")
            for entry in manifest["files"]:
                if not entry["path"].startswith("fmse_labkit/"):
                    continue
                data = urllib.request.urlopen(f"{{base}}/{{entry['path']}}", timeout=20).read()
                if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                    raise RuntimeError(f"integrity check failed for {{entry['path']}}")
                dest = target / entry["path"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
            marker.write_text("ok")
            sys.path.insert(0, str(target))
            return f"downloaded and verified the labkit from {{base}}"
        except Exception as exc:  # try the next source
            problems.append(f"{{base}} ({{type(exc).__name__}})")
    raise RuntimeError(
        "Could not load fmse_labkit from: " + "; ".join(problems) + ". "
        "Recovery: download the labs folder from agentic-ai.es/academy/fmse/resources, upload the "
        "fmse_labkit folder next to this notebook (Files panel), and re-run this cell."
    )


print(_fmse_bootstrap())
import fmse_labkit as fmse

print(f"fmse_labkit {{fmse.__version__}} ready for {{LAB_ID}} ({{fmse.lab_spec(LAB_ID).title}})")
'''


def parse_source(text: str, lab_id: str):
    cells = []
    kind, buf = None, []

    def flush():
        if kind is None:
            return
        body = "\n".join(buf).strip("\n")
        if kind == "setup":
            cells.append(("code", setup_code(lab_id).rstrip("\n")))
        elif body:
            cells.append((kind, body))

    for line in text.splitlines():
        m = re.match(r"^%%(md|code|setup)\s*$", line)
        if m:
            flush()
            kind, buf = {"md": "markdown", "code": "code", "setup": "setup"}[m.group(1)], []
        else:
            buf.append(line)
    flush()
    return cells


def to_notebook(cells, title: str) -> dict:
    nb_cells = []
    for i, (kind, body) in enumerate(cells):
        lines = body.split("\n")
        source = [ln + "\n" for ln in lines[:-1]] + [lines[-1]]
        cell = {"cell_type": kind, "id": f"cell-{i:02d}", "metadata": {}, "source": source}
        if kind == "code":
            cell.update({"execution_count": None, "outputs": []})
        nb_cells.append(cell)
    return {
        "cells": nb_cells,
        "metadata": {
            "colab": {"name": title, "provenance": [], "toc_visible": True},
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def check_structure(cells, name: str) -> list:
    problems = []
    headings = [ln.strip() for kind, body in cells if kind == "markdown" for ln in body.splitlines() if ln.startswith("## ")]
    position = -1
    for section in CANONICAL_SECTIONS:
        idx = next((i for i, h in enumerate(headings) if h.startswith(section)), None)
        if idx is None:
            problems.append(f"{name}: missing section '{section}'")
        elif idx < position:
            problems.append(f"{name}: section '{section}' is out of order")
        else:
            position = idx
    first = cells[0][1].splitlines()[0] if cells else ""
    if not re.match(r"^# FMSE (Lab \d{2}|Capstone) - .+", first):
        problems.append(f"{name}: first line must be '# FMSE Lab NN - <Title>'")
    if not any(kind == "code" and "_fmse_bootstrap" in body for kind, body in cells):
        problems.append(f"{name}: missing %%setup cell")
    for kind, body in cells:
        if kind == "code" and re.search(r"(sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_\-]{30,})", body):
            problems.append(f"{name}: code cell contains a credential-shaped string")
    return problems


def build(check_only: bool = False) -> int:
    problems, stale = [], []
    outputs = {}
    for src in sorted(SRC.glob("*.lab")):
        header = src.read_text(encoding="utf-8")
        meta = re.search(r"^#!\s*lab_id:\s*(\S+)\s+output:\s*(\S+)\s*$", header, re.M)
        if not meta:
            problems.append(f"{src.name}: first line must be '#! lab_id: <id> output: <path.ipynb>'")
            continue
        lab_id, output = meta.group(1), meta.group(2)
        body = "\n".join(ln for ln in header.splitlines() if not ln.startswith("#!"))
        cells = parse_source(body, lab_id)
        problems += check_structure(cells, src.name)
        title = cells[0][1].splitlines()[0].lstrip("# ").strip() if cells else src.stem
        outputs[ROOT / output] = json.dumps(to_notebook(cells, title), indent=1, ensure_ascii=False) + "\n"

    for path, content in outputs.items():
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            stale.append(str(path.relative_to(ROOT)))
            if not check_only:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

    manifest = manifest_json()
    mpath = ROOT / "manifest.json"
    if not mpath.exists() or mpath.read_text() != manifest:
        stale.append("manifest.json")
        if not check_only:
            mpath.write_text(manifest)

    for p in problems:
        print("ERROR", p)
    if check_only and stale:
        print("Stale build outputs (run python3 tools/build_notebooks.py):", ", ".join(stale))
        return 1
    print(f"{len(outputs)} notebook(s) {'checked' if check_only else 'built'}; {len(problems)} problem(s).")
    return 1 if problems else 0


def manifest_json() -> str:
    """The same file set and hashes the portal mirror publishes (content-compiler.ts listMirrorFiles)."""
    patterns = [r"^fmse_labkit/.+\.(py|json)$", r"^datasets/public/.+\.(json|csv|md|txt|yaml)$", r"^labs/.+\.ipynb$",
                r"^capstone/.+\.(ipynb|md|yaml|csv|json)$", r"^requirements\.txt$", r"^README\.md$"]
    files = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or any(part.startswith(".") for part in path.relative_to(ROOT).parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        if any(re.match(p, rel) for p in patterns):
            files.append({"path": rel, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return json.dumps({"labkit_version": labkit_version(), "files": files}, indent=2) + "\n"


if __name__ == "__main__":
    sys.exit(build(check_only="--check" in sys.argv))
