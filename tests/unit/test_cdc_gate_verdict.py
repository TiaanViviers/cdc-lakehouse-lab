"""Keep the Phase 2 pair verifier compatible with the parity evidence writer."""

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory
import unittest

from scripts.cdc.parity import COLUMNS, Capture, verify_checkpoint, write_evidence
from tests.fixture_oracle import load_expectations


VERIFIER = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                              "integration/cdc-gate/verdict.py"))


class GateVerdictTests(unittest.TestCase):
    def test_exact_checkpoint_exports_preserve_negative_retention_verdict(self):
        expected = load_expectations()
        with TemporaryDirectory() as directory:
            pair = Path(directory)
            for n in ("first", "second"):
                run = pair / n
                for step in VERIFIER["CHECKPOINTS"]:
                    capture = Capture({table: expected[step][table] for table in COLUMNS}, "test")
                    result = verify_checkpoint("gate", step, lambda _: capture, lambda _: capture)
                    write_evidence(run / step, result)
                (run / "gate.json").write_text(json.dumps(dict(
                    project=f"project-{n}", bridge=f"bridge-{n}", source_system=f"source-{n}",
                    consumer_system=f"consumer-{n}", revision="same-revision", images=["same-image"],
                    retention=dict(progress_observed=False, persistent_growth=True),
                )))
                (run / "teardown.ok").touch()

            with redirect_stdout(io.StringIO()):
                self.assertEqual(VERIFIER["verdict"](pair), 1)
            summary = json.loads((pair / "verdict.json").read_text())
            self.assertEqual(summary["verdict"], "M2 unmet")
            self.assertEqual(len(summary["hashes"]), 12)

            target = pair / "second/S03/target.snapshot.json"
            snapshot = json.loads(target.read_text())
            snapshot["rows"]["order_items"][0]["quantity"] += 1
            target.write_text(json.dumps(snapshot))
            with self.assertRaisesRegex(RuntimeError, "S03 target is not independently exact"):
                VERIFIER["verdict"](pair)
