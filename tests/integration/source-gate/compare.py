"""Check a read-only psql snapshot against the published fixture."""
import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from tests.fixture_oracle import PRIMARY_KEYS, compare_checkpoint, load_expectations

S04_RECEIPT = {
    "fixture_version": "v1", "seed": 42, "scenario_id": "S04",
    "payload_sha256": "4d2c11bd073069f7a4a9f38ba044d58219fad0c37ab3a2b43b300a97414432f8",
}


def read_snapshot(path):
    rows = json.loads(Path(path).read_text())
    receipts = rows.pop("receipts")
    for relation, records in rows.items():
        if len(records) > 32:
            raise ValueError(f"{relation} exceeds the 32-row fixture bound")
        for row in records:
            for column in ("created_at", "updated_at"):
                if isinstance(row.get(column), str):
                    row[column] = datetime.fromisoformat(row[column]).astimezone(UTC).isoformat()
                    row[column] = row[column].replace("+00:00", "Z")
    return rows, receipts


def main(checkpoint, path, reference, receipt_reference):
    rows, receipts = read_snapshot(path)
    expected = ({table: [] for table in PRIMARY_KEYS} if checkpoint == "empty"
                else load_expectations()[checkpoint])
    differences = compare_checkpoint(expected, rows)
    receipt_values = [
        {key: value for key, value in receipt.items() if key != "tuple_xid"}
        for receipt in receipts
    ]
    expected_receipts = [S04_RECEIPT] if checkpoint in ("S04", "S05", "S06") else []
    if receipt_values != expected_receipts:
        differences.append(f"receipts: expected {expected_receipts!r}, got {receipt_values!r}")
    if any(not receipt.get("tuple_xid", "").isdigit() for receipt in receipts):
        differences.append("receipt tuple transaction ID is missing or invalid")
    if reference and (rows, receipts) != read_snapshot(reference):
        differences.append(f"live snapshot differs from {Path(reference).name}, including receipt xmin")
    if receipt_reference and receipts != read_snapshot(receipt_reference)[1]:
        differences.append(f"receipt differs from {Path(receipt_reference).name}, including xmin")
    canonical = json.dumps({"rows": rows, "receipts": receipt_values},
                           sort_keys=True, separators=(",", ":")).encode()
    print(json.dumps({
        "checkpoint": checkpoint, "snapshot": Path(path).name, "differences": differences,
        "report": rows["report"], "receipt_count": len(receipts),
        "receipt_xids": [receipt.get("tuple_xid") for receipt in receipts],
        "sha256": hashlib.sha256(canonical).hexdigest(),
    }, sort_keys=True))
    return bool(differences)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint")
    parser.add_argument("path")
    parser.add_argument("--reference")
    parser.add_argument("--receipt-reference")
    sys.exit(main(**vars(parser.parse_args())))
