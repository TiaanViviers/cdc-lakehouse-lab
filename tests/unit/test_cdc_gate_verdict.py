"""Exercise the paired subgate with exports from the parity writer."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory
import unittest

from scripts.cdc.parity import COLUMNS, Capture, verify_checkpoint, write_evidence
from tests.fixture_oracle import load_expectations


VERIFIER = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                              "integration/cdc-gate/verdict.py"))


class GateVerdictTests(unittest.TestCase):
    def write_pair(self, root, *, retention_passes):
        pair = root / "EXP-020" / "pair-test"
        expected = load_expectations()
        for n in ("first", "second"):
            run = pair / n
            for step in VERIFIER["CHECKPOINTS"]:
                capture = Capture({table: expected[step][table] for table in COLUMNS}, "test")
                result = verify_checkpoint("gate", step, lambda _: capture, lambda _: capture)
                write_evidence(run / step, result)
            (run / "gate.json").write_text(json.dumps(dict(
                project=f"project-{n}", bridge=f"bridge-{n}", source_system=f"source-{n}",
                consumer_system=f"consumer-{n}", revision="same-revision", images=["same-image"],
                retention=dict(progress_observed=retention_passes, persistent_growth=not retention_passes),
            )))
            (run / "teardown.ok").touch()
        return pair

    def assert_subgate(self, pair, *, passes):
        expected = "pass" if passes else "fail"
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(VERIFIER["verdict"](pair), 0 if passes else 1)
        summary = json.loads((pair / "verdict.json").read_text())
        self.assertEqual(summary["scope"], "paired-subgate")
        self.assertEqual(summary["verdict"], expected)
        self.assertIs(summary["requires_m2_review"], True)
        self.assertEqual(len(summary["hashes"]), 12)
        self.assertEqual(stdout.getvalue().splitlines(), [
            f"Paired CDC subgate: {expected}",
            "Full M2 decision requires review of all mandatory evidence, including controlled COPY overlap.",
        ])

    def test_exact_exports_preserve_negative_retention_result(self):
        with TemporaryDirectory() as directory:
            pair = self.write_pair(Path(directory), retention_passes=False)
            self.assert_subgate(pair, passes=False)

    def test_positive_pair_never_emits_full_m2_verdict(self):
        # The guest writes COPY evidence beside EXP-020, under EXP-017.
        # A positive pair remains scoped for each possible COPY outcome.
        copy_hold = dict(checkpoint="copy-window", event="same_copy_blocked_after_commit")
        exact_checks = [
            dict(checkpoint=checkpoint, event="exact_target")
            for checkpoint in ("copy-window", "item-102-update", "item-102-delete")
        ]
        for copy_outcome, copy_events in (
            ("missing", []),
            ("failed", [copy_hold]),
            ("inconclusive", [dict(checkpoint="copy-window", event="inconclusive_copy_window_unhit")]),
            ("passed", [copy_hold, *exact_checks]),
        ):
            with self.subTest(copy_outcome=copy_outcome), TemporaryDirectory() as directory:
                root = Path(directory)
                pair = self.write_pair(root, retention_passes=True)
                if copy_events:
                    run = root / "EXP-017" / "copy-run"
                    run.mkdir(parents=True)
                    (run / "run.txt").write_text(
                        f"experiment_exit={0 if copy_outcome == 'passed' else 1} cleanup_exit=0\n"
                    )
                    (run / "timeline.jsonl").write_text("".join(json.dumps(event) + "\n"
                                                              for event in copy_events))

                self.assert_subgate(pair, passes=True)

    def test_positive_retention_cannot_mask_inexact_target(self):
        with TemporaryDirectory() as directory:
            pair = self.write_pair(Path(directory), retention_passes=True)
            target = pair / "second/S03/target.snapshot.json"
            snapshot = json.loads(target.read_text())
            snapshot["rows"]["order_items"][0]["quantity"] += 1
            target.write_text(json.dumps(snapshot))
            with self.assertRaisesRegex(RuntimeError, "S03 target is not independently exact"):
                VERIFIER["verdict"](pair)
            self.assertFalse((pair / "verdict.json").exists())
