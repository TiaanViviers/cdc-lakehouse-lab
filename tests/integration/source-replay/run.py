"""Run the S06 experiment inside the isolated fixture-runner container."""
import hashlib
import json
import os
import select
import signal
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic, sleep
from unittest.mock import patch

import psycopg
from psycopg import sql

from scripts.source import replay, runner
from scripts.source.checkpoints import S04_RECEIPT, check_state, read_state
from scripts.source.transactions import connect
from scripts.source.workload import s04_payload
from tests.fixture_oracle import PRIMARY_KEYS

EVIDENCE = Path("/evidence")
BARRIER_SECONDS = 8
CHILD_SECONDS = 12


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def snapshot(label, checkpoint):
    with connect("reader") as reader, reader.transaction():
        reader.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        rows, receipts = read_state(reader)
        differences = check_state(checkpoint, (rows, receipts))
        versions = {}
        for table, key in PRIMARY_KEYS.items():
            if table != "report":
                versions[table] = reader.execute(sql.SQL(
                    "SELECT {}, xmin::text AS xmin FROM fixture.{} ORDER BY {} LIMIT 33"
                ).format(sql.Identifier(key), sql.Identifier(table), sql.Identifier(key))).fetchall()
        versions["scenario_receipts"] = reader.execute("""
            SELECT fixture_version, seed, scenario_id, xmin::text AS xmin
            FROM fixture.scenario_receipts ORDER BY fixture_version, seed, scenario_id LIMIT 33
        """).fetchall()
        result = dict(rows=rows, receipts=receipts, versions=versions)
        write_json(EVIDENCE / f"{label}.json", dict(
            **result, checkpoint=checkpoint, differences=differences,
            backend_pid=reader.info.backend_pid, utc=datetime.now(UTC).isoformat(),
        ))
    assert differences == [], (label, differences)
    digest = hashlib.sha256(json.dumps(
        dict(rows=rows, receipts=receipts), sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    print(f"{label} {checkpoint} differences=0 sha256={digest}", flush=True)
    return result


class Child:
    def __init__(self, process, path):
        self.process = process
        self.path = path

    def events(self, event):
        # An active child may still be writing its final line.
        lines = self.path.read_bytes().split(b"\n")[:-1]
        return [record for record in map(json.loads, lines) if record["event"] == event]

    def one(self, event):
        records = self.events(event)
        assert len(records) == 1, (self.path, event, records)
        return records[0]

    def at(self, event):
        deadline = monotonic() + BARRIER_SECONDS
        while monotonic() < deadline:
            if self.events(event):
                return self.one(event)
            if self.process.poll() is not None:
                break
            sleep(0.02)
        raise AssertionError((self.path, "missing event", event))

    def finish(self, expected=0):
        rc = self.process.wait(timeout=CHILD_SECONDS)
        assert rc == expected, (self.path, rc, expected, self.path.read_text())

    def kill(self):
        self.process.kill()
        self.finish(-signal.SIGKILL)
        assert not self.events("outcome"), self.path

    def release(self):
        self.process.stdin.write(b"continue\n")
        self.process.stdin.flush()


@contextmanager
def start(run_id, attempt, name, *args, fault=None):
    command = [sys.executable, "-B"]
    if fault:
        command += [__file__, "--child", fault]
    else:
        command += ["-m", "scripts.source.runner"]
    command += ["--run-id", run_id, "--attempt", str(attempt), *args]
    path = EVIDENCE / f"{name}.jsonl"
    with path.open("xb") as log, path.with_suffix(".stderr").open("xb") as stderr:
        with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=log, stderr=stderr) as process:
            try:
                yield Child(process, path)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=2)


def experiment(run_id):
    start_time = monotonic()
    attempt = 0

    def launch(name, *args, fault=None):
        nonlocal attempt
        attempt += 1
        return start(run_id, attempt, name, *args, fault=fault)

    def call(name, *args, status=0, fault=None):
        with launch(name, *args, fault=fault) as child:
            child.finish(status)
            return child

    def baseline(name):
        call(f"{name}-reset", "reset", "--confirm")
        for step in ("S01", "S02", "S03"):
            call(f"{name}-{step}", "run", step)
        return snapshot(f"{name}-before", "S03")

    def committed(child, resolution):
        outcome = child.one("outcome")
        assert (outcome["scenario"], outcome["status"], outcome["resolution"], outcome["receipt"]) == (
            "S06", "committed", resolution, S04_RECEIPT[0],
        ), outcome
        return outcome

    def assert_winner(state, staged):
        # This fresh fixture database fits in a single 32-bit XID epoch.
        xid = str(int(staged["xid"]) % (2 ** 32))
        for table, key, value in (
            ("orders", "order_id", 30), ("order_items", "item_id", 301),
            ("payments", "payment_id", 302), ("scenario_receipts", "scenario_id", "S04"),
        ):
            row = next(row for row in state["versions"][table] if row[key] == value)
            assert row["xmin"] == xid, (table, row, staged)

    def unchanged_prior(prior, after):
        for table, versions in prior["versions"].items():
            assert all(row in after["versions"][table] for row in versions), table

    baseline("existing")
    first = call("existing-S04", "run", "S04")
    original = snapshot("existing-committed", "S04")
    assert_winner(original, first.one("commit_acknowledged"))
    redelivery = call("existing-replay", "run", "S06")
    committed(redelivery, "receipt")
    assert redelivery.one("receipt_lookup")["backend_pid"] != first.one("commit_acknowledged")["backend_pid"]
    assert not redelivery.events("claim_started")
    assert snapshot("existing-after", "S04") == original
    mismatch = call("mismatch", "run", "S06", status=1, fault="mismatch")
    rejection = mismatch.one("receipt_mismatch")
    assert rejection["stored_receipt"] == S04_RECEIPT[0]
    assert rejection["submitted_receipt"] == dict(S04_RECEIPT[0],
        payload_sha256="a01e11c7cc6c23eec7b04ed9fccabf7423877c024b1cd280baec139b21dbac80")
    assert not mismatch.events("claim_started") and not mismatch.events("outcome")
    assert snapshot("mismatch-after", "S04") == original

    prior = baseline("precommit")
    with launch("precommit-lost-runner", "run", "S06", fault="hold_before_commit") as child:
        staged = child.at("commit_requested")
        assert snapshot("precommit-held", "S03") == prior
        child.kill()
        assert not child.events("commit_returned")
    assert snapshot("precommit-interrupted", "S03") == prior
    retried = call("precommit-retry", "run", "S06")
    committed(retried, "applied")
    lookup = retried.one("receipt_lookup")
    assert lookup["backend_pid"] != staged["backend_pid"] and lookup["stored_receipt"] is None
    after = snapshot("precommit-recovered", "S04")
    assert_winner(after, retried.one("commit_returned"))
    unchanged_prior(prior, after)

    prior = baseline("postcommit")
    with launch("postcommit-lost-runner", "run", "S06", fault="hold_after_commit") as child:
        returned = child.at("commit_returned")
        before_ack = snapshot("postcommit-before-ack", "S04")
        assert_winner(before_ack, returned)
        unchanged_prior(prior, before_ack)
        child.kill()
    resumed = call("postcommit-reconcile", "run", "S06")
    committed(resumed, "receipt")
    assert resumed.one("receipt_lookup")["backend_pid"] != returned["backend_pid"]
    assert not resumed.events("claim_started")
    assert snapshot("postcommit-recovered", "S04") == before_ack

    prior = baseline("overlap")
    with launch("overlap-A", "run", "S06", fault="hold_before_commit") as a:
        staged = a.at("commit_requested")
        assert snapshot("overlap-A-held", "S03") == prior
        with launch("overlap-B", "run", "S06") as b:
            claimant = b.at("claim_started")
            assert b.one("receipt_lookup")["stored_receipt"] is None
            observe_claim_wait(staged["backend_pid"], claimant["backend_pid"])
            a.release()
            a.finish()
            b.finish()
    committed(a, "applied")
    committed(b, "receipt")
    assert b.one("claim_conflict")["stored_receipt"] == S04_RECEIPT[0]
    assert not b.events("commit_requested") and not b.events("delivery_interrupted")
    after = snapshot("overlap-after", "S04")
    assert_winner(after, staged)
    unchanged_prior(prior, after)

    prior = baseline("automatic")
    auto = call("automatic-retry", "run", "S06", fault="terminate_first_backend")
    committed(auto, "applied")
    assert auto.one("backend_terminated")["delivery"] == 1
    assert auto.one("delivery_interrupted")["delivery"] == 1
    assert [event["stored_receipt"] for event in auto.events("receipt_lookup")] == [None, None]
    assert auto.one("commit_returned")["delivery"] == 2
    after = snapshot("automatic-after", "S04")
    assert_winner(after, auto.one("commit_returned"))
    unchanged_prior(prior, after)

    prior = baseline("exhausted")
    exhausted = call("exhausted-retry", "run", "S06", status=1, fault="terminate_all_backends")
    assert exhausted.one("outcome")["status"] == "unknown"
    assert [event["delivery"] for event in exhausted.events("delivery_interrupted")] == [1, 2]
    assert [event["after_delivery"] for event in exhausted.events("receipt_lookup")] == [0, 1, 2]
    assert not exhausted.events("commit_returned")
    assert snapshot("exhausted-after", "S03") == prior

    prior = baseline("unavailable")
    unavailable = call("unavailable-reconcile", "run", "S06", status=1, fault="unavailable")
    assert unavailable.one("outcome")["status"] == "unknown"
    assert unavailable.one("receipt_lookup_failed")["after_delivery"] == 1
    assert unavailable.one("delivery_interrupted")["delivery"] == 1
    assert unavailable.one("claim_started")["delivery"] == 1
    after = snapshot("unavailable-committed", "S04")
    assert_winner(after, unavailable.one("commit_returned"))
    unchanged_prior(prior, after)
    restored = call("unavailable-restored", "run", "S06")
    committed(restored, "receipt")
    assert not restored.events("claim_started")
    assert snapshot("unavailable-after", "S04") == after
    print(f"S06 experiment passed in {monotonic() - start_time:.3f}s ({attempt} runner invocations)", flush=True)


def observe_claim_wait(holder_pid, claimant_pid):
    deadline = monotonic() + 1.5
    with connect("writer") as observer:
        while monotonic() < deadline:
            row = observer.execute("""
                SELECT pid, wait_event_type, wait_event, pg_blocking_pids(pid) AS blockers,
                       query ~ 'INSERT INTO fixture.scenario_receipts' AS claiming_receipt
                FROM pg_stat_activity WHERE pid = %s
            """, (claimant_pid,)).fetchone()
            if row and holder_pid in row["blockers"]:
                assert (row["wait_event_type"], row["wait_event"], row["claiming_receipt"]) == (
                    "Lock", "transactionid", True,
                ), row
                write_json(EVIDENCE / "overlap-source-wait.json", dict(
                    **row, holder_pid=holder_pid, observer_pid=observer.info.backend_pid,
                    utc=datetime.now(UTC).isoformat(),
                ))
                return
            sleep(0.02)
    raise AssertionError("second claim never waited on the first transaction")


def fault_child(fault, args):
    original_trace = runner.Trace.__call__
    refuse_connection = False

    def trace(self, event, **fields):
        nonlocal refuse_connection
        original_trace(self, event, **fields)
        if ((fault, event) in (("hold_before_commit", "commit_requested"),
                               ("hold_after_commit", "commit_returned"))):
            ready = select.select([sys.stdin], [], [], BARRIER_SECONDS)[0]
            if not ready or sys.stdin.readline() != "continue\n":
                raise runner.FixtureError("experiment barrier expired")
        if event == "commit_requested" and (
            fault == "terminate_all_backends"
            or (fault == "terminate_first_backend" and fields["delivery"] == 1)
        ):
            with connect("writer") as observer:
                result = observer.execute("SELECT pg_terminate_backend(%s, 1000) AS stopped",
                                          (fields["backend_pid"],)).fetchone()
                assert result["stopped"], fields
            original_trace(self, "backend_terminated", **fields)
        if fault == "unavailable" and event == "commit_returned":
            refuse_connection = True
            raise psycopg.OperationalError("injected loss after COMMIT returned")

    def fault_connect(role):
        if refuse_connection and role == "reader":
            # A real failed connection, scoped to this child and its unused loopback port.
            return psycopg.connect(host="127.0.0.1", port=1, connect_timeout=3)
        return connect(role)

    payload = s04_payload()
    if fault == "mismatch":
        payload["operations"][2]["row"]["amount_cents"] = 401
    # The production CLI exposes no fault options.
    with patch.object(runner.Trace, "__call__", trace), patch.object(replay, "connect", fault_connect), \
            patch.object(runner, "s04_payload", return_value=payload):
        return runner.main(args)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        sys.exit(fault_child(sys.argv[2], sys.argv[3:]))
    experiment(sys.argv[1])
