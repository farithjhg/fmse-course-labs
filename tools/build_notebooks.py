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

Spanish notebooks are built from labsrc/es/*.lab into *.es.ipynb. They must be the
English notebook translated: the same cells, and code that differs only in its
string literals and comments (identifiers and data keys stay English, so the
tests and the validators treat both alike). The build checks that too.

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

CANONICAL_SECTIONS_ES = [
    "## 0. Misión y competencia objetivo",
    "## 1. Requisitos y criterios de aceptación",
    "## 2. Preparación del entorno",
    "## 3. Comprobación de secretos",
    "## 4. Experimento guiado",
    "## 5. Predice antes de ejecutar",
    "## 6. Reto",
    "## 7. Validación pública",
    "## 8. Robustez / pruebas adversariales",
    "## 9. Reflexión de ingeniería",
    "## 10. Exportar el artefacto / resultado de finalización",
]

LANGUAGES = {
    "en": {"src": SRC, "sections": CANONICAL_SECTIONS, "title": r"^# FMSE (Lab \d{2}|Capstone) - .+", "suffix": ".ipynb"},
    "es": {"src": SRC / "es", "sections": CANONICAL_SECTIONS_ES, "title": r"^# FMSE (Laboratorio \d{2}|Proyecto final) - .+", "suffix": ".es.ipynb"},
}

# Setup-cell messages, printed before the labkit (and its translations) is importable.
SETUP_TEXT = {
    "en": {
        "idempotent": "# Idempotent: safe to re-run, and it never prints secrets.",
        "loaded": "fmse_labkit already loaded",
        "local": "using the labkit in {folder}",
        "cached": "using the previously downloaded labkit",
        "downloaded": "downloaded and verified the labkit from {base}",
        "failed": "Could not load fmse_labkit from: ",
        "recovery": ("Recovery: download the labs folder from agentic-ai.es/academy/fmse/resources, upload the "
                     "fmse_labkit folder next to this notebook (Files panel), and re-run this cell."),
        "ready": "fmse_labkit {version} ready for {lab} ({title})",
    },
    "es": {
        "idempotent": "# Idempotente: se puede volver a ejecutar y nunca imprime secretos.",
        "loaded": "fmse_labkit ya estaba cargado",
        "local": "usando el labkit de {folder}",
        "cached": "usando el labkit descargado anteriormente",
        "downloaded": "labkit descargado y verificado desde {base}",
        "failed": "No se pudo cargar fmse_labkit desde: ",
        "recovery": ("Solución: descarga la carpeta de laboratorios desde agentic-ai.es/academy/fmse/resources, sube la "
                     "carpeta fmse_labkit junto a este notebook (panel Archivos) y vuelve a ejecutar esta celda."),
        "ready": "fmse_labkit {version} listo para {lab} ({title})",
    },
}

# Published location of this folder; the bootstrap downloads the labkit from the
# portal mirror first and GitHub second. Keep in step with content/fmse/course.yaml.
PORTAL_MIRROR = "https://agentic-ai.es/academy/fmse/labs"
GITHUB_RAW = "https://raw.githubusercontent.com/farithjhg/fmse-course-labs/main"


def labkit_version() -> str:
    text = (ROOT / "fmse_labkit" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def setup_code(lab_id: str, lang: str = "en") -> str:
    m = SETUP_TEXT[lang]
    fmt = lambda key, **names: m[key].format(**{k: "{" + v + "}" for k, v in names.items()})  # noqa: E731
    return f'''{m["idempotent"]}
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
            return "{m['loaded']}"
    except ImportError:
        pass
    here = pathlib.Path.cwd().resolve()
    for folder in [here, *here.parents]:
        if (folder / "fmse_labkit" / "__init__.py").exists():
            sys.path.insert(0, str(folder))
            return f"{fmt('local', folder='folder')}"
    target = pathlib.Path("fmse_labkit_dist").resolve()
    marker = target / f".labkit-{{LABKIT_VERSION}}"
    if marker.exists():
        sys.path.insert(0, str(target))
        return "{m['cached']}"
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
            return f"{fmt('downloaded', base='base')}"
        except Exception as exc:  # try the next source
            problems.append(f"{{base}} ({{type(exc).__name__}})")
    raise RuntimeError(
        "{m['failed']}" + "; ".join(problems) + ". "
        "{m['recovery']}"
    )


print(_fmse_bootstrap())
import fmse_labkit as fmse

fmse.set_language("{lang}")
print(f"{fmt('ready', version='fmse.__version__', lab='LAB_ID', title='fmse.title(fmse.lab_spec(LAB_ID))')}")
'''


def parse_source(text: str, lab_id: str, lang: str = "en"):
    cells = []
    kind, buf = None, []

    def flush():
        if kind is None:
            return
        body = "\n".join(buf).strip("\n")
        if kind == "setup":
            cells.append(("code", setup_code(lab_id, lang).rstrip("\n")))
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


def check_structure(cells, name: str, lang: str = "en") -> list:
    problems = []
    CANONICAL_SECTIONS = LANGUAGES[lang]["sections"]
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
    if not re.match(LANGUAGES[lang]["title"], first):
        problems.append(f"{name}: first line must match {LANGUAGES[lang]['title']}")
    if not any(kind == "code" and "_fmse_bootstrap" in body for kind, body in cells):
        problems.append(f"{name}: missing %%setup cell")
    for kind, body in cells:
        if kind == "code" and re.search(r"(sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_\-]{30,})", body):
            problems.append(f"{name}: code cell contains a credential-shaped string")
    return problems


def code_shape(cells) -> list:
    """Each code cell's AST with string literals blanked: what a translation must leave unchanged."""
    import ast

    class Blank(ast.NodeTransformer):
        def visit_Constant(self, node):
            return ast.Constant("") if isinstance(node.value, str) else node

        def visit_JoinedStr(self, node):
            return ast.Constant("")

    shapes = []
    for kind, body in cells:
        if kind == "code":
            source = "\n".join(("pass" if ln.lstrip().startswith(("!", "%")) else ln) for ln in body.splitlines())
            shapes.append(ast.dump(Blank().visit(ast.parse(source))))
    return shapes


def build(check_only: bool = False) -> int:
    problems, stale = [], []
    outputs = {}
    english = {}
    for lang, conf in LANGUAGES.items():
        for src in sorted(conf["src"].glob("*.lab")):
            header = src.read_text(encoding="utf-8")
            name = src.relative_to(SRC).as_posix()
            meta = re.search(r"^#!\s*lab_id:\s*(\S+)\s+output:\s*(\S+)\s*$", header, re.M)
            if not meta:
                problems.append(f"{name}: first line must be '#! lab_id: <id> output: <path.ipynb>'")
                continue
            lab_id, output = meta.group(1), meta.group(2)
            if not output.endswith(conf["suffix"]) or (lang == "en" and output.endswith(".es.ipynb")):
                problems.append(f"{name}: output must end with {conf['suffix']}")
                continue
            body = "\n".join(ln for ln in header.splitlines() if not ln.startswith("#!"))
            cells = parse_source(body, lab_id, lang)
            problems += check_structure(cells, name, lang)
            if lang == "en":
                english[output] = (lab_id, cells)
            else:
                source = english.get(output.replace(conf["suffix"], ".ipynb"))
                if source is None or source[0] != lab_id:
                    problems.append(f"{name}: no English notebook with lab id {lab_id} for {output}")
                elif [k for k, _ in source[1]] != [k for k, _ in cells]:
                    problems.append(f"{name}: cells differ from the English notebook (same markdown/code sequence required)")
                elif code_shape(source[1]) != code_shape(cells):
                    diff = next(i for i, (a, b) in enumerate(zip(code_shape(source[1]), code_shape(cells))) if a != b)
                    problems.append(f"{name}: code cell {diff} differs from the English notebook beyond strings and comments")
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
    if not mpath.exists() or mpath.read_text(encoding="utf-8") != manifest:
        stale.append("manifest.json")
        if not check_only:
            mpath.write_text(manifest, encoding="utf-8", newline="\n")

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
    # Sort by the posix path, case-sensitively: Path ordering is case-insensitive on Windows,
    # which would put README.md after capstone/ and change the manifest by platform.
    for path in sorted(ROOT.rglob("*"), key=lambda p: p.relative_to(ROOT).as_posix()):
        if not path.is_file() or "__pycache__" in path.parts or any(part.startswith(".") for part in path.relative_to(ROOT).parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        if any(re.match(p, rel) for p in patterns):
            # The mirror serves the repository's bytes, which are LF; a Windows checkout with
            # core.autocrlf=true holds CRLF copies, so normalise before hashing or the manifest
            # differs by platform for identical content.
            files.append({"path": rel, "sha256": hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()})
    return json.dumps({"labkit_version": labkit_version(), "files": files}, indent=2) + "\n"


if __name__ == "__main__":
    sys.exit(build(check_only="--check" in sys.argv))
