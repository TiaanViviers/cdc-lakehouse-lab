"""Load the published fixture expectations and compare canonical keyed rows."""

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

EXPECTED_PATH = Path(__file__).with_name("fixtures") / "v1" / "expected.json"
PRIMARY_KEYS = {
    "customers": "customer_id",
    "orders": "order_id",
    "order_items": "item_id",
    "payments": "payment_id",
    "report": "customer_id",
}

Row = Mapping[str, int | str | None]
Checkpoint = Mapping[str, Iterable[Row]]


def load_expectations() -> dict[str, dict[str, list[dict[str, int | str]]]]:
    with EXPECTED_PATH.open(encoding="utf-8") as fixture:
        return json.load(fixture)


def compare_rows(
    relation: str, key_column: str, expected: Iterable[Row], actual: Iterable[Row]
) -> list[str]:
    """Return diagnostics for a relation or an empty list for exact parity.

    Rows use canonical scalar values and integer keys. Check both inputs for
    invalid and duplicate keys before matching, since those keys are ambiguous.
    """
    problems = []

    def index(rows: Iterable[Row], side: str) -> dict[int, Row]:
        by_key = {}
        duplicates = set()
        for row_number, row in enumerate(rows, start=1):
            key = row.get(key_column)
            if type(key) is not int:
                problems.append(
                    f"{relation}: invalid {side} {key_column} in row {row_number}: {key!r}"
                )
                continue
            if key in by_key:
                duplicates.add(key)
            by_key[key] = row
        for key in sorted(duplicates):
            problems.append(f"{relation}: duplicate {side} key {key_column}={key}")
        return by_key

    expected_by_key = index(expected, "expected")
    actual_by_key = index(actual, "actual")
    if problems:
        return problems

    for key in sorted(expected_by_key.keys() - actual_by_key.keys()):
        problems.append(f"{relation}: missing key {key_column}={key}")
    for key in sorted(actual_by_key.keys() - expected_by_key.keys()):
        problems.append(f"{relation}: extra key {key_column}={key}")
    for key in sorted(expected_by_key.keys() & actual_by_key.keys()):
        expected_row = expected_by_key[key]
        actual_row = actual_by_key[key]
        label = f"{relation}: unequal {key_column}={key}"
        for column, value in expected_row.items():
            if column not in actual_row:
                problems.append(f"{label} {column}: missing column, expected {value!r}")
                continue
            actual_value = actual_row[column]
            if type(actual_value) is not type(value) or actual_value != value:
                problems.append(f"{label} {column}: expected {value!r}, got {actual_value!r}")
        for column in sorted(actual_row.keys() - expected_row.keys()):
            problems.append(f"{label} {column}: extra column, got {actual_row[column]!r}")
    return problems


def compare_checkpoint(expected: Checkpoint, actual: Checkpoint) -> list[str]:
    """Compare all four business tables and the customer report."""
    problems = []
    for side, checkpoint in (("expected", expected), ("actual", actual)):
        for relation in sorted(checkpoint.keys() - PRIMARY_KEYS.keys()):
            problems.append(f"{relation}: extra relation in {side} checkpoint")
        for relation in sorted(PRIMARY_KEYS.keys() - checkpoint.keys()):
            problems.append(f"{relation}: missing relation in {side} checkpoint")

    for relation, key_column in PRIMARY_KEYS.items():
        if relation in expected and relation in actual:
            problems.extend(
                compare_rows(relation, key_column, expected[relation], actual[relation])
            )
    return problems
