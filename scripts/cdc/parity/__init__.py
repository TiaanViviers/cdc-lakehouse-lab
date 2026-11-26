"""Independent comparison of the v1 fixture at a caller-controlled hold point."""

import json
import math
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from time import monotonic, sleep

from tests.fixture_oracle import PRIMARY_KEYS, compare_checkpoint, load_expectations

ROW_LIMIT = 32
TIMESTAMPS = ("created_at", "updated_at")
# Explicit fixture projection. The report is computed from each side's rows.
COLUMNS = {
    "customers": ("customer_id", "code", "name", *TIMESTAMPS),
    "orders": ("order_id", "customer_id", "order_ref", "status", *TIMESTAMPS),
    "order_items": (
        "item_id", "order_id", "line_no", "sku", "quantity", "unit_cents", *TIMESTAMPS,
    ),
    "payments": ("payment_id", "order_id", "payment_ref", "amount_cents", *TIMESTAMPS),
}
INTEGERS = {
    "customer_id", "order_id", "item_id", "payment_id", "line_no", "quantity",
    "unit_cents", "amount_cents",
}
Value = int | str
Rows = dict[str, list[dict[str, Value]]]
RawRows = Mapping[str, Iterable[Mapping[str, object]]]


class ReadError(ValueError):
    """A bounded read could not produce a valid snapshot."""


class ReadTimeout(ReadError):
    """The reader exceeded its client deadline."""


def timestamp(value: object) -> str:
    # Restrict text to the fixture's ISO forms. Reject excess precision instead
    # of letting fromisoformat silently truncate a changed timestamp.
    if isinstance(value, str):
        if not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}"
            r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}(?::[0-9]{2})?)",
            value,
        ):
            raise ValueError
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def normalize_rows(
    relation: str,
    rows: Iterable[Mapping[str, object]],
    columns: tuple[str, ...],
    key: str,
    integers: set[str],
    timestamps: tuple[str, ...] = (),
) -> list[dict[str, Value]]:
    bounded = list(islice(rows, ROW_LIMIT + 1))
    if len(bounded) > ROW_LIMIT:
        raise ReadError(f"{relation}: row overflow (limit {ROW_LIMIT})")
    result = []
    for index, row in enumerate(bounded, start=1):
        if row.keys() != set(columns):
            raise ReadError(f"{relation}: row {index} does not match projected columns")
        normalized = {}
        for column in columns:
            value = row[column]
            try:
                if column in timestamps:
                    normalized[column] = timestamp(value)
                elif column in integers:
                    if type(value) is int:
                        normalized[column] = value
                    elif isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value):
                        normalized[column] = int(value)
                    else:
                        raise ValueError
                elif isinstance(value, str):
                    normalized[column] = value
                else:
                    raise ValueError
            except (ValueError, OverflowError):
                raise ReadError(f"{relation}: row {index} invalid {column}") from None
        result.append(normalized)
    return sorted(result, key=lambda row: row[key])


def customer_report(rows: Rows) -> list[dict[str, Value]]:
    report = []
    for customer in rows["customers"]:
        customer_id = customer["customer_id"]
        orders = [row for row in rows["orders"] if row["customer_id"] == customer_id]
        report.append({
            "customer_id": customer_id,
            "order_count": len(orders),
            "item_total_cents": sum(
                item["quantity"] * item["unit_cents"]
                for order in orders for item in rows["order_items"]
                if item["order_id"] == order["order_id"]
            ),
        })
    return report


@dataclass(frozen=True)
class Capture:
    rows: RawRows
    reader_semantics: str
    catalog_snapshot_id: str | int | None = None


@dataclass(frozen=True)
class Snapshot:
    rows: Rows
    reader_semantics: str
    catalog_snapshot_id: str | int | None
    started_at_utc: str
    finished_at_utc: str
    elapsed_seconds: float


@dataclass(frozen=True)
class Outcome:
    phase: str
    checkpoint: str
    side: str
    status: str
    diffs: tuple[str, ...]
    snapshot: Snapshot | None = None


@dataclass(frozen=True)
class CheckpointResult:
    source: Outcome
    target: Outcome
    target_attempts: int
    last_target_mismatch: Outcome | None

    @property
    def passed(self) -> bool:
        return self.source.status == self.target.status == "pass"


def fixture_rows(raw: RawRows) -> Rows:
    if raw.keys() != COLUMNS.keys():
        raise ReadError("capture must contain all four projected business relations")
    rows = {
        name: normalize_rows(name, raw[name], columns, PRIMARY_KEYS[name], INTEGERS,
                             TIMESTAMPS)
        for name, columns in COLUMNS.items()
    }
    rows["report"] = customer_report(rows)
    return rows


def compare(phase: str, checkpoint: str, side: str, rows: Rows) -> tuple[str, ...]:
    return tuple(
        f"{phase}/{checkpoint} {side}: {diff}"
        for diff in compare_checkpoint(load_expectations()[checkpoint], rows)
    )


Reader = Callable[[float], Capture]


def _observe(
    phase: str, checkpoint: str, side: str, read: Reader, deadline: float
) -> Outcome:
    started = datetime.now(UTC)
    start = monotonic()
    try:
        budget = deadline - start
        if budget <= 0:
            raise ReadTimeout("read deadline expired")
        capture = read(budget)
        rows = fixture_rows(capture.rows)
        diffs = compare(phase, checkpoint, side, rows)
        end = monotonic()
        if end >= deadline:
            raise ReadTimeout("read deadline expired")
        snapshot = Snapshot(
            rows, capture.reader_semantics, capture.catalog_snapshot_id,
            timestamp(started), timestamp(datetime.now(UTC)), end - start,
        )
    except ReadError as exc:
        status = "timeout" if isinstance(exc, ReadTimeout) else "read_error"
        return Outcome(phase, checkpoint, side, status, (f"{phase}/{checkpoint} {side}: {exc}",))
    return Outcome(phase, checkpoint, side, "mismatch" if diffs else "pass", diffs, snapshot)


def verify_checkpoint(
    phase: str,
    checkpoint: str,
    source: Reader,
    target: Reader,
    *,
    source_timeout: float = 10,
    target_timeout: float = 60,
    interval: float = 0.5,
) -> CheckpointResult:
    """Read source once, then poll fresh target reads while the writer holds."""
    if not phase or checkpoint not in load_expectations():
        raise ValueError("provide a phase label and a published fixture checkpoint")
    if any(not math.isfinite(v) or v <= 0 for v in (source_timeout, target_timeout, interval)):
        raise ValueError("timeouts and interval must be finite and positive")
    source_result = _observe(phase, checkpoint, "source", source, monotonic() + source_timeout)
    deadline = monotonic() + target_timeout
    attempts = 0
    last_mismatch = None
    while True:
        if monotonic() >= deadline:
            target_result = Outcome(
                phase, checkpoint, "target", "timeout",
                (f"{phase}/{checkpoint} target: parity deadline expired",),
            )
            break
        attempts += 1
        target_result = _observe(phase, checkpoint, "target", target, deadline)
        if target_result.status != "mismatch":
            break
        last_mismatch = target_result
        sleep(max(0, min(interval, deadline - monotonic())))
    return CheckpointResult(source_result, target_result, attempts, last_mismatch)


def write_evidence(directory: Path, result: CheckpointResult) -> None:
    """Write one named bundle per hold point into a fresh evidence directory."""
    directory.mkdir(parents=True)
    for name, outcome in (
        ("source", result.source),
        ("target", result.target),
        ("target-last-mismatch", result.last_target_mismatch),
    ):
        if outcome is None:
            continue
        payload = asdict(outcome)
        snapshot = payload.pop("snapshot")
        if name == "target":
            payload["attempts"] = result.target_attempts
        if snapshot is not None:
            for field in ("phase", "checkpoint", "side"):
                snapshot[field] = payload[field]
            (directory / f"{name}.snapshot.json").write_text(
                json.dumps(snapshot, indent=2) + "\n", encoding="utf-8",
            )
        (directory / f"{name}.diff.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8",
        )
