"""Public tests for the lab kit and notebooks (safe to publish: no solutions here).

    python3 -m unittest discover -s fmse-course-labs/tests -t fmse-course-labs
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import fmse_labkit as fmse  # noqa: E402
from build_notebooks import CANONICAL_SECTIONS  # noqa: E402
from run_notebook import run_notebook  # noqa: E402

# Registry key -> spec. Capstone milestones share lab_id "capstone" and are addressed by their key.
IMPLEMENTED = [(k, s) for k, s in fmse.LAB_SPECS.items() if s.validator is not None]
RECORD_KEYS = {"schema", "course", "course_version", "lab_id", "validator_id", "module_id", "labkit_version", "created_at",
               "passed", "score", "public_gate", "checks", "guided", "artifact", "evidence", "probes", "source", "signature"}


class NotebookStructure(unittest.TestCase):
    def test_build_outputs_are_current(self):
        proc = subprocess.run([sys.executable, str(ROOT / "tools" / "build_notebooks.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_full_roadmap_registered(self):
        labs = {s.lab_id for s in fmse.LAB_SPECS.values()}
        self.assertEqual(labs, {f"lab-{n:02d}" for n in range(16)} | {"capstone"})
        self.assertTrue(all(s.validator for s in fmse.LAB_SPECS.values()), "every lab and milestone has a public validator")

    def test_capstone_datasets_match_labkit(self):
        from fmse_labkit.labs import capstone
        for name, text in (("bank_export.csv", capstone.BANK_CSV), ("ledger_entries.csv", capstone.LEDGER_CSV), ("vendor_master.csv", capstone.VENDORS_CSV)):
            self.assertEqual((ROOT / "capstone" / "datasets" / name).read_text(), text, name)

    def test_every_registered_lab_has_its_notebook(self):
        for spec in fmse.LAB_SPECS.values():
            with self.subTest(lab=spec.lab_id):
                self.assertTrue((ROOT / spec.notebook).exists(), spec.notebook)

    def test_canonical_sections_in_order(self):
        for spec in fmse.LAB_SPECS.values():
            nb = json.loads((ROOT / spec.notebook).read_text())
            md = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "markdown")
            positions = [md.find("\n" + s) for s in CANONICAL_SECTIONS]
            with self.subTest(lab=spec.lab_id):
                self.assertNotIn(-1, positions)
                self.assertEqual(positions, sorted(positions))
                self.assertTrue(md.startswith(f"# FMSE "), "title line")

    def test_notebooks_have_no_outputs_or_secrets(self):
        for path in (ROOT / "labs").glob("*.ipynb"):
            nb = json.loads(path.read_text())
            for cell in nb["cells"]:
                if cell["cell_type"] == "code":
                    self.assertEqual(cell["outputs"], [], f"{path.name} has committed outputs")
            self.assertEqual(fmse.secrets.contains_secret(path.read_text()), [], path.name)


class StarterNotebooksFailSafely(unittest.TestCase):
    """Run every notebook untouched: it must execute end to end and export a NOT PASSED record."""

    def test_run_starter_notebooks(self):
        for _key, spec in IMPLEMENTED:
            if spec.milestone_id:
                continue  # milestones live in the capstone notebook, checked via its package record
            with self.subTest(lab=spec.lab_id):
                ns = run_notebook(ROOT / spec.notebook)
                record = json.loads((ns["__workdir__"] / "fmse_artifacts" / spec.lab_id / "completion-record.json").read_text())
                self.assertEqual(RECORD_KEYS, set(record))
                self.assertEqual(record["lab_id"], spec.lab_id)
                self.assertEqual(record["module_id"], spec.module_id)
                self.assertFalse(record["passed"])
                self.assertFalse(record["guided"]["completed"])
                self.assertIn("BEGIN FMSE COMPLETION RECORD", ns["__stdout__"])


class ValidatorsFailSafely(unittest.TestCase):
    GARBAGE = [None, 42, "", "   ", {}, [], "not yaml: [", {"unexpected": object()}]

    def test_garbage_never_crashes_and_never_passes(self):
        for key, spec in IMPLEMENTED:
            for bad in self.GARBAGE:
                with self.subTest(lab=key, submission=repr(bad)[:30]):
                    result = fmse.check_public(key, bad)
                    self.assertFalse(result.passed)
                    self.assertEqual([c.id for c in result.checks], list(spec.requirements))
                    for c in result.checks:
                        self.assertIn(c.status, ("pass", "fail", "warn"))
                        if c.status == "fail":
                            self.assertTrue(c.hint, f"{c.id} failure without a hint")

    def test_result_contract(self):
        r = fmse.check_public("lab-00", "")
        d = r.to_dict()
        self.assertEqual(set(d), {"lab_id", "passed", "score", "public_gate", "checks", "failed_requirements"})
        self.assertEqual(set(d["checks"][0]), {"id", "status", "dimension", "message", "hint", "critical"})

    def test_lab_id_aliases(self):
        self.assertIs(fmse.lab_spec("lab-01"), fmse.lab_spec("01"))
        self.assertIs(fmse.lab_spec("01-typed-model-call"), fmse.lab_spec("lab-01"))
        with self.assertRaises(KeyError):
            fmse.lab_spec("lab-99")


class SecretsNeverLeak(unittest.TestCase):
    # Built at runtime so repository secret scanners do not flag this fake key.
    KEY = "sk-" + "proj-" + "THISISAFAKEKEYFORTESTS1234567890"

    def test_redaction(self):
        self.assertNotIn(self.KEY, fmse.redact(f"key={self.KEY}"))
        self.assertNotIn("AIzaSyA" + "x" * 33, fmse.redact("AIzaSyA" + "x" * 33))

    def test_export_redacts(self):
        with tempfile.TemporaryDirectory() as d:
            with contextlib.redirect_stdout(io.StringIO()):
                art = fmse.export_artifact("lab-00", f"## Intent\nuse {self.KEY}", out_dir=d)
            self.assertTrue(art["redacted"])
            self.assertNotIn(self.KEY, art["content"])
            self.assertNotIn(self.KEY, Path(art["reference"]).read_text())

    def test_secrets_check_prints_presence_only(self):
        os.environ["OPENAI_API_KEY"] = self.KEY
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                status = fmse.secrets_check(["OPENAI_API_KEY"])
            self.assertTrue(status["OPENAI_API_KEY"])
            self.assertNotIn(self.KEY, buf.getvalue())
        finally:
            del os.environ["OPENAI_API_KEY"]

    def test_record_redacts_evidence(self):
        with contextlib.redirect_stdout(io.StringIO()):
            rec = fmse.make_completion_record("lab-00", 0.5, {"note": f"my key is {self.KEY}"})
        self.assertNotIn(self.KEY, json.dumps(rec))

    def test_submit_remote_is_optional(self):
        with contextlib.redirect_stdout(io.StringIO()):
            out = fmse.submit_remote("lab-00", {"x": 1}, endpoint="http://127.0.0.1:9/unreachable")
        self.assertIsNone(out)


class LargeArtifacts(unittest.TestCase):
    def test_large_artifact_is_referenced_not_embedded(self):
        with tempfile.TemporaryDirectory() as d:
            with contextlib.redirect_stdout(io.StringIO()):
                art = fmse.export_artifact("lab-00", "## Intent\n" + "x" * 30000, out_dir=d)
                rec = fmse.make_completion_record("lab-00", 1.0, {}, artifact=art)
            self.assertIsNone(art["content"])
            self.assertTrue(art["truncated"])
            self.assertLess(len(json.dumps(rec)), 64_000)


if __name__ == "__main__":
    unittest.main()
