"""COPY handoff experiment using the existing fixture and independent parity reads."""

import json
import os
from pathlib import Path
import re
import subprocess
import time

from baseline import DEADLINE, DOCKER, POLL, SOURCE_PSQL, TABLES, TARGET, Experiment, require
from scripts.cdc.parity import ReadTimeout, fixture_rows, verify_checkpoint, write_evidence
from scripts.cdc.parity.psql import read_fixture
from tests.fixture_oracle import compare_checkpoint, load_expectations


class CopyBoundary(Experiment):
    def __init__(self):
        super().__init__()
        self.schedule = os.environ["COPY_SCHEDULE"]

    def positions(self, label):
        slots = self.sql("slot position trace", """
            SELECT s.slot_name, s.temporary, s.active_pid, s.restart_lsn,
                   s.confirmed_flush_lsn, a.backend_xmin,
                   CASE WHEN NOT s.temporary AND a.query LIKE 'START_REPLICATION SLOT %'
                        THEN substring(a.query FROM ' LOGICAL ([0-9A-F]+/[0-9A-F]+)') END
            FROM pg_replication_slots s LEFT JOIN pg_stat_activity a ON a.pid = s.active_pid
            ORDER BY s.temporary LIMIT 3;
        """).splitlines()
        self.event(label, "slot_positions", slots=slots)
        return slots

    def commit_s01(self):
        start = self.sql("pre-commit WAL", "SELECT pg_current_wal_insert_lsn();")
        self.fixture("during-copy", "S01")
        end = self.sql("post-commit WAL", "SELECT pg_current_wal_insert_lsn();")
        events = (self.evidence / "during-copy.runner.jsonl").read_text().splitlines()
        xid = next(row["xid"] for row in map(json.loads, events)
                   if row["event"] == "commit_acknowledged")
        require(xid.isdecimal() and int(xid) <= 0xFFFFFFFF, "expected a fresh cluster XID")
        require(all(re.fullmatch(r"[0-9A-F]+/[0-9A-F]+", lsn) for lsn in (start, end)),
                "invalid WAL bracket")
        source = fixture_rows(self.read_source(8).rows)
        diffs = compare_checkpoint(load_expectations()["S01"], source)
        self.save("S01.source-at-commit.json", dict(rows=source, diffs=diffs))
        require(not diffs, "independent source S01 mismatch")
        self.event("copy-window", "exact_source_s01", xid=xid, wal_start=start, wal_end=end)
        return xid, start, end

    def dump_s01(self, xid, start, end):
        # Read the active lab's WAL with a bounded XID and interval. No decoder
        # slot is needed. Keep record headers and types, excluding payload text.
        raw = self.checked("S01 WAL records", (
            *DOCKER, "exec", "--user", "postgres", self.source_id, "sh", "-ec",
            'exec pg_waldump -p "$PGDATA/pg_wal" -s "$1" -e "$2" -x "$3" -n 12',
            "sh", start, end, xid,
        ))
        records = []
        for line in raw.splitlines():
            match = re.match(r"rmgr:\s*(\w+)\s+len \(rec/tot\):\s*(\d+)/\s*(\d+),"
                             r"\s+tx:\s*(\d+), lsn: ([0-9A-F/]+),"
                             r" prev [0-9A-F/]+, desc: (\w+)", line)
            require(match and match[4] == xid, "unexpected WAL record header")
            records.append(dict(resource=match[1], bytes=int(match[3]), lsn=match[5], kind=match[6]))
        require(any(row["kind"] == "INSERT" for row in records)
                and sum(row["kind"] == "COMMIT" for row in records) == 1,
                "S01 insert and commit WAL records missing")
        self.save("S01.wal.json", dict(xid=xid, start=start, end=end, records=records))

    def target_s01(self, deadline):
        def read_target(budget):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ReadTimeout("COPY convergence deadline expired")
            capture = read_fixture(self.target_reader, TARGET, min(budget, remaining, 8))
            if time.monotonic() >= deadline:
                raise ReadTimeout("COPY result exceeded the convergence deadline")
            return capture

        remaining = deadline - time.monotonic()
        require(remaining > 0, "COPY evidence consumed the target deadline")
        result = verify_checkpoint(self.trial, "S01", self.read_source, read_target,
                                   target_timeout=remaining, interval=POLL)
        write_evidence(self.evidence / "copy-window", result)
        self.event("copy-window", "exact_target" if result.passed else "parity_failed",
                   source=result.source.status, target=result.target.status,
                   attempts=result.target_attempts)
        self.status("copy-parity")
        require(result.passed, "COPY S01 parity deadline missed")

    def capture_connector_trace(self):
        # Match only ticket-specific numeric traces and the two existing snapshot
        # announcements. Container log output may otherwise contain conninfo.
        proc = subprocess.run((*DOCKER, "logs", "--tail", "1500", self.consumer_id),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, timeout=8, check=True)
        pattern = re.compile(
            r"(COPY212 [A-Za-z0-9_= /.,:-]+|(?:Starting chunked COPY snapshot|Snapshot complete)"
            r" for fixture\.order_items:? (?:[0-9]+ rows copied )?\(consistent_point=[0-9A-F/]+\))"
        )
        lines = [match[0] for line in proc.stdout.splitlines() if (match := pattern.search(line))]
        self.save("connector-copy.json", lines[-200:])

    def copy_window(self):
        self.event("copy-window", "schedule", name=self.schedule)
        self.positions("before-order-items")
        if self.schedule == "before-slot":
            committed = self.commit_s01()
            self.register(TABLES[-1])
            deadline = time.monotonic() + DEADLINE
        elif self.schedule == "after-copy":
            self.register(TABLES[-1])
            self.initial(TABLES[-1], "S00")
            self.positions("after-copy-before-commit")
            committed = self.commit_s01()
            deadline = time.monotonic() + DEADLINE
        else:
            committed, deadline = self.overlap()
        try:
            self.dump_s01(*committed)
            self.target_s01(deadline)
            require(len(self.positions("after-S01")) == 1, "temporary COPY slot remains after parity")
            self.inventory()
            self.item_102_dml()
        finally:
            self.capture_connector_trace()

    def overlap(self):
        self.sql("install copy barrier", Path(__file__).with_name("copy-hold.sql").read_text(),
                 variables=("-v", f"publisher={self.publisher}"))
        holder_command = (*DOCKER, "exec", "-i", "--user", "postgres", self.source_id,
                          "timeout", "-k", "1s", "45s", "sh", "-ec", SOURCE_PSQL,
                          "sh", "-At", "-f", "-")
        with subprocess.Popen(holder_command, text=True, stdin=subprocess.PIPE,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as holder:
            try:
                holder.stdin.write("""
                    SET application_name = 'exp017_copy_holder';
                    SET idle_in_transaction_session_timeout = '40s';
                    BEGIN;
                    SELECT pg_advisory_xact_lock(17026, 1);
                """)
                holder.stdin.flush()
                self.wait_copy("holder", 5)
                self.register(TABLES[-1])
                before = self.wait_copy("blocked", 12)
                require(before, "inconclusive: COPY/advisory wait and temporary slot unobserved")
                self.positions("blocked-before-S01")
                committed = self.commit_s01()
                if self.schedule == "delayed":
                    time.sleep(3)
                self.positions("blocked-after-S01")
                self.status("blocked-after-S01")
                after = self.copy_probe()
                require(after == before, "inconclusive: COPY/session/slot changed across S01")
                self.event("copy-window", "same_copy_blocked_after_commit", session=after)
            finally:
                # Disconnect to roll back the holder even when an assertion fails.
                holder.stdin.close()
                try:
                    require(holder.wait(timeout=6) == 0, "source advisory holder failed")
                except subprocess.TimeoutExpired:
                    holder.kill()
                    holder.wait()
                    raise RuntimeError("advisory holder release timed out") from None
                deadline = time.monotonic() + DEADLINE
                self.event("copy-window", "advisory_hold_released")
        return committed, deadline


if __name__ == "__main__":
    CopyBoundary().run()
