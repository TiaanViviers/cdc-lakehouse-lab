"""Exercise parity independently of the writer, source DB and connector."""

import csv
import io
import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.cdc.parity import (
    COLUMNS,
    Capture,
    ReadError,
    ReadTimeout,
    compare,
    fixture_rows,
    normalize_rows,
    verify_checkpoint,
    write_evidence,
)
from scripts.cdc.parity.psql import SOURCE_TABLES, read_fixture, read_projections, select_rows

T0 = "2026-01-01T00:00:00Z"


def timed(minute, **fields):
    stamp = f"2026-01-01T00:{minute:02}:00Z"
    return dict(fields, created_at=stamp, updated_at=stamp)


def examples():
    """Small hand-built reader inputs describing the documented DML timeline."""
    s00 = {
        "customers": [
            timed(0, customer_id=2, code="C2", name="Bo"),
            timed(0, customer_id=1, code="C1", name="Ada"),
        ],
        "orders": [
            timed(0, order_id=10, customer_id=1, order_ref="O10", status="open"),
            timed(0, order_id=20, customer_id=2, order_ref="O20", status="paid"),
        ],
        "order_items": [
            timed(0, item_id=101, order_id=10, line_no=1, sku="A", quantity=2, unit_cents=300),
            timed(0, item_id=201, order_id=20, line_no=1, sku="B", quantity=1, unit_cents=500),
        ],
        "payments": [timed(0, payment_id=301, order_id=20, payment_ref="P301", amount_cents=500)],
    }
    s01 = deepcopy(s00)
    s01["order_items"].append(
        timed(1, item_id=102, order_id=10, line_no=2, sku="B", quantity=1, unit_cents=500)
    )
    s02 = deepcopy(s01)
    s02["order_items"][0].update(quantity=3, updated_at="2026-01-01T00:02:00Z")
    s03 = deepcopy(s02)
    s03["order_items"].pop()
    s04 = deepcopy(s03)
    s04["orders"].append(timed(4, order_id=30, customer_id=1, order_ref="O30", status="paid"))
    s04["order_items"].append(
        timed(4, item_id=301, order_id=30, line_no=1, sku="C", quantity=2, unit_cents=200)
    )
    s04["payments"].append(timed(4, payment_id=302, order_id=30, payment_ref="P302", amount_cents=400))
    s05 = deepcopy(s04)
    s05["order_items"][0].update(quantity=4, updated_at="2026-01-01T00:05:00Z")
    s05["payments"].append(timed(5, payment_id=303, order_id=10, payment_ref="P303", amount_cents=200))
    return (s00, s01, s02, s03, s04, s05, deepcopy(s05))


def reader(rows, catalog_snapshot_id=None):
    return lambda budget: Capture(rows, "offline reader", catalog_snapshot_id)


class FixtureTests(unittest.TestCase):
    def test_exact_s00_through_s06_on_both_sides(self):
        for n, raw in enumerate(examples()):
            with self.subTest(n=n):
                result = verify_checkpoint("settled", f"S{n:02}", reader(raw), reader(raw, 12))
                self.assertTrue(result.passed, result)
                self.assertEqual(result.target_attempts, 1)
                snap = result.target.snapshot
                self.assertEqual(snap.catalog_snapshot_id, 12)
                self.assertIsNone(result.source.snapshot.catalog_snapshot_id)
                self.assertEqual([row["customer_id"] for row in snap.rows["customers"]], [1, 2])

    def test_altered_rows_and_retained_delete(self):
        _, _, before_delete, exact, *_ = examples()
        missing, duplicate, wrong_value, wrong_timestamp = (deepcopy(exact) for _ in range(4))
        missing["payments"].clear()
        duplicate["orders"].append(duplicate["orders"][0])
        wrong_value["order_items"][0]["unit_cents"] = 301
        wrong_timestamp["customers"][0]["updated_at"] = "2026-01-01T00:00:00.000001Z"

        for actual, diff in (
            (missing, "payments: missing key payment_id=301"),
            (duplicate, "orders: duplicate actual key order_id=10"),
            (before_delete, "order_items: extra key item_id=102"),
            (wrong_value, "order_items: unequal item_id=101 unit_cents: expected 300, got 301"),
            (wrong_timestamp, "customers: unequal customer_id=2 updated_at: "
             "expected '2026-01-01T00:00:00Z', got '2026-01-01T00:00:00.000001Z'"),
        ):
            with self.subTest(diff=diff):
                self.assertIn(f"after-delete/S03 target: {diff}",
                              compare("after-delete", "S03", "target", fixture_rows(actual)))

    def test_report_drift_with_exact_business_rows(self):
        raw = examples()[0]
        rows = fixture_rows(raw)
        rows["report"][0]["order_count"] += 1
        self.assertEqual(compare("initial", "S00", "source", rows), (
            "initial/S00 source: report: unequal customer_id=1 order_count: expected 1, got 2",
        ))

    def test_normalizes_types_and_offsets_without_losing_precision(self):
        raw = examples()[0]
        raw["customers"][0].update(
            customer_id="2",
            created_at="2026-01-01 02:30:00+02:30",
            updated_at=datetime(2025, 12, 31, 19, tzinfo=timezone(timedelta(hours=-5))),
        )
        raw["order_items"][0]["unit_cents"] = "300"
        normalized = fixture_rows(raw)
        self.assertEqual(compare("initial", "S00", "target", normalized), ())
        self.assertIs(type(normalized["order_items"][0]["unit_cents"]), int)
        for invalid in (True, 2.0, "2.1", None):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ReadError, "invalid customer_id"):
                raw["customers"][0]["customer_id"] = invalid
                fixture_rows(raw)
        raw["customers"][0]["customer_id"] = 2
        for invalid in (T0[:-1], "2026-01-01T00:00:00.0000001Z"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ReadError, "invalid created_at"):
                raw["customers"][0]["created_at"] = invalid
                fixture_rows(raw)

    def test_overflow_consumes_only_sentinel_row(self):
        raw = examples()[0]
        row = raw["customers"][0]

        def overflow():
            yield from [row] * 33
            self.fail("read beyond the overflow sentinel")

        candidate = dict(raw, customers=overflow())
        result = verify_checkpoint("initial", "S00", reader(raw), reader(candidate))
        self.assertEqual(result.source.status, "pass")
        self.assertEqual(result.target.status, "read_error")
        self.assertEqual(result.target.diffs, ("initial/S00 target: customers: row overflow (limit 32)",))
        self.assertIsNone(result.target.snapshot)

    def test_reports_zero_for_customer_without_orders(self):
        raw = examples()[0]
        raw["orders"].pop()
        self.assertEqual(fixture_rows(raw)["report"][1],
                         {"customer_id": 2, "order_count": 0, "item_total_cents": 0})


class PollTests(unittest.TestCase):
    def test_source_mismatch_and_target_convergence_are_independent(self):
        _, _, stale, exact, *_ = examples()
        captures = iter((Capture(stale, "offline reader", 12), Capture(exact, "offline reader", 13)))
        result = verify_checkpoint("delete", "S03", reader(stale), lambda _: next(captures), interval=0.001)
        self.assertFalse(result.passed)
        self.assertEqual(result.source.status, "mismatch")
        self.assertEqual(result.target.status, "pass")
        self.assertEqual(result.target_attempts, 2)
        self.assertEqual(result.last_target_mismatch.snapshot.catalog_snapshot_id, 12)
        self.assertIn("delete/S03 source: order_items: extra key item_id=102", result.source.diffs)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "delete"
            write_evidence(path, result)
            snap = json.loads((path / "target.snapshot.json").read_text())
            self.assertEqual(snap["catalog_snapshot_id"], 13)
            self.assertEqual(snap["phase"], "delete")
            diff = json.loads((path / "target-last-mismatch.diff.json").read_text())
            self.assertIn("delete/S03 target: order_items: extra key item_id=102", diff["diffs"])

    def test_poll_deadline_preserves_last_mismatch_and_clips_sleep(self):
        _, _, stale, exact, *_ = examples()
        now = [10.0]
        seen = []

        def wait(seconds):
            now[0] += seconds

        def target(budget):
            seen.append(budget)
            return Capture(stale, "offline reader")

        with patch("scripts.cdc.parity.monotonic", side_effect=lambda: now[0]), patch(
            "scripts.cdc.parity.sleep", side_effect=wait
        ):
            result = verify_checkpoint("delete", "S03", reader(exact), target,
                                       target_timeout=1.25, interval=1)
        self.assertEqual(result.source.status, "pass")
        self.assertEqual(result.target.status, "timeout")
        self.assertEqual(result.target_attempts, 2)
        self.assertEqual(seen, [1.25, 0.25])
        self.assertEqual(now[0], 11.25)
        self.assertIn("delete/S03 target: order_items: extra key item_id=102",
                      result.last_target_mismatch.diffs)

    def test_late_match_is_rejected(self):
        exact = examples()[0]
        now = [10.0]

        def late(budget):
            now[0] += budget
            return Capture(exact, "offline reader")

        with patch("scripts.cdc.parity.monotonic", side_effect=lambda: now[0]):
            result = verify_checkpoint("initial", "S00", reader(exact), late, target_timeout=1)
        self.assertFalse(result.passed)
        self.assertEqual(result.target.status, "timeout")


class PsqlTests(unittest.TestCase):
    def test_full_projection_sql_and_csv_framing(self):
        raw = examples()[0]
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        for name, columns in COLUMNS.items():
            output.write("," * 8 + "\n")
            writer.writerow(columns)
            for row in raw[name]:
                writer.writerow([row[column] for column in columns])
        with patch("scripts.cdc.parity.psql.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, stdout=output.getvalue())
            captured = read_fixture(["psql", "-d", "source_lab"], SOURCE_TABLES, 1.5)
        self.assertEqual(compare("initial", "S00", "source", fixture_rows(captured.rows)), ())
        sql = run.call_args.kwargs["input"]
        self.assertIn("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;", sql)
        self.assertIn("SET LOCAL statement_timeout = 1500;", sql)
        self.assertEqual(sql.count("LIMIT 33;"), 4)
        self.assertNotIn("scenario_receipts", sql)
        self.assertTrue(sql.endswith("ROLLBACK;\n"))
        self.assertEqual(run.call_args.kwargs["timeout"], 1.5)

    def test_one_table_projection_preserves_multiline_text(self):
        columns = ("id", "stamp", "value")
        with patch("scripts.cdc.parity.psql.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                [], 0, stdout=',,,\nid,stamp,value\n1,2026-01-01 00:00:00+00,"a\n,,,\nb"\n',
            )
            capture = read_projections(["psql"], {"probe": (("lake", "demo"), columns, "id")}, 1)
        sql = run.call_args.kwargs["input"]
        self.assertIn('SELECT "id", "stamp", "value" FROM "lake"."demo" ORDER BY "id" LIMIT 33;', sql)
        rows = normalize_rows("probe", capture.rows["probe"], columns, "id", {"id"}, ("stamp",))
        self.assertEqual(rows, [{"id": 1, "stamp": T0, "value": "a\n,,,\nb"}])

    def test_one_table_overflow_and_psql_exit(self):
        projection = {"probe": (("lake", "demo"), ("id",), "id")}
        with patch("scripts.cdc.parity.psql.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, stdout=",\nid\n" + "1\n" * 33)
            with self.assertRaisesRegex(ReadError, "probe: row overflow"):
                read_projections(["psql"], projection, 1)
            run.return_value = subprocess.CompletedProcess([], 3)
            with self.assertRaisesRegex(ReadError, "psql read failed \\(exit 3\\)"):
                read_projections(["psql"], projection, 1)

    def test_subprocess_deadline(self):
        with self.assertRaisesRegex(ReadTimeout, "psql client deadline expired"):
            read_projections(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                {"probe": (("lake", "demo"), ("id",), "id")}, 0.1,
            )

    def test_rejects_invalid_mapping_identifier(self):
        with self.assertRaises(ValueError):
            select_rows(("public", 'probe";'), ("id",), "id")


if __name__ == "__main__":
    unittest.main()
