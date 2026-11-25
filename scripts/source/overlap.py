"""Coordinate and verify the two disjoint S05 source transactions."""
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Barrier, BrokenBarrierError
from time import monotonic

import psycopg

from .checkpoints import check_state, observe
from .transactions import (
    FixtureError, connect, sequential_writer, write_transaction, writer_identity,
)
from .workload import fixture_time

BARRIER_SECONDS = 4
RESULT_SECONDS = 12


def wait_at_gate(gate, transaction):
    started = monotonic()
    try:
        gate.wait()
    except BrokenBarrierError as error:
        elapsed_ms = round((monotonic() - started) * 1000)
        raise FixtureError(
            f"S05 {transaction} commit barrier broke after {elapsed_ms} ms "
            f"(deadline {BARRIER_SECONDS} s)"
        ) from error


def wait_for_result(result, stage):
    try:
        return result.result(timeout=RESULT_SECONDS)
    except TimeoutError as error:
        raise FixtureError(f"S05 {stage} exceeded {RESULT_SECONDS} s") from error


def write_b(trace, writer, staged, release_a, release_b):
    try:
        with write_transaction(writer):
            t05 = fixture_time("S05")
            writer.execute(
                """
                INSERT INTO fixture.payments
                    (payment_id, order_id, payment_ref, amount_cents, created_at, updated_at)
                VALUES (303, 10, 'P303', 200, %s, %s)
                """,
                (t05, t05),
            )
            identity = writer_identity(writer)
            staged.set_result(identity)
            wait_at_gate(release_a, "A")
            wait_at_gate(release_b, "B")
            trace("commit_requested", transaction="B", **identity)
        trace("commit_acknowledged", transaction="B", **identity)
    except Exception as error:
        if not staged.done():
            staged.set_exception(error)
        raise


def transaction_statuses(reader, identities):
    return {
        name: reader.execute("SELECT pg_xact_status(%s::xid8) AS status",
                             (identity["xid"],)).fetchone()["status"]
        for name, identity in identities.items()
    }


def record_snapshot(trace, reader, event, checkpoint, state, statuses, differences, **details):
    rows, receipts = state
    trace(event, checkpoint=checkpoint, backend_pid=reader.info.backend_pid,
          rows=rows, report=rows["report"], receipts=receipts, transaction_statuses=statuses,
          differences=differences, **details)


def verify_snapshot(trace, reader, event, checkpoint, identities, expected_statuses):
    state = observe(reader)
    statuses = transaction_statuses(reader, identities)
    differences = check_state(checkpoint, state)
    if statuses != expected_statuses:
        differences.append(f"transaction statuses: expected {expected_statuses}, got {statuses}")
    record_snapshot(trace, reader, event, checkpoint, state, statuses, differences)
    if differences:
        raise FixtureError(f"expected exact {checkpoint} state; see checkpoint differences")


def record_failure_state(trace, reader, identities):
    failed_at = trace.stage
    try:
        state = observe(reader)
        statuses = transaction_statuses(reader, identities)
        comparisons = {
            checkpoint: check_state(checkpoint, state) for checkpoint in ("S04", "S05-A", "S05")
        }
        checkpoint = next((name for name, diff in comparisons.items() if not diff), None)
        outcomes = {"S04": "rolled_back", "S05-A": "partial_commit", "S05": "committed"}
        record_snapshot(trace, reader, "failure_state", checkpoint, state, statuses,
                        [] if checkpoint else comparisons,
                        outcome=outcomes.get(checkpoint, "unverified"), failed_at=failed_at)
    except (FixtureError, psycopg.Error, OSError):
        trace("failure_state_unverified", outcome="unverified", failed_at=failed_at)


def run_schedule(trace, reader, a, b, fault, identities):
    release_a = Barrier(2, timeout=BARRIER_SECONDS)
    release_b = Barrier(2, timeout=BARRIER_SECONDS)
    staged = Future()
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            with write_transaction(a):
                result = a.execute(
                    "UPDATE fixture.order_items SET quantity = 4, updated_at = %s WHERE item_id = 101",
                    (fixture_time("S05"),),
                )
                if result.rowcount != 1:
                    raise FixtureError("S05 A requires item 101")
                identities["A"] = writer_identity(a)
                trace("writer_staged", transaction="A", **identities["A"])
                task = pool.submit(write_b, trace, b, staged, release_a, release_b)
                identities["B"] = wait_for_result(staged, "B staging")
                trace("writer_staged", transaction="B", **identities["B"])
                backend_pids = {a.info.backend_pid, b.info.backend_pid, reader.info.backend_pid}
                xids = {identity["xid"] for identity in identities.values()}
                if len(backend_pids) != 3 or len(xids) != 2 or None in xids:
                    raise FixtureError("S05 requires three backends and two distinct writer XIDs")
                verify_snapshot(trace, reader, "both_open", "S04", identities,
                                {"A": "in progress", "B": "in progress"})
                if fault == "barrier-timeout":
                    trace("barrier_release_withheld", transaction="A", deadline_s=BARRIER_SECONDS)
                    wait_for_result(task, "A barrier timeout and B rollback")
                    raise FixtureError("S05 barrier timeout injection did not reach the barrier")
                trace("barrier_release", transaction="A", deadline_s=BARRIER_SECONDS)
                wait_at_gate(release_a, "A")
                trace("commit_requested", transaction="A", **identities["A"])
            trace("commit_acknowledged", transaction="A", **identities["A"])
            verify_snapshot(trace, reader, "a_only", "S05-A", identities,
                            {"A": "committed", "B": "in progress"})
            if fault == "after-a-commit":
                raise FixtureError("S05 injected failure after A commit and before B release")
            trace("barrier_release", transaction="B", deadline_s=BARRIER_SECONDS)
            wait_at_gate(release_b, "B")
            wait_for_result(task, "B commit")
            verify_snapshot(trace, reader, "after_commit", "S05", identities,
                            {"A": "committed", "B": "committed"})
        finally:
            # Break pending waits before the executor joins so B unwinds on any fault.
            release_a.abort()
            release_b.abort()


def run_s05(trace, reader, fault):
    writers = {}
    identities = {}
    try:
        with connect("writer") as a, sequential_writer(a):
            writers["A"] = (a.info.backend_pid, a)
            verify_snapshot(trace, reader, "predecessor", "S04", {}, {})
            try:
                with connect("writer") as b:
                    writers["B"] = (b.info.backend_pid, b)
                    run_schedule(trace, reader, a, b, fault, identities)
            except (FixtureError, psycopg.Error, OSError):
                # Both write transactions have unwound. A still holds the runner lock
                # while we inspect committed rows independently and report the outcome.
                record_failure_state(trace, reader, identities)
                raise
    finally:
        trace("writers_closed", writers={
            name: dict(backend_pid=pid, closed=connection.closed)
            for name, (pid, connection) in writers.items()
        })
