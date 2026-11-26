"""Characterize source and DuckLake transaction boundaries on a fresh lab clone."""

from contextlib import contextmanager
from pathlib import Path
import json
import os
import subprocess
import sys
import time

from scripts.cdc.consumer.catalog import inspect as catalog
from scripts.cdc.parity import COLUMNS, customer_report, fixture_rows
from tests.fixture_oracle import compare_checkpoint, load_expectations

from reads import BEGIN, LineSession, decode_engine, decode_native, engine_capture, native_capture

# Import the reviewed EXP-017 lifecycle without editing its owned entry points.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cdc-baseline"))
from baseline import DEADLINE, TABLES, Experiment, require


EXPECTATIONS = load_expectations()
EXPECTATIONS["S05-A"] = dict(EXPECTATIONS["S05"], payments=EXPECTATIONS["S04"]["payments"])
EXPECTATIONS["S03-control"] = dict(
    EXPECTATIONS["S03"],
    order_items=[row for row in EXPECTATIONS["S05"]["order_items"] if row["item_id"] != 301],
    report=[{"customer_id": 1, "order_count": 1, "item_total_cents": 1200},
            {"customer_id": 2, "order_count": 1, "item_total_cents": 500}],
)
STATES = ("S03", "S03-control", "S04", "S05-A", "S05")
POLL = 0.2
OPEN_SECONDS = 1.5
AFTER_A_SECONDS = 2.0
QUIET_SECONDS = 10
NATIVE_WINDOW = 12
HISTORY_LIMIT = 32


def exact(checkpoint, rows):
    return not compare_checkpoint(EXPECTATIONS[checkpoint], rows)


def visibility(rows):
    return dict(
        order_30=any(row["order_id"] == 30 for row in rows["orders"]),
        item_301=any(row["item_id"] == 301 for row in rows["order_items"]),
        payment_302=any(row["payment_id"] == 302 for row in rows["payments"]),
        payment_303=any(row["payment_id"] == 303 for row in rows["payments"]),
        item_101_quantity=next((row["quantity"] for row in rows["order_items"]
                               if row["item_id"] == 101), None),
    )


class VisibilityExperiment(Experiment):
    def target_sample(self, label, sql, decode, timeout, session=None):
        started = time.monotonic_ns()
        try:
            if session is None:
                raw = self.checked(label, (*self.target, "-v", "VERBOSITY=verbose", "-f", "-"),
                                   data=sql, timeout=timeout)
                lines = raw.splitlines()
            else:
                lines = session.packet(sql, time.monotonic() + timeout)
            result = decode(lines)
        except Exception:
            self.event(label, "target_capture_failed", started_ns=started - self.start)
            raise
        self.event(label, "target_read_finished", started_ns=started - self.start,
                   visibility=visibility(result["rows"]),
                   exact=[name for name in STATES if exact(name, result["rows"])], **result)
        return result

    def engine(self, label, timeout=4, version=None):
        return self.target_sample(label, engine_capture(version),
                                  lambda lines: decode_engine(lines, version), timeout)

    def native(self, label, session):
        return self.target_sample(label, native_capture(), decode_native, 4, session=session)

    @contextmanager
    def native_session(self):
        with (self.evidence / "native-psql-errors.txt").open("ab") as errors:
            prefix = ("env", "CDC_SQL_TIMEOUT=28", *self.target)
            with LineSession((*prefix, "-v", "VERBOSITY=verbose", "-f", "-"),
                             stderr=errors) as session:
                session.send(BEGIN)
                yield session
                session.send("ROLLBACK;\n")

    def source_exact(self, label, checkpoint):
        rows = fixture_rows(self.read_source(5).rows)
        differences = compare_checkpoint(EXPECTATIONS[checkpoint], rows)
        self.event(label, "source_exact_state", expected=checkpoint, rows=rows, differences=differences)
        require(not differences, f"{label}: source {checkpoint} mismatch")

    @contextmanager
    def source_schedule(self, label, *scenario_args):
        self.attempt += 1
        code = Path(__file__).with_name("source_hold.py").read_text()
        runner = (*self.runner[:self.runner.index("fixture-runner")],
                  "--entrypoint", "timeout", "fixture-runner",
                  "--kill-after=2s", "40s", "python", "-Bu", "-c", code,
                  "--run-id", os.environ["RUNNER_ID"], "--attempt", str(self.attempt),
                  "run", *scenario_args)
        with LineSession(runner, stderr=subprocess.DEVNULL) as session:
            yield session

    def source_event(self, label, session, deadline):
        line = session.line(deadline)
        if line is not None:
            event = json.loads(line)
            with (self.evidence / f"{label}.runner.jsonl").open("a") as stream:
                stream.write(line + "\n")
            self.event(label, "source_schedule", runner_event=event)
            return event

    def source_gate(self, label, session, gate):
        deadline = time.monotonic() + 9
        while (event := self.source_event(label, session, deadline)) is not None:
            if event["event"] == gate:
                return event
        raise RuntimeError(f"{label}: source exited before reaching {gate}")

    def release(self, label, session, gate):
        self.event(label, "release_source_gate", gate=gate)
        session.send("release\n")
        return time.monotonic()

    def finish_schedule(self, label, session, expected_exit):
        deadline = time.monotonic() + 10
        events = []
        while (event := self.source_event(label, session, deadline)) is not None:
            events.append(event)
        require(session.process.wait(timeout=2) == expected_exit, f"{label}: unexpected source exit")
        resources = next(row["cgroup"] for row in events if row["event"] == "resources")
        require(resources["memory.max"] == "268435456" and resources["memory.swap.max"] == "0"
                and resources["cpu.max"] == "50000 100000"
                and all(line in resources["memory.events"].splitlines()
                        for line in ("oom 0", "oom_kill 0")), "runner cgroup bounds")
        return events

    def sample_hold(self, label, seconds, allowed, *, gate_budget=None):
        start = time.monotonic()
        count = 0
        while True:
            now = time.monotonic()
            budget = 4 if gate_budget is None else min(1.5, start + gate_budget - now)
            require(budget > 0, f"{label}: source hold observation exceeded its budget")
            capture = self.engine(label, budget)
            require(any(exact(name, capture["rows"]) for name in allowed),
                    f"{label}: unexpected target rows before source release")
            count += 1
            if time.monotonic() - start >= seconds:
                break
            time.sleep(POLL)
        self.event(label, "hold_observed", allowed=allowed, reads=count,
                   observed_seconds=time.monotonic() - start)

    def converge(self, label, checkpoint, stop=None, *, required=True):
        deadline = stop if stop is not None else time.monotonic() + DEADLINE
        while (remaining := deadline - time.monotonic()) > 0.15:
            capture = self.engine(label, timeout=min(4, remaining))
            if time.monotonic() <= deadline and exact(checkpoint, capture["rows"]):
                self.event(label, "first_exact_engine_read", expected=checkpoint,
                           snapshot_id=capture["snapshot_id"], rows=capture["rows"])
                return capture
            time.sleep(min(POLL, max(0, deadline - time.monotonic())))
        if required:
            raise RuntimeError(f"{label}: exact {checkpoint} not seen before deadline")

    def history(self, label, start):
        raw = self.sql(label, f"""
            SELECT json_build_object('snapshot_id', s.snapshot_id,
                                     'snapshot_time', s.snapshot_time,
                                     'changes', c.changes_made)
            FROM ducklake.ducklake_snapshot s
            LEFT JOIN ducklake.ducklake_snapshot_changes c USING (snapshot_id)
            WHERE s.snapshot_id >= {start}
            ORDER BY s.snapshot_id LIMIT {HISTORY_LIMIT + 1};
        """, target=True)
        entries = [json.loads(row) for row in raw.splitlines()]
        ids = [row["snapshot_id"] for row in entries]
        require(1 <= len(ids) <= HISTORY_LIMIT and ids == sorted(set(ids)) and ids[0] == start,
                f"{label}: invalid, expired or overflowing catalog range")
        self.event(label, "retained_catalog_versions", entries=entries)
        return [self.engine(f"{label}-version-{version}", version=version) for version in ids]

    def first_exact_version(self, label, history, checkpoint):
        first = next((row for row in history if exact(checkpoint, row["rows"])), None)
        require(first is not None and exact(checkpoint, history[-1]["rows"]),
                f"{label}: {checkpoint} is not reproducible at the final retained version")
        self.event(label, "first_exact_retained_version", expected=checkpoint,
                   snapshot_id=first["snapshot_id"], rows=first["rows"])
        return first

    def held_native(self, old, new, first, last):
        before, after = first["pg_before"], last["pg_after"]
        require(before["backend_pid"] == after["backend_pid"]
                and before["pg_snapshot"] == after["pg_snapshot"], "lost native RR boundary")
        engine_ids = [first["engine_before"], first["engine_after"],
                      last["engine_before"], last["engine_after"]]
        self.event("S04", "native_repeatable_read_crossed_target_apply",
                   first_exact=exact(old, first["rows"]), last_exact=exact(old, last["rows"]),
                   engine_ids=engine_ids, pinned_by_fixture_control=
                   first["rows"] == last["rows"] == EXPECTATIONS[old]
                   and engine_ids == [before["catalog_head"]] * 4
                   and new["snapshot_id"] > before["catalog_head"])

    def split_control(self, old, new):
        raw = {table: (new if table == "order_items" else old)["rows"][table] for table in COLUMNS}
        versions = {table: (new if table == "order_items" else old)["snapshot_id"] for table in COLUMNS}
        rows = dict(raw, report=customer_report(raw))
        self.event("S04", "intentional_cross_version_control", versions=versions,
                   rows=rows, visibility=visibility(rows))

    def rollback_control(self, start):
        label = "S04-abort-disjoint-commit"
        # Item 101 is outside the aborted S04 key set. Force CDC to apply a
        # later real change, then verify aborted keys are still absent.
        output = self.sql(label, """
            BEGIN;
            SET LOCAL ROLE source_fixture_writer;
            SET LOCAL synchronous_commit = on;
            UPDATE fixture.order_items SET quantity = 4, updated_at = '2026-01-01T00:05:00Z'
            WHERE item_id = 101 RETURNING item_id, pg_current_xact_id()::text;
            COMMIT;
        """)
        key, xid = output.split("|")
        require(key == "101" and xid.isdecimal(), "disjoint rollback control did not update item 101")
        self.event(label, "commit_acknowledged", key=int(key), xid=xid)
        self.source_exact(label, "S03-control")
        self.converge(label, "S03-control")
        history = self.history(label, start)
        require(all(any(exact(name, row["rows"]) for name in ("S03", "S03-control"))
                    for row in history), "aborted S04 changed a retained snapshot")
        self.first_exact_version(label, history, "S03-control")

    def s04(self, rollback):
        label = "S04-abort" if rollback else "S04-commit"
        options = ("--rollback",) if rollback else ()
        initial = self.engine(f"{label}-before")
        require(exact("S03", initial["rows"]), "S04 predecessor")
        self.wal(f"{label}-before")
        self.status(f"{label}-before")
        observed = None
        with self.native_session() as held:
            first = self.native(f"{label}-held-native-before", held)
            require(exact("S03", first["rows"]), "native S04 predecessor")
            with self.source_schedule(label, "S04", *options) as session:
                gate = self.source_gate(label, session, "before_commit")
                require(gate["transaction_statuses"] == {"S04": "in progress"}
                        and gate["identity"]["xid"] and not gate["differences"],
                        "missing exact source S04 hold evidence")
                self.sample_hold(f"{label}-open", OPEN_SECONDS, ("S03",))
                require(exact("S03", self.native(f"{label}-held-native-open", held)["rows"]),
                        "uncommitted S04 visible to native reader")
                released = self.release(label, session, "before_commit")
                events = self.finish_schedule(label, session, 0)
                outcome = "rolled_back" if rollback else "commit_acknowledged"
                require(any(row["event"] == outcome and row["xid"] == gate["identity"]["xid"]
                            for row in events), f"missing S04 {outcome}")
            if not rollback:
                observed = self.converge(label, "S04", stop=released + NATIVE_WINDOW, required=False)
                if observed is not None:
                    last = self.native(f"{label}-held-native-after", held)
                    self.held_native("S03", observed, first, last)
                else:
                    self.event(label, "native_crossing_inconclusive", deadline_s=NATIVE_WINDOW)
        stop_checkpoint = "S03" if rollback else "S04"
        self.source_exact(label, stop_checkpoint)
        if rollback:
            self.sample_hold(f"{label}-post", QUIET_SECONDS, ("S03",))
        elif observed is None:
            self.converge(label, "S04", stop=released + DEADLINE)
        with self.native_session() as fresh:
            require(exact(stop_checkpoint, self.native(f"{label}-fresh-native", fresh)["rows"]),
                    f"{label}: native reader does not match {stop_checkpoint}")
        history = self.history(label, initial["snapshot_id"])
        require(exact("S03", history[0]["rows"]), f"{label}: retained S03 predecessor mismatch")
        if rollback:
            require(all(exact("S03", row["rows"]) for row in history), "historical rollback leak")
            self.rollback_control(initial["snapshot_id"])
        else:
            final = self.first_exact_version(label, history, "S04")
            self.split_control(history[0], final)
        self.wal(label)
        self.status(label)
        self.resources(label)

    def s05(self, abort_b):
        label = "S05-abort-B" if abort_b else "S05-commit"
        options = ("--s05-fault", "after-a-commit") if abort_b else ()
        initial = self.engine(f"{label}-before")
        require(exact("S04", initial["rows"]), "S05 predecessor")
        self.wal(f"{label}-before")
        self.status(f"{label}-before")
        with self.source_schedule(label, "S05", *options) as session:
            both = self.source_gate(label, session, "both_open")
            require(both["transaction_statuses"] == {"A": "in progress", "B": "in progress"},
                    "missing both-open source barrier")
            self.sample_hold(f"{label}-both-open", OPEN_SECONDS, ("S04",), gate_budget=3)
            self.release(label, session, "both_open")
            a_only = self.source_gate(label, session, "a_only")
            require(a_only["transaction_statuses"] == {"A": "committed", "B": "in progress"},
                    "missing A-only source barrier")
            self.sample_hold(f"{label}-A-committed-B-open", AFTER_A_SECONDS,
                             ("S04", "S05-A"), gate_budget=3)
            self.release(label, session, "a_only")
            events = self.finish_schedule(label, session, 1 if abort_b else 0)
        final_event = "failure_state" if abort_b else "after_commit"
        statuses = {"A": "committed", "B": "aborted" if abort_b else "committed"}
        checkpoint = "S05-A" if abort_b else "S05"
        require(any(row["event"] == final_event and row["checkpoint"] == checkpoint
                    and row["transaction_statuses"] == statuses and not row["differences"]
                    for row in events), f"{label}: missing exact terminal source state")
        self.converge(label, checkpoint)
        self.source_exact(label, checkpoint)
        self.sample_hold(f"{label}-post", QUIET_SECONDS, (checkpoint,))
        with self.native_session() as fresh:
            require(exact(checkpoint, self.native(f"{label}-fresh-native", fresh)["rows"]),
                    f"{label}: native reader does not match {checkpoint}")
        history = self.history(label, initial["snapshot_id"])
        require(exact("S04", history[0]["rows"]), f"{label}: retained S04 predecessor mismatch")
        self.first_exact_version(label, history, checkpoint)
        if abort_b:
            require(all(exact("S04", row["rows"]) or exact("S05-A", row["rows"]) for row in history),
                    "aborted B changed a retained snapshot")
        self.wal(label)
        self.status(label)
        self.resources(label)

    def run(self):
        self.setup()
        self.create()
        for table in TABLES:
            self.register(table)
            self.initial(table, "S00")
        self.inventory()
        self.checkpoint("S00", "S00")
        for step in ("S01", "S02", "S03"):
            self.fixture(step, step)
            self.checkpoint(step, step)
        rollback = self.trial == "rollback"
        self.s04(rollback)
        if not rollback:
            self.s05(self.trial == "overlap-abort")
        self.save("catalog.json", catalog(self.consumer_id))
        self.wal("final")
        self.status("final")
        self.resources("final")
        self.remove_source_objects()
        self.event("final", "experiment_passed")


if __name__ == "__main__":
    VisibilityExperiment().run()
