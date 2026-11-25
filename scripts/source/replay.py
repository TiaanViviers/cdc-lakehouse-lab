"""Deliver the original S04 fixture input and reconcile from its durable receipt."""
import psycopg

from .checkpoints import check_state, read_state
from .transactions import (
    SEQUENTIAL_WRITER_LOCK, FixtureError, apply_inserts, claim_s04, connect, write_transaction,
)
from .workload import SEED, VERSION, payload_digest, s04_payload

RECEIPT_KEY_COLUMNS = ("fixture_version", "seed", "scenario_id")
S04_KEY = (VERSION, SEED, "S04")
MAX_DELIVERIES = 2


class ReplayUnknown(FixtureError):
    """The source receipt could not establish the outcome."""


def read_receipt(connection, key):
    return connection.execute(
        """
        SELECT fixture_version, seed, scenario_id, payload_sha256
        FROM fixture.scenario_receipts
        WHERE (fixture_version, seed, scenario_id) = (%s, %s, %s)
        """, key,
    ).fetchone()


def require_matching_receipt(trace, stored, expected):
    if stored != expected:
        trace("receipt_mismatch", stored_receipt=stored, submitted_receipt=expected)
        raise FixtureError("S04 receipt key is already committed with a different payload")
    return stored


def reconcile(trace, expected, *, after_delivery):
    try:
        with connect("reader") as reader:
            stored = read_receipt(reader, S04_KEY)
            trace("receipt_lookup", after_delivery=after_delivery,
                  backend_pid=reader.info.backend_pid, stored_receipt=stored)
    except (psycopg.Error, OSError) as error:
        trace("receipt_lookup_failed", after_delivery=after_delivery,
              sqlstate=getattr(error, "sqlstate", None), error_type=type(error).__name__)
        raise ReplayUnknown("S04 receipt lookup unavailable") from error
    return None if stored is None else require_matching_receipt(trace, stored, expected)


def deliver(trace, payload, expected, delivery):
    with connect("writer") as writer:
        with write_transaction(writer):
            # Allow overlapping S06 deliveries while excluding the 1.5 sequential writer.
            writer.execute("SELECT pg_advisory_xact_lock_shared(%s, %s)", SEQUENTIAL_WRITER_LOCK)
            identity = dict(delivery=delivery, backend_pid=writer.info.backend_pid)
            trace("claim_started", **identity)
            if claim_s04(writer, payload) is None:
                try:
                    stored = read_receipt(writer, S04_KEY)
                except psycopg.Error as error:
                    raise ReplayUnknown("S04 receipt lookup failed after claim conflict") from error
                trace("claim_conflict", stored_receipt=stored, **identity)
                if stored is None:
                    raise ReplayUnknown("S04 receipt missing after claim conflict")
                return require_matching_receipt(trace, stored, expected), "receipt"

            rows, receipts = read_state(writer)
            # The claim is already visible inside this transaction. Compare the remaining
            # state to S03 before writing business rows.
            prior_receipts = [receipt for receipt in receipts if receipt != expected]
            differences = check_state("S03", (rows, prior_receipts))
            if differences:
                raise FixtureError(f"S04 delivery requires exact S03: {differences}")
            apply_inserts(writer, payload["operations"])
            identity["xid"] = writer.execute(
                "SELECT pg_current_xact_id_if_assigned()::text AS xid"
            ).fetchone()["xid"]
            trace("commit_requested", **identity)
        trace("commit_returned", **identity)
    return expected, "applied"


def run_replay(trace, payload):
    """Return the committed receipt and how it was established, or raise on failure."""
    if tuple(payload[column] for column in RECEIPT_KEY_COLUMNS) != S04_KEY:
        raise FixtureError("S06 requires the original S04 receipt key")
    expected = dict(zip(RECEIPT_KEY_COLUMNS, S04_KEY), payload_sha256=payload_digest(payload))
    trace("replay_input", submitted_receipt=expected)
    stored = reconcile(trace, expected, after_delivery=0)
    if stored is not None:
        return stored, "receipt"
    if payload != s04_payload():
        raise FixtureError("S06 can only apply the original S04 payload")

    for delivery in range(1, MAX_DELIVERIES + 1):
        try:
            return deliver(trace, payload, expected, delivery)
        except psycopg.OperationalError as error:
            trace("delivery_interrupted", delivery=delivery, sqlstate=error.sqlstate,
                  error_type=type(error).__name__)
            # Absence is snapshot-local. The claim must still arbitrate any late commit.
            stored = reconcile(trace, expected, after_delivery=delivery)
            if stored is not None:
                return stored, "receipt"
    raise ReplayUnknown("S04 write budget exhausted without a matching receipt")
