from datetime import UTC, datetime
from unittest import TestCase

from tests.fixture_oracle import compare_checkpoint, load_expectations


class FixtureOracleTest(TestCase):
    def setUp(self):
        self.expected = load_expectations()
        self.actual = load_expectations()

    def test_complete_fixtures_use_canonical_values(self):
        columns = {
            "customers": tuple("customer_id code name created_at updated_at".split()),
            "orders": tuple("order_id customer_id order_ref status created_at updated_at".split()),
            "order_items": tuple(
                "item_id order_id line_no sku quantity unit_cents created_at updated_at".split()
            ),
            "payments": tuple(
                "payment_id order_id payment_ref amount_cents created_at updated_at".split()
            ),
            "report": ("customer_id", "order_count", "item_total_cents"),
        }
        self.assertEqual(list(self.expected), [f"S{step:02}" for step in range(7)])
        for step, checkpoint in self.expected.items():
            with self.subTest(step=step):
                self.assertEqual(checkpoint.keys(), columns.keys())
                self.assertEqual([row["customer_id"] for row in checkpoint["report"]], [1, 2])
                for relation, rows in checkpoint.items():
                    key_column = columns[relation][0]
                    keys = [row[key_column] for row in rows]
                    self.assertEqual(keys, sorted(set(keys)))
                    for row in rows:
                        self.assertEqual(tuple(row), columns[relation])
                        self.assertIs(type(row[key_column]), int)
                        if relation != "report":
                            for column in ("created_at", "updated_at"):
                                value = row[column]
                                parsed = datetime.fromisoformat(value)
                                self.assertIs(parsed.tzinfo, UTC)
                                canonical = parsed.isoformat(timespec="seconds").replace("+00:00", "Z")
                                self.assertEqual(value, canonical)

    def test_literal_report_matches_business_rows_at_each_checkpoint(self):
        for step, checkpoint in self.expected.items():
            for report in checkpoint["report"]:
                customer_id = report["customer_id"]
                with self.subTest(step=step, customer_id=customer_id):
                    orders = {
                        order["order_id"] for order in checkpoint["orders"]
                        if order["customer_id"] == customer_id
                    }
                    total = sum(
                        item["quantity"] * item["unit_cents"]
                        for item in checkpoint["order_items"]
                        if item["order_id"] in orders
                    )
                    self.assertIs(type(report["order_count"]), int)
                    self.assertIs(type(report["item_total_cents"]), int)
                    self.assertEqual(report["order_count"], len(orders))
                    self.assertEqual(report["item_total_cents"], total)

    def test_matching_checkpoints_accept_different_row_order(self):
        for step, expected in self.expected.items():
            with self.subTest(step=step):
                actual = {relation: reversed(rows) for relation, rows in self.actual[step].items()}
                self.assertEqual(compare_checkpoint(expected, actual), [])

    def test_wrong_value_with_same_row_count(self):
        self.actual["S02"]["order_items"][0]["quantity"] = 2
        self.assert_diagnostics(
            "S02", ["order_items: unequal item_id=101 quantity: expected 3, got 2"]
        )

    def test_wrong_report_values_for_both_customers(self):
        customer_1, customer_2 = self.actual["S05"]["report"]
        customer_1["item_total_cents"] = 1800
        customer_2["order_count"] = 2
        self.assert_diagnostics("S05", [
            "report: unequal customer_id=1 item_total_cents: expected 1600, got 1800",
            "report: unequal customer_id=2 order_count: expected 1, got 2",
        ])

    def test_replay_timestamp_change(self):
        self.actual["S06"]["orders"][2]["updated_at"] = "2026-01-01T00:06:00Z"
        self.assert_diagnostics("S06", [
            "orders: unequal order_id=30 updated_at: expected '2026-01-01T00:04:00Z', "
            "got '2026-01-01T00:06:00Z'",
        ])

    def test_duplicate_keys_reported_on_both_sides_before_matching(self):
        expected = self.expected["S02"]["order_items"]
        actual = self.actual["S02"]["order_items"]
        expected[-1] = dict(expected[0])
        actual[1] = dict(actual[-1], quantity=7)
        self.assert_diagnostics("S02", [
            "order_items: duplicate expected key item_id=101",
            "order_items: duplicate actual key item_id=201",
        ])

    def test_deleted_key_residue_is_extra_even_with_null_values(self):
        item = self.expected["S02"]["order_items"][1]
        residue = dict.fromkeys(item)
        residue["item_id"] = 102
        self.actual["S03"]["order_items"].append(residue)
        self.assert_diagnostics("S03", ["order_items: extra key item_id=102"])

    def test_missing_and_extra_keys_with_same_row_count(self):
        self.actual["S03"]["order_items"][1] = self.expected["S02"]["order_items"][1]
        self.assert_diagnostics("S03", [
            "order_items: missing key item_id=201",
            "order_items: extra key item_id=102",
        ])

    def test_missing_and_extra_columns_are_unequal(self):
        item = self.actual["S00"]["order_items"][0]
        del item["sku"]
        item["unexpected"] = None
        self.assert_diagnostics("S00", [
            "order_items: unequal item_id=101 sku: missing column, expected 'A'",
            "order_items: unequal item_id=101 unexpected: extra column, got None",
        ])

    def test_type_and_null_values_are_preserved(self):
        payment = self.actual["S00"]["payments"][0]
        payment["amount_cents"] = 500.0
        payment["payment_ref"] = None
        self.assert_diagnostics("S00", [
            "payments: unequal payment_id=301 payment_ref: expected 'P301', got None",
            "payments: unequal payment_id=301 amount_cents: expected 500, got 500.0",
        ])

    def test_invalid_key_is_reported_before_matching(self):
        self.actual["S00"]["customers"][0]["customer_id"] = "1"
        self.assert_diagnostics("S00", ["customers: invalid actual customer_id in row 1: '1'"])

    def test_missing_and_extra_relations(self):
        self.actual["S00"]["unexpected"] = self.actual["S00"].pop("payments")
        self.assert_diagnostics("S00", [
            "unexpected: extra relation in actual checkpoint",
            "payments: missing relation in actual checkpoint",
        ])

    def test_delete_and_replay_expectations(self):
        for step in ("S01", "S02"):
            with self.subTest(step=step):
                keys = [row["item_id"] for row in self.expected[step]["order_items"]]
                self.assertEqual(keys, [101, 102, 201])
        for step in ("S03", "S04", "S05", "S06"):
            with self.subTest(step=step):
                self.assertNotIn(102, [row["item_id"] for row in self.expected[step]["order_items"]])
        self.assertEqual(compare_checkpoint(self.expected["S05"], self.expected["S06"]), [])

    def assert_diagnostics(self, step, diagnostics):
        self.assertEqual(compare_checkpoint(self.expected[step], self.actual[step]), diagnostics)
