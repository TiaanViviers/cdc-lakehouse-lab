"""Literal mutation inputs for fixture v1/seed 42."""
import hashlib
import json
from datetime import UTC, datetime

VERSION = "v1"
SEED = 42
PREVIOUS = {"S00": "empty", "S01": "S00", "S02": "S01", "S03": "S02", "S04": "S03"}
INSERTS = {
    "S00": (
        ("customers", dict(customer_id=1, code="C1", name="Ada")),
        ("customers", dict(customer_id=2, code="C2", name="Bo")),
        ("orders", dict(order_id=10, customer_id=1, order_ref="O10", status="open")),
        ("orders", dict(order_id=20, customer_id=2, order_ref="O20", status="paid")),
        ("order_items", dict(item_id=101, order_id=10, line_no=1, sku="A",
                             quantity=2, unit_cents=300)),
        ("order_items", dict(item_id=201, order_id=20, line_no=1, sku="B",
                             quantity=1, unit_cents=500)),
        ("payments", dict(payment_id=301, order_id=20, payment_ref="P301", amount_cents=500)),
    ),
    "S01": (
        ("order_items", dict(item_id=102, order_id=10, line_no=2, sku="B",
                             quantity=1, unit_cents=500)),
    ),
    "S04": (
        ("orders", dict(order_id=30, customer_id=1, order_ref="O30", status="paid")),
        ("order_items", dict(item_id=301, order_id=30, line_no=1, sku="C",
                             quantity=2, unit_cents=200)),
        ("payments", dict(payment_id=302, order_id=30, payment_ref="P302", amount_cents=400)),
    ),
}


def fixture_time(scenario):
    """Return the scenario's fixed UTC instant, including for future steps."""
    return datetime(2026, 1, 1, 0, int(scenario[1:]), tzinfo=UTC)


def insert_operations(scenario):
    timestamp = fixture_time(scenario).isoformat().replace("+00:00", "Z")
    return [
        {"op": "insert", "table": table,
         "row": dict(values, created_at=timestamp, updated_at=timestamp)}
        for table, values in INSERTS[scenario]
    ]


def s04_payload():
    return dict(fixture_version=VERSION, seed=SEED, scenario_id="S04",
                operations=insert_operations("S04"))


def payload_digest(payload):
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True, allow_nan=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
