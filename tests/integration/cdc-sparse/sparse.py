"""Measure sparse publisher retention and a same-slot pre-apply crash."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cdc-gate"))

from gate import Gate, MIB, lsn, require  # noqa: E402

SPAN_LIMIT = 64 * MIB
HEADROOM_ALERT = 96 * MIB
HEADROOM_STOP = 64 * MIB
SWITCH_BUDGET = 17 * MIB
SILENT_SECONDS = 20
STAGE_SECONDS = 150


class Sparse(Gate):
    def setup(self):
        super().setup()
        delay = 5000
        if self.trial == "sparse-delayed-flush":
            # Change only the supported time trigger before any queues are created.
            # This widens the S03 crash window after the epoch-four item flush.
            delay = 12000
            self.sql("delayed flush setting", "SELECT duckpipe.set_config('flush_interval_ms', '12000');",
                     target=True)
        effective = self.sql("effective flush setting", "SELECT duckpipe.get_config('flush_interval_ms');",
                             target=True)
        require(effective == str(delay), "unexpected flush interval")
        self.event("setup", "flush_interval", milliseconds=delay)

    def slot_fingerprint(self):
        return self.sql("persistent slot and publication fingerprint", """
            SELECT s.slot_name, s.plugin, s.database, s.temporary, p.oid,
                   (SELECT count(*) FROM pg_replication_slots)
            FROM pg_replication_slots s CROSS JOIN pg_publication p;
        """)

    def budget(self, label, *, reserve=0):
        self.resources(label)
        pg = self.slot_sample(label)
        span = pg["wal_bytes"]["insert_to_restart"]
        headroom = pg["slot"]["safe_wal_size"]
        require(span is not None and span + reserve < SPAN_LIMIT, "retained WAL span stop")
        require(headroom is not None and headroom - reserve > HEADROOM_STOP, "slot headroom stop")
        if headroom <= HEADROOM_ALERT:
            self.event(label, "headroom_alert", bytes=headroom)
        return pg

    def epoch(self, number, start):
        label = f"sparse-{number}"
        require(time.monotonic() - start < STAGE_SECONDS, "sparse stage deadline before write")
        before = self.budget(f"{label}-before", reserve=SWITCH_BUDGET)
        state = self.group_state(f"{label}-before")
        positions = {row["source_table"]: row["applied_lsn"] for row in state["mappings"]}
        self.touch(label, """
            UPDATE fixture.orders SET status=status WHERE order_id=10 RETURNING order_id;
            UPDATE fixture.order_items SET quantity=quantity WHERE item_id=101 RETURNING item_id;
            UPDATE fixture.payments SET amount_cents=amount_cents WHERE payment_id=301 RETURNING payment_id;
        """, ["10", "101", "301"])
        committed = self.slot_sample(f"{label}-committed")
        self.sql("sparse segment switch and checkpoint", "SELECT pg_switch_wal(); CHECKPOINT;")
        deadline = min(time.monotonic() + 18, start + STAGE_SECONDS)
        while time.monotonic() < deadline:
            state = self.group_state(label)
            by_table = {row["source_table"]: row for row in state["mappings"]}
            idle = by_table.pop("fixture.customers")
            require(idle["applied_lsn"] == positions["fixture.customers"] and idle["queued_changes"] == 0,
                    "customer table did not remain idle")
            if len(by_table) == 3 and all(
                not row["queued_changes"] and row["applied_lsn"]
                and lsn(row["applied_lsn"]) >= lsn(before["positions"]["insert_lsn"])
                and (not positions[table] or lsn(row["applied_lsn"]) > lsn(positions[table]))
                for table, row in by_table.items()
            ):
                break
            time.sleep(.5)
        else:
            raise RuntimeError(f"{label} did not witness three durable advances")
        self.checkpoint(label, "S02")
        after = self.budget(f"{label}-after")
        require(before["slot"]["active"] and after["slot"]["active"]
                and after["slot"]["active_pid"] == before["slot"]["active_pid"],
                "sender changed during sparse epoch")
        self.event(label, "epoch_complete", committed=committed["positions"], slot=after["slot"],
                   wal_bytes=after["wal_bytes"])
        return after

    def fault_at_delete(self):
        self.budget("before-delete")
        lower = self.slot_sample("before-delete-commit")["positions"]["insert_lsn"]
        self.fixture("delete", "S03")
        require(not self.data("delete", "S03", "source"), "source delete differs")
        pending = False
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            state = self.group_state("delete-pending")
            if any(row["source_table"] == "fixture.order_items" and row["queued_changes"]
                   for row in state["mappings"]):
                pending = not self.data("delete-pending", "S02", "target")
                if pending:
                    break
            time.sleep(.15)
        offline = self.fault("delete-crash", kill=True)
        self.boot_consumer("delete-restart")
        status = self.group_state("delete-before-worker")
        require(not status["worker_pids"], "pre-worker read window missed")
        require(self.slot_fingerprint() == self.original_slot, "persistent publisher identity changed")
        stale = not self.data("delete-before-worker-old", "S02", "target")
        if stale:
            require(lsn(offline["slot"]["confirmed_flush_lsn"]) <= lsn(lower),
                    "feedback crossed the source delete lower bracket while Bronze retained the deleted row")
        else:
            require(not self.data("delete-before-worker-new", "S03", "target"),
                    "unexpected durable rows after crash")
        self.event("delete-crash", "apply_window", witnessed=pending and stale,
                   preworker_s02=stale, queued_and_old_sample=pending,
                   before_commit_insert_lsn=lower, offline_confirmed=offline["slot"]["confirmed_flush_lsn"])
        self.worker("delete-restart")
        self.checkpoint("delete-recovered", "S03")
        self.budget("delete-recovered")
        self.budget("before-S04")
        self.fixture("S04", "S04")
        self.checkpoint("S04", "S04")
        self.budget("before-S05")
        self.continued()
        self.budget("after-S05")
        return pending and stale

    def run(self):
        initial = self.before_fault()
        self.original_slot = self.slot_fingerprint()
        begin = time.monotonic()
        self.budget("before-first-burst")
        first = [self.epoch(number, begin) for number in range(1, 4)]
        self.event("silent", "hold_started", seconds=SILENT_SECONDS)
        time.sleep(SILENT_SECONDS)
        quiet = self.budget("silent-end")
        require(quiet["slot"]["active_pid"] == initial["slot"]["active_pid"], "sender changed across silence")
        self.checkpoint("silent-end", "S02")
        epoch_results = first + [self.epoch(4, begin)]
        require(time.monotonic() - begin < STAGE_SECONDS, "sparse stage deadline")
        crash_window = self.fault_at_delete()
        start_ack = lsn(initial["slot"]["confirmed_flush_lsn"])
        acks = [lsn(sample["slot"]["confirmed_flush_lsn"]) for sample in epoch_results]
        spans = [sample["wal_bytes"]["insert_to_restart"] for sample in epoch_results]
        span_grew_each_epoch = all(right > left for left, right in zip(
            [initial["wal_bytes"]["insert_to_restart"], *spans], spans))
        self.logs("sparse")
        self.remove_source_objects()
        self.save("sparse.json", dict(
            revision=os.environ["CDC_REVISION"],
            initial_confirmed=start_ack, epoch_confirmed=acks, epoch_retained_bytes=spans,
            progress_each_epoch=all(right > left for left, right in zip([start_ack, *acks], acks)),
            span_grew_each_epoch=span_grew_each_epoch, pre_apply_crash_witnessed=crash_window,
        ))
        self.event("final", "sparse_observations_complete")


if __name__ == "__main__":
    Sparse().run()
