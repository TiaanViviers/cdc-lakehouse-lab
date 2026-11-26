"""Replay redacted EXP-011 row renderings through the one-table adapter."""

import csv
import io
import re
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.cdc.parity import normalize_rows
from scripts.cdc.parity.psql import read_projections
from tests.fixture_oracle import compare_rows

EVIDENCE = (
    Path(__file__).resolve().parents[2]
    / "docs/experiments/evidence/EXP-011-guest-observations.txt"
)
COLUMNS = ("id", "value")
EXPECTED = {
    "initial": [{"id": 1, "value": "seed"}],
    "insert": [{"id": 1, "value": "seed"}, {"id": 2, "value": "inserted"}],
    "update": [{"id": 1, "value": "updated"}, {"id": 2, "value": "inserted"}],
    "delete": [{"id": 1, "value": "updated"}],
}
STALE_DIFFS = {
    "initial": ["items: missing key id=1"],
    "insert": ["items: missing key id=2"],
    "update": ["items: unequal id=1 value: expected 'updated', got 'seed'"],
    "delete": ["items: extra key id=2"],
}


def read_rendering(rendering, table):
    # EXP-011 used unaligned psql with pipe separators. Its simple fixture
    # values are losslessly re-framed as CSV for the adapter's psql boundary.
    output = io.StringIO(newline="")
    output.write(",,\n")
    writer = csv.writer(output)
    writer.writerow(COLUMNS)
    writer.writerows(line.split("|") for line in rendering.splitlines())
    with patch("scripts.cdc.parity.psql.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 0, stdout=output.getvalue())
        capture = read_projections(["psql"], {"items": (table, COLUMNS, "id")}, 1)
    return normalize_rows("items", capture.rows["items"], COLUMNS, "id", {"id"})


class Exp011ReplayTest(unittest.TestCase):
    def test_observed_source_and_target_renderings_at_all_four_hold_points(self):
        observations = EVIDENCE.read_text(encoding="utf-8")
        for phase, expected in EXPECTED.items():
            with self.subTest(phase=phase):
                section = observations.split(f"=== {phase} ===\n", 1)[1].split("\n===", 1)[0]
                source = re.search(r"Source rows\n(.*?)Target polling\n", section, re.S)[1]
                target = re.search(r"first passing observation[^\n]*\n(.*?)Source state\n",
                                   section, re.S)[1]
                stale = re.search(r"last failing observation\nattempt=[^\n]*\n(.*?)"
                                  r"first passing observation", section, re.S)[1]
                self.assertEqual(compare_rows(
                    "items", "id", expected, read_rendering(source, ("probe", "items")),
                ), [])
                self.assertEqual(compare_rows(
                    "items", "id", expected, read_rendering(target, ("bronze", "items")),
                ), [])
                self.assertEqual(compare_rows(
                    "items", "id", expected, read_rendering(stale, ("bronze", "items")),
                ), STALE_DIFFS[phase])
