"""Run isolated graceful, abrupt and publisher WAL-loss experiments."""

from dataclasses import replace
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cdc-baseline"))
from baseline import Experiment, POLL, TABLES, TARGET, catalog, require  # noqa: E402
from scripts.cdc.parity import compare, fixture_rows  # noqa: E402
from scripts.cdc.parity.psql import read_fixture  # noqa: E402
from scripts.cdc.wal.observe import DOCKER  # noqa: E402
from scripts.isolation.preflight import check_firewall  # noqa: E402

MIB = 1024 * 1024
LOSS_SWITCHES = 11
LOSS_SPAN = 11 * 16 * MIB
ORDINARY_SPAN = 16 * MIB
STATE = '{{.State.Status}} {{.State.ExitCode}} {{.State.OOMKilled}}'
INSPECT = (
    '{{.Id}} {{.Image}} {{index .Config.Labels "com.docker.compose.project"}} '
    '{{index .Config.Labels "com.docker.compose.service"}} {{.HostConfig.Privileged}} '
    '{{len .NetworkSettings.Networks}} {{range .NetworkSettings.Networks}}{{.NetworkID}}{{end}} '
    '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}}:{{.Destination}}{{end}}{{end}}'
)
VOLUME = (
    '{{.Name}} {{.CreatedAt}} {{index .Labels "com.docker.compose.project"}} '
    '{{index .Labels "com.docker.compose.volume"}}'
)
STATUS = "scripts/cdc/consumer/status.sh"


def lsn(value):
    high, low = value.split("/")
    return (int(high, 16) << 32) + int(low, 16)


class Recovery(Experiment):
    def __init__(self):
        super().__init__()
        self.compose = (*DOCKER, "compose", "-f", "compose.source.yaml", "-f", "compose.cdc.yaml",
                        "--profile", "source", "--profile", "cdc")
        self.volume = f"{self.project}_cdc-pg"

    def docker(self, *args, timeout=10):
        return self.checked("docker " + " ".join(args[:2]), (*DOCKER, *args), timeout=timeout).strip()

    def slot_sample(self, label, *, allow_loss=False):
        self.observer.source = replace(self.observer.source, slot=self.slot,
                                       publication=self.publication, members=self.members)
        sample = self.observer.sample(self.trial, label)
        self.event(label, "publisher_sample", sample=sample)
        require(sample["error"] is None, f"publisher sample: {sample['error']}")
        pg = sample["postgresql"]
        slot = pg["slot"]
        require(allow_loss or slot["wal_status"] in ("reserved", "extended"), "required WAL unavailable")
        return pg

    def group_state(self, label, *, allow_error=False):
        if not allow_error:
            data = self.status(label)
        else:
            raw = self.checked("connector status", ("bash", STATUS, self.consumer_id, self.group,
                               self.run_id, label, str((time.monotonic_ns() - self.start) // 1_000_000)))
            data = json.loads(raw)
            self.event(label, "connector_sample", sample=data)
        identity = self.group_sql("persisted mapping identity", """
            SELECT g.id, g.name, g.publication, g.slot_name, g.enabled,
                   string_agg(m.id::text || ':' || m.source_table, ',' ORDER BY m.id)
            FROM duckpipe.sync_groups g JOIN duckpipe.table_mappings m ON m.group_id=g.id
            WHERE g.name=:'group' GROUP BY g.id;
        """)
        require(identity == self.group_identity, "persistent group or mapping IDs changed")
        return data

    def consumer_identity(self, *, running):
        actual = self.docker("inspect", "-f", INSPECT, self.consumer_id).split()
        prefix = [self.consumer_id, self.consumer_image, self.project, "cdc-catalog", "false", "1"]
        # The stopped network attachment retains only its network key. Docker
        # may leave NetworkID blank until the container starts again.
        tail = [self.bridge, f"{self.volume}:/var/lib/postgresql"]
        require(actual == prefix + tail or (not running and actual == prefix + tail[1:]),
                "consumer runtime identity changed")
        volume = self.docker("volume", "inspect", "-f", VOLUME, self.volume)
        require(volume.split()[0] == self.volume and volume.endswith(f" {self.project} cdc-pg"),
                "consumer volume ownership")
        require(not self.docker("port", self.consumer_id), "consumer has a published port")
        check_firewall(os.environ["BRIDGE"])
        return volume

    def wait_active(self, label, active):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            pg = self.slot_sample(label)
            if pg["slot"]["active"] is active:
                return pg
            time.sleep(POLL)
        raise RuntimeError(f"slot activity did not reach {active}")

    def data(self, label, step, side):
        capture = self.read_source(8) if side == "source" else read_fixture(self.target_reader, TARGET, 8)
        rows = fixture_rows(capture.rows)
        diffs = compare(self.trial, step, side, rows)
        self.save(f"{label}.{side}.json", dict(rows=rows, diffs=diffs,
                  reader_semantics=capture.reader_semantics, read_by_utc=datetime.now(UTC).isoformat()))
        self.event(label, "independent_read", side=side, expected=step, diffs=diffs)
        return diffs

    def logs(self, name):
        # Save selected, structured log fields only. Raw logs may contain conninfo.
        selectors = {
            "publisher": (self.source_id, {
                "start_replication": r"START_REPLICATION SLOT [\"a-z_0-9]+ LOGICAL [0-9A-F]+/[0-9A-F]+",
                "slot_invalidated": r"invalidating obsolete replication slot \"[a-z_0-9]+\"",
                "lost_reconnect": r"can no longer get changes from replication slot \"[a-z_0-9]+\"",
                "removed_wal": r"requested WAL segment [0-9A-F]+ has already been removed",
            }),
            "consumer": (self.consumer_id, {
                "invalid_slot": r"can no longer get changes from replication slot \"[a-z_0-9]+\"",
                "removed_wal": r"requested WAL segment [0-9A-F]+ has already been removed",
                "upstream_disconnect": r"replication (?:stream|connection) (?:error|failed)",
                "database_interrupted": r"database system was interrupted",
                "redo_start": r"redo starts at [0-9A-F]+/[0-9A-F]+",
            }),
        }
        records = []
        for role, (cid, patterns) in selectors.items():
            raw = self.checked(f"{role} bounded logs", (*DOCKER, "logs", "--timestamps", "--tail", "400", cid),
                               merge_streams=True)
            for line in raw.splitlines():
                utc = re.match(r"[0-9T:.Z-]+ ", line)
                if utc is None:
                    continue
                for kind, pattern in patterns.items():
                    match = re.search(pattern, line, re.I)
                    if match:
                        records.append(dict(role=role, kind=kind, detail=match[0], utc=utc[0].strip()))
        self.save(f"{name}.logs.json", records)
        return records

    def checked(self, label, args, *, data=None, timeout=10, merge_streams=False):
        if not merge_streams:
            return super().checked(label, args, data=data, timeout=timeout)
        try:
            result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"{label} timed out") from None
        require(result.returncode == 0 and len(result.stdout) <= 524288, f"{label} failed")
        return result.stdout

    def fault(self, label, *, kill=False):
        check_firewall(os.environ["BRIDGE"])
        require(self.consumer_identity(running=True) == self.original_volume, "pre-fault volume mismatch")
        self.event(label, "fault_requested", signal="SIGKILL" if kill else "docker stop --time=12")
        if kill:
            self.docker("kill", "--signal=KILL", self.consumer_id)
        else:
            self.docker("stop", "--time=12", self.consumer_id, timeout=16)
        expected = "exited 137 false" if kill else "exited 0 false"
        require(self.docker("inspect", "-f", STATE, self.consumer_id) == expected, "unexpected fault exit")
        self.event(label, "consumer_down", state=expected, consumer=self.consumer_id)
        self.offline_started = time.monotonic()
        return self.wait_active(label, False)

    def offline_step(self, step):
        label = f"offline-{step}"
        require(time.monotonic() - self.offline_started < 35, "offline write deadline")
        baseline = self.slot_sample(label)
        require(not baseline["slot"]["active"], "consumer no longer offline")
        require(baseline["wal_bytes"]["insert_to_restart"] < ORDINARY_SPAN, "ordinary WAL write budget")
        self.fixture(label, step)
        require(not self.data(label, step, "source"), "offline source checkpoint differs")
        result = self.slot_sample(label)
        require(not result["slot"]["active"] and result["wal_bytes"]["insert_to_restart"] < ORDINARY_SPAN,
                "offline WAL budget crossed")
        require(result["slot"]["confirmed_flush_lsn"] == baseline["slot"]["confirmed_flush_lsn"],
                "inactive slot acknowledged WAL")

    def boot_consumer(self, label):
        require(self.consumer_identity(running=False) == self.original_volume, "offline volume changed")
        check_firewall(os.environ["BRIDGE"])
        self.event(label, "same_container_start_requested")
        self.docker("start", self.consumer_id, timeout=16)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.docker("inspect", "-f", '{{.State.Health.Status}}', self.consumer_id) == "healthy":
                break
            time.sleep(POLL)
        else:
            raise RuntimeError("consumer SQL health did not return")
        require(self.consumer_identity(running=True) == self.original_volume, "restarted volume changed")
        state = self.sql("restarted cluster", "SELECT system_identifier FROM pg_control_system();", target=True)
        require(state == self.consumer_system, "consumer data directory changed")
        self.event(label, "consumer_health_returned", system_identifier=state, volume=self.original_volume)
        return self.group_state(label)

    def worker(self, label, *, expect_active=True):
        self.group_sql("start existing worker", "SELECT duckpipe.start_worker(:'group');")
        self.event(label, "start_worker_requested")
        if expect_active:
            self.wait_active(label, True)
            self.group_state(label)

    def onboard(self, step, label):
        self.create()
        for table in TABLES:
            self.register(table)
            self.initial(table, step)
        self.inventory()
        self.checkpoint(label, step)

    def before_fault(self):
        self.setup()
        self.sql("enable scoped replication log", f"ALTER ROLE {self.publisher} SET log_replication_commands=on;")
        self.onboard("S00", "S00")
        for step in ("S01", "S02"):
            self.fixture(step, step)
            self.checkpoint(step, step)
        pg = self.wait_active("before-fault", True)
        self.consumer_image = next(line.split("@", 1)[1].strip() for line in
                                   Path("compose.cdc.yaml").read_text().splitlines() if line.startswith("    image: "))
        self.original_volume = self.consumer_identity(running=True)
        self.consumer_system = self.sql("consumer system ID", "SELECT system_identifier FROM pg_control_system();",
                                        target=True)
        self.group_identity = self.group_sql("initial persistent group identity", """
            SELECT g.id, g.name, g.publication, g.slot_name, g.enabled,
                   string_agg(m.id::text || ':' || m.source_table, ',' ORDER BY m.id)
            FROM duckpipe.sync_groups g JOIN duckpipe.table_mappings m ON m.group_id=g.id
            WHERE g.name=:'group' GROUP BY g.id;
        """)
        self.event("before-fault", "fault_identity", group=self.group_identity, volume=self.original_volume,
                   system_identifier=self.consumer_system, image=self.consumer_image,
                   last_verified_target="S02/target.snapshot.json")
        return pg

    def continued(self):
        self.attempt += 1
        self.event("continued-S05", "runner_started", scenario="S05")
        raw = self.checked("Phase 1 ordered S05 runner",
                           (*self.runner, "--attempt", str(self.attempt), "run", "S05"), timeout=50)
        (self.evidence / "continued-S05.runner.jsonl").write_text(raw)
        rows = [json.loads(line) for line in raw.splitlines()]
        commits = [row for row in rows if row["event"] == "commit_acknowledged"]
        require([row["transaction"] for row in commits] == ["A", "B"], "S05 commit order changed")
        for row in commits:
            self.event("continued-S05", "commit_acknowledged", runner_event=row)
        cgroup = next(row["cgroup"] for row in rows if row["event"] == "resources")
        require(cgroup["memory.max"] == "268435456" and cgroup["memory.swap.max"] == "0"
                and cgroup["cpu.max"] == "50000 100000"
                and all(line in cgroup["memory.events"].splitlines()
                        for line in ("oom 0", "oom_kill 0")), "S05 runner cgroup bounds")
        self.checkpoint("continued-S05", "S05")
        require(not self.data("fresh-S05", "S05", "target"), "fresh post-S05 target differs")

    def graceful(self):
        before = self.fault("graceful-fault")
        self.offline_step("S03")
        self.offline_step("S04")
        offline = self.slot_sample("graceful-offline")
        require(offline["slot"]["confirmed_flush_lsn"] == before["slot"]["confirmed_flush_lsn"],
                "slot feedback changed while offline")
        status = self.boot_consumer("graceful-restart")
        if not status["worker_pids"]:
            require(not self.data("graceful-restart-before-worker", "S02", "target"),
                    "last verified target S02 did not survive graceful interruption")
        self.worker("graceful-restart")
        self.checkpoint("recovered-S04", "S04")
        self.continued()

    def touch(self, label, statements, keys):
        # These narrow source-only UPDATEs emit WAL while leaving every fixture
        # field unchanged. They use the existing table owner's permissions.
        sql = "BEGIN; SET LOCAL ROLE source_fixture_owner; SET LOCAL synchronous_commit=on;"
        sql += statements + " COMMIT;"
        returned = self.sql(label, sql).splitlines()
        require(returned == keys, f"{label} did not update the exact predeclared keys")
        self.event(label, "source_noop_commit", keys=returned)

    def sparse_control(self, before):
        upper = before["positions"]["insert_lsn"]
        self.touch("three-tables", """
            UPDATE fixture.orders SET status=status WHERE order_id=10 RETURNING order_id;
            UPDATE fixture.payments SET amount_cents=amount_cents WHERE payment_id=301 RETURNING payment_id;
            UPDATE fixture.order_items SET quantity=quantity WHERE item_id=101 RETURNING item_id;
        """, ["10", "301", "101"])
        deadline = time.monotonic() + 18
        while time.monotonic() < deadline:
            progress = self.status("sparse-customer")
            maps = {m["source_table"]: m for m in progress["mappings"]}
            if all(maps[f"fixture.{table}"]["applied_lsn"] and
                   lsn(maps[f"fixture.{table}"]["applied_lsn"]) >= lsn(upper)
                   for table in TABLES if table != "customers"):
                break
            time.sleep(POLL)
        else:
            self.event("sparse-customer", "noncustomer_apply_threshold_unobserved", upper=upper)
        sparse = self.slot_sample("sparse-customer")
        require(not self.data("sparse-customer", "S02", "target"), "no-op control changed Bronze rows")
        self.touch("touch-customer", """
            UPDATE fixture.customers SET name=name WHERE customer_id=1 RETURNING customer_id;
        """, ["1"])
        deadline = time.monotonic() + 22
        while time.monotonic() < deadline:
            pg = self.slot_sample("customer-feedback")
            progress = self.status("customer-feedback")
            confirmed = pg["slot"]["confirmed_flush_lsn"]
            if lsn(confirmed) >= lsn(upper) and lsn(confirmed) > lsn(sparse["slot"]["confirmed_flush_lsn"]):
                require(not self.data("acknowledged-S02", "S02", "target"), "acked target S02 differs")
                self.event("acknowledged-S02", "feedback_covers_post_commit_upper_bound",
                           confirmed=confirmed, upper=upper, group=progress["group"]["confirmed_lsn"])
                return confirmed
            time.sleep(POLL)
        self.event("acknowledged-S02", "feedback_threshold_unobserved",
                   upper=upper, confirmed=confirmed)
        return None

    def abrupt(self, before):
        confirmed = self.sparse_control(before)
        self.resources("before-crash")
        self.fixture("buffer-S03", "S03")
        require(not self.data("buffer-S03", "S03", "source"), "source S03 differs")
        deadline = time.monotonic() + 6
        queued = False
        while time.monotonic() < deadline:
            status = self.status("buffer-S03")
            if any(m["source_table"] == "fixture.order_items" and m["queued_changes"]
                   for m in status["mappings"]):
                queued = not self.data("buffer-before-kill", "S02", "target")
                if queued:
                    self.event("buffer-S03", "observed_buffered_work_and_exact_old_target")
                    break
            time.sleep(.15)
        if not queued:
            self.event("buffer-S03", "inconclusive_buffer_window")
        self.fault("abrupt-fault", kill=True)
        self.offline_step("S04")
        status = self.boot_consumer("abrupt-restart")
        old_target_survived = False
        if not status["worker_pids"]:
            # S03 may have crossed the apply boundary between the last sample
            # and SIGKILL. Accept either exact committed predecessor here.
            for step in ("S02", "S03"):
                if not self.data(f"before-worker-{step}", step, "target"):
                    old_target_survived = True
                    self.event("abrupt-restart", "committed_target_survived_before_worker",
                               step=step, covered_s02_feedback=confirmed, buffered_sample=queued)
                    break
            require(old_target_survived, "unexpected pre-worker Bronze after crash")
        else:
            self.event("abrupt-restart", "inconclusive_pre_worker_read", reason="worker already started")
        self.worker("abrupt-restart")
        self.checkpoint("recovered-S04", "S04")
        self.continued()
        self.logs("abrupt-recovery")

    def force_wal_loss(self):
        settings = self.sql("retention settings", """
            SELECT current_setting('wal_segment_size'), current_setting('max_slot_wal_keep_size'),
                   current_setting('wal_keep_size'), current_setting('archive_mode');
        """)
        require(settings == "16MB|128MB|0|off", "unexpected settings for switch budget")
        self.event("retention", "effective_wal_settings", settings=settings,
                   max_switches=LOSS_SWITCHES, max_span_bytes=LOSS_SPAN)
        deadline = time.monotonic() + 50
        for switch in range(1, LOSS_SWITCHES + 1):
            before = self.slot_sample(f"before-switch-{switch}", allow_loss=True)
            span = before["wal_bytes"]["insert_to_restart"]
            if span is None or span + 16 * MIB > LOSS_SPAN or time.monotonic() >= deadline:
                break
            require(not before["slot"]["active"], "publisher no longer offline")
            self.sql("emit and switch WAL", """
                SELECT pg_logical_emit_message(false, 'exp018', 'retention-switch'::text);
                SELECT pg_switch_wal();
                CHECKPOINT;
            """)
            after = self.slot_sample(f"after-switch-{switch}", allow_loss=True)
            if after["slot"]["wal_status"] == "lost":
                self.event("retention", "slot_wal_lost", switch=switch)
                return after["slot"]
        self.event("retention", "inconclusive_wal_loss_unhit")
        return None

    def clean_catalog(self, lost):
        # The same slot name, source cluster, creation record and publication
        # OID were tracked continuously in this dedicated trial. PostgreSQL 16
        # clears restart_lsn after invalidation, so use the connector's guarded
        # group route and verify both remote deletions independently.
        self.group_sql("quiesce lost worker", """
            SELECT duckpipe.disable_group(:'group');
            SELECT duckpipe.stop_worker(:'group');
        """)
        status = self.group_state_after_disable()
        require(not status["worker_pids"] and not status["group"]["enabled"], "lost worker not quiescent")
        pg = self.slot_sample("before-lost-slot-removal", allow_loss=True)
        require(pg["slot"] == lost and not pg["slot"]["active"], "lost slot identity changed")
        oid = self.sql("tracked publication OID", "SELECT oid FROM pg_publication;")
        require(oid == self.publication_oid, "lost publication identity changed")
        require(self.consumer_identity(running=True) == self.original_volume, "old consumer identity")
        for table in TABLES:
            self.group_sql("remove lost mapping", f"""
                SELECT duckpipe.remove_table('fixture.{table}', drop_target => false, sync_group => :'group');
            """)
        self.group_sql("drop lost group", "SELECT duckpipe.drop_group(:'group');")
        self.members = ()
        self.observer.source = replace(self.observer.source, slot="", publication="", members=())
        self.wal("lost-objects-removed")
        self.controller("disable-login", self.oid)
        self.controller("restore-identity", self.oid)
        old_id = self.consumer_id
        self.docker("stop", "--time=12", old_id, timeout=16)
        require(self.docker("inspect", "-f", STATE, old_id) == "exited 0 false", "old consumer stop failed")
        require(self.consumer_identity(running=False) == self.original_volume, "old catalog volume identity")
        self.docker("rm", old_id)
        require(self.docker("volume", "rm", self.volume) == self.volume, "old catalog volume removal")
        self.event("resnapshot", "old_consumer_removed", container=old_id, volume=self.original_volume)
        self.checked("fresh consumer Compose start", (*self.compose, "up", "-d", "--wait", "--wait-timeout",
                     "30", "--no-deps", "--no-build", "--pull", "never", "cdc-catalog"), timeout=35)
        self.consumer_id = self.checked("new consumer identity", (*self.compose, "ps", "-q", "cdc-catalog")).strip()
        self.consumer_id = self.docker("inspect", "-f", "{{.Id}}", self.consumer_id)
        self.target = ("bash", "scripts/cdc/consumer/psql.sh", self.consumer_id)
        self.target_reader = (*self.target, "--pset=tuples_only=off")
        volume = self.consumer_identity(running=True)
        system = self.sql("new consumer system ID", "SELECT system_identifier FROM pg_control_system();", target=True)
        require(self.consumer_id != old_id and volume != self.original_volume and system != self.consumer_system,
                "consumer resnapshot did not start from a fresh volume")
        empty = self.sql("fresh catalog inventory", """
            SELECT name, publication, slot_name, conninfo IS NULL, confirmed_lsn IS NULL
            FROM duckpipe.sync_groups ORDER BY name LIMIT 2;
            SELECT (SELECT count(*) FROM duckpipe.table_mappings),
                   (SELECT count(*) FROM pg_class
                    WHERE relnamespace=to_regnamespace('bronze') AND relkind IN ('r','p','v','m','f'));
        """, target=True)
        self.event("resnapshot", "fresh_catalog_inventory", inventory=empty)
        require(empty == "default|duckpipe_pub_postgres|duckpipe_slot_postgres|t|t\n0|0",
                "fresh catalog lacks the exact extension bootstrap inventory")
        self.event("resnapshot", "fresh_consumer", system_identifier=system, volume=volume, container=self.consumer_id)
        self.controller("elevate", self.oid)
        self.controller("enable-login", self.oid)
        self.sql("initialize fresh consumer Bronze", Path("scripts/cdc/consumer/bootstrap.sql").read_text(), target=True)

    def group_state_after_disable(self):
        raw = self.checked("disabled connector status", ("bash", STATUS, self.consumer_id, self.group,
                           self.run_id, "lost-worker-quiesced", str((time.monotonic_ns() - self.start) // 1_000_000)))
        state = json.loads(raw)
        self.event("lost-worker-quiesced", "connector_sample", sample=state)
        require(state["group"]["slot_name"] == self.slot and state["group"]["publication"] == self.publication,
                "disabled group scope changed")
        return state

    def retention(self):
        self.fault("retention-fault")
        self.offline_step("S03")
        self.offline_step("S04")
        lost = self.force_wal_loss()
        self.boot_consumer("retention-restart")
        if lost is None:
            self.worker("retention-restart")
            self.checkpoint("recovered-S04", "S04")
            return
        self.worker("lost-slot-reconnect", expect_active=False)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            self.group_state("lost-slot-reconnect", allow_error=True)
            self.slot_sample("lost-slot-reconnect", allow_loss=True)
            logs = self.logs("lost-slot-reconnect")
            if any(row["kind"] in ("lost_reconnect", "removed_wal", "invalid_slot") for row in logs):
                self.event("retention", "lost_slot_reconnect_rejected")
                break
            time.sleep(POLL)
        else:
            self.event("retention", "reconnect_error_unobserved")
        require(not self.data("stale-target-after-invalidated-restart", "S02", "target"),
                "old invalidated catalog was not exact S02")
        require(not self.data("resnapshot-input", "S04", "source"), "source S04 lost before resnapshot")
        self.clean_catalog(lost)
        self.evidence /= "resnapshot"
        self.evidence.mkdir()
        self.onboard("S04", "resnapshot-S04")
        self.continued()

    def run(self):
        try:
            before = self.before_fault()
            if self.trial == "graceful":
                self.graceful()
            elif self.trial == "abrupt":
                self.abrupt(before)
            else:
                require(self.trial == "retention", "unknown trial")
                self.retention()
            self.save("catalog.json", catalog(self.consumer_id))
            self.resources("final")
            self.logs("recovery")
            self.remove_source_objects()
            self.event("final", "trial_completed")
        except Exception:
            try:
                self.logs("failed-run")
            except Exception as error:
                self.event("failure", "diagnostics_unavailable", error_type=type(error).__name__)
            raise


if __name__ == "__main__":
    Recovery().run()
