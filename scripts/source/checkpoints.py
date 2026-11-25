"""Read live source checkpoints and compare them with independent expectations."""
from datetime import UTC, datetime
from decimal import Decimal

from psycopg import sql

from tests.fixture_oracle import PRIMARY_KEYS, compare_checkpoint, load_expectations

from .transactions import FixtureError

ROW_LIMIT = 32
# Independently transcribed from the receipt contract in docs/source-schema.md.
S04_RECEIPT = [{
    "fixture_version": "v1", "seed": 42, "scenario_id": "S04",
    "payload_sha256": "4d2c11bd073069f7a4a9f38ba044d58219fad0c37ab3a2b43b300a97414432f8",
}]
REPORT = """
    SELECT c.customer_id, count(DISTINCT o.order_id) AS order_count,
           coalesce(sum(i.quantity::numeric * i.unit_cents), 0) AS item_total_cents
    FROM fixture.customers AS c
    LEFT JOIN fixture.orders AS o USING (customer_id)
    LEFT JOIN fixture.order_items AS i USING (order_id)
    GROUP BY c.customer_id ORDER BY c.customer_id
"""


def normalize(value):
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else str(value)
    return value


def read_state(connection):
    """Read rows on the caller's snapshot, retaining unexpected timestamp fractions."""
    actual = {}
    for table, key in PRIMARY_KEYS.items():
        if table == "report":
            continue
        rows = connection.execute(
            sql.SQL("SELECT * FROM fixture.{} ORDER BY {} LIMIT %s").format(
                sql.Identifier(table), sql.Identifier(key),
            ),
            (ROW_LIMIT + 1,),
        ).fetchall()
        if len(rows) > ROW_LIMIT:
            raise FixtureError(f"{table} exceeds the fixture inspection bound of {ROW_LIMIT} rows")
        actual[table] = [
            {column: normalize(value) for column, value in row.items()} for row in rows
        ]
    receipts = connection.execute(
        """
        SELECT * FROM fixture.scenario_receipts
        ORDER BY fixture_version, seed, scenario_id LIMIT %s
        """, (ROW_LIMIT + 1,),
    ).fetchall()
    if len(receipts) > ROW_LIMIT:
        raise FixtureError(f"scenario_receipts exceeds the fixture inspection bound of {ROW_LIMIT} rows")
    actual["report"] = [
        {column: normalize(value) for column, value in row.items()}
        for row in connection.execute(REPORT)
    ]
    return actual, receipts


def observe(reader):
    """Take a fresh, consistent, read-only snapshot on an independent backend."""
    with reader.transaction():
        reader.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        return read_state(reader)


def check_state(checkpoint, state):
    actual, receipts = state
    expected = ({table: [] for table in PRIMARY_KEYS} if checkpoint == "empty"
                else load_expectations()[checkpoint])
    problems = compare_checkpoint(expected, actual)
    expected_receipts = S04_RECEIPT if checkpoint in ("S04", "S05", "S06") else []
    if receipts != expected_receipts:
        problems.append(f"scenario_receipts: expected {expected_receipts!r}, got {receipts!r}")
    return problems


def s04_visibility(state):
    rows, receipts = state
    return {
        "order_30": any(row["order_id"] == 30 for row in rows["orders"]),
        "item_301": any(row["item_id"] == 301 for row in rows["order_items"]),
        "payment_302": any(row["payment_id"] == 302 for row in rows["payments"]),
        "receipt_S04": any((row["fixture_version"], row["seed"], row["scenario_id"])
                           == ("v1", 42, "S04") for row in receipts),
    }
