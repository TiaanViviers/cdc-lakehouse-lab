"""Coordinate the bounded fixture, independent reads and CDC observations."""

from dataclasses import asdict, replace
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import time

from scripts.cdc.consumer.catalog import inspect as catalog
from scripts.cdc.parity import (
    COLUMNS, INTEGERS, TIMESTAMPS, compare, fixture_rows, normalize_rows,
    verify_checkpoint, write_evidence,
)
from scripts.cdc.parity.psql import SOURCE_TABLES, read_fixture, read_projections
from scripts.cdc.wal.observe import DOCKER, Observer, Source
from scripts.isolation.preflight import check_firewall
from tests.fixture_oracle import PRIMARY_KEYS, load_expectations


TABLES = ("customers", "orders", "payments", "order_items")
TARGET = {table: ("bronze", table) for table in TABLES}
POLL = 0.5
DEADLINE = 60
ABORT_HOLD = 10
SOURCE_PSQL = """
    export PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")"
    export PGREQUIREAUTH=scram-sha-256 PGCONNECT_TIMEOUT=2
    export PGOPTIONS="-c statement_timeout=5000 -c lock_timeout=2000 -c timezone=UTC"
    exec psql -h 127.0.0.1 -U source_admin -d source_lab -Xwq -v ON_ERROR_STOP=1 "$@"
"""
RESOURCES = """
    for key in memory.max memory.swap.max memory.peak memory.events cpu.max cpu.stat pids.max; do
        echo "$key"; cat "/sys/fs/cgroup/$key"
    done
    test "$(cat /sys/fs/cgroup/memory.max)" = "$2"
    test "$(cat /sys/fs/cgroup/memory.swap.max)" = 0
    test "$(cat /sys/fs/cgroup/cpu.max)" = "$3"
    test "$(cat /sys/fs/cgroup/pids.max)" = 128
    awk '$1=="oom" || $1=="oom_kill" { if ($2) bad=1 } END {exit bad}' /sys/fs/cgroup/memory.events
    du -skx "$1" "$PGDATA/pg_wal" /tmp
    df -Pk "$PGDATA"
    test "$(du -skx "$1" | cut -f1)" -lt 524288
    test "$(du -skx "$PGDATA/pg_wal" | cut -f1)" -lt 262144
    test "$(du -skx /tmp | cut -f1)" -le 65536
    test "$(df -Pk "$PGDATA" | awk 'NR==2 {print $4}')" -ge 1048576
"""


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def command(args, *, data=None, timeout=10):
    # Errors can include conninfo. Report the safe stage name at the call site.
    proc = subprocess.run(args, input=data, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, timeout=timeout, check=False)
    return proc


class Experiment:
    def __init__(self):
        self.evidence = Path(os.environ["EVIDENCE"])
        self.run_id = os.environ["RUN_ID"]
        self.trial = os.environ["TRIAL"]
        self.project = os.environ["COMPOSE_PROJECT_NAME"]
        self.bridge = os.environ["SOURCE_INPUT_ID"]
        self.source_id = os.environ["SOURCE_ID"]
        self.consumer_id = os.environ["CONSUMER_ID"]
        key = os.environ["CDC_RUN_KEY"]
        self.publisher = f"publisher_{key}"
        self.publication = f"pub_{key}"
        self.slot = f"slot_{key}"
        self.group = f"g_{key}"
        self.source = (*DOCKER, "exec", "-i", "--user", "postgres", self.source_id,
                       "sh", "-ec", SOURCE_PSQL, "sh")
        self.target = ("bash", "scripts/cdc/consumer/psql.sh", self.consumer_id)
        self.admin = ("bash", "sql/cdc/source/admin.sh")
        self.runner = (*DOCKER, "compose", "-f", "compose.source.yaml", "-f",
                       "compose.runner.yaml", "--profile", "source", "--profile", "generator",
                       "run", "--rm", "--no-deps", "-T", "fixture-runner",
                       "--run-id", os.environ["RUNNER_ID"])
        self.start = time.monotonic_ns()
        self.attempt = 0
        self.members = ()
        self.observer = None

    def checked(self, label, args, *, data=None, timeout=10):
        try:
            proc = command(args, data=data, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"{label} timed out") from None
        require(proc.returncode == 0, f"{label} failed (exit {proc.returncode})")
        require(len(proc.stdout) <= 262144, f"{label} output exceeded capture bound")
        return proc.stdout

    def sql(self, label, sql, *, target=False, variables=()):
        prefix = self.target if target else self.source
        return self.checked(label, (*prefix, "-At", *variables, "-f", "-"), data=sql).strip()

    def save(self, name, value):
        (self.evidence / name).write_text(json.dumps(value, indent=2) + "\n")

    def event(self, label, event, **payload):
        row = dict(run_id=self.run_id, trial=self.trial, checkpoint=label, event=event,
                   utc=datetime.now(UTC).isoformat(),
                   elapsed_ns=time.monotonic_ns() - self.start, **payload)
        with (self.evidence / "timeline.jsonl").open("a") as stream:
            stream.write(json.dumps(row) + "\n")
        if event not in ("target_read_started", "target_read_finished", "copy_probe"):
            print(f"{label}: {event}", flush=True)

    def controller(self, op, *args):
        out = self.checked(f"publisher {op}", (*self.admin, op, *args), timeout=24)
        (self.evidence / f"publisher-{op}.txt").write_text(out)
        return out.strip()

    def fixture(self, label, step, rollback=False):
        self.attempt += 1
        args = (*self.runner, "--attempt", str(self.attempt), "run", step)
        if rollback:
            args += ("--rollback",)
        self.event(label, "runner_started", scenario=step, rollback=rollback)
        raw = self.checked(f"Phase 1 runner {label}", args, timeout=50)
        events = [json.loads(line) for line in raw.splitlines()]
        (self.evidence / f"{label}.runner.jsonl").write_text(raw)
        outcome = "rolled_back" if rollback else "commit_acknowledged"
        selected = [row for row in events if row["event"] == outcome]
        require(len(selected) == 1, f"{label} missing runner {outcome}")
        self.event(label, outcome, runner_event=selected[0])
        resources = next(row["cgroup"] for row in events if row["event"] == "resources")
        require(resources["memory.max"] == "268435456" and resources["memory.swap.max"] == "0"
                and resources["cpu.max"] == "50000 100000"
                and all(line in resources["memory.events"].splitlines()
                        for line in ("oom 0", "oom_kill 0")), "runner cgroup bounds")

    def resources(self, label):
        with (self.evidence / "resources.txt").open("a") as stream:
            for role, cid, root, memory, cpu in (
                ("publisher", self.source_id, "/var/lib/postgresql/data", "805306368", "100000 100000"),
                ("consumer", self.consumer_id, "/var/lib/postgresql", "536870912", "75000 100000"),
            ):
                result = self.checked(f"{role} resource bounds", (*DOCKER, "exec", cid,
                                      "sh", "-ec", RESOURCES, "sh", root, memory, cpu))
                stream.write(f"{label} {role}\n{result}")

    def setup(self):
        version = self.sql("source settings", """
            SELECT version(), current_setting('shared_preload_libraries'),
                   current_setting('max_wal_senders'), current_setting('max_replication_slots'),
                   current_setting('max_slot_wal_keep_size');
        """)
        require(version.startswith("PostgreSQL 16.16 ") and version.endswith("||2|2|128MB"),
                "source version and WAL limits")
        self.system = self.sql("publisher identity", "SELECT system_identifier FROM pg_control_system();")
        self.save("runtime.json", dict(source_version=version, source_system=self.system,
                                      source=self.source_id, consumer=self.consumer_id,
                                      group=self.group, slot=self.slot, publication=self.publication,
                                      publisher=self.publisher, mapping=TARGET))
        self.observer = Observer(Source(self.project, self.source_id, self.bridge, self.system),
                                 self.run_id, budget_seconds=300, max_samples=120)
        self.wal("empty")
        enrollment = Path(f"secrets/{self.project}-fixture-id").read_text().strip()
        self.sql("fixture install", Path("sql/source/001_fixture_v1.sql").read_text(),
                 variables=("-v", f"disposable_id={enrollment}"))
        self.controller("inventory")
        oid, role = self.controller("prepare").split("|")
        require(role == self.publisher and oid.isdecimal(), "unexpected publisher role")
        self.oid = oid
        for role, file in ((self.publisher, "publisher"), ("source_fixture_reader", "source-fixture-reader"),
                           ("source_fixture_writer", "source-fixture-writer")):
            password = Path(f"secrets/{file}-password").read_text().strip()
            require(len(password) == 48 and all(c in "0123456789abcdef" for c in password),
                    "unexpected local secret format")
            self.sql("set scoped password", f"ALTER ROLE {role} PASSWORD '{password}';")
        ipam = json.loads(self.checked("bridge inventory", (*DOCKER, "network", "inspect",
                          "-f", "{{json .IPAM.Config}}", self.bridge)))
        hba = "".join(f"host source_lab {self.publisher} {network['Subnet']} scram-sha-256\n"
                      for network in ipam)
        hba += (f"host replication {self.publisher} all reject\nhost all {self.publisher} all reject\n"
                f"local replication {self.publisher} reject\nlocal all {self.publisher} reject\n")
        self.checked("install HBA", (*DOCKER, "exec", "-i", "--user", "postgres", self.source_id,
                     "sh", "-ec", 'umask 077; { cat; cat "$PGDATA/pg_hba.conf"; } > "$PGDATA/pg_hba.new"; '
                     'mv "$PGDATA/pg_hba.new" "$PGDATA/pg_hba.conf"'), data=hba)
        require(self.sql("HBA validation", "SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL;") == "0"
                and self.sql("HBA reload", "SELECT pg_reload_conf();") == "t", "publisher HBA")
        self.controller("enable-login", oid)
        self.controller("permission-probe")
        self.fixture("seed", "S00")
        capture = self.read_source(8)
        rows = fixture_rows(capture.rows)
        diffs = compare(self.trial, "S00", "source-pre-registration", rows)
        self.save("S00-source-before-registration.json", dict(rows=rows, diffs=diffs,
                  reader_semantics=capture.reader_semantics))
        require(not diffs, "source S00 mismatch before registration")
        self.wal("before-registration")
        self.event("S00", "exact_source_before_registration")
        self.controller("elevate", oid)
        self.sql("consumer bootstrap", Path("scripts/cdc/consumer/bootstrap.sql").read_text(), target=True)
        effective = self.sql("consumer settings", """
            SELECT version(), current_setting('duckpipe.query_routing'), current_setting('duckdb.threads'),
                   current_setting('duckdb.memory_limit'), current_setting('duckdb.max_temp_directory_size');
            SELECT extname, extversion FROM pg_extension WHERE extname LIKE 'pg_duck%' ORDER BY 1;
            SELECT duckdb.raw_query('SELECT version()');
        """, target=True)
        require(effective.startswith("PostgreSQL 18.4 ") and
                "|off|1|96MB|48MiB" in effective and "pg_duckpipe|1.0.0" in effective,
                "consumer version and query settings")
        (self.evidence / "consumer-settings.txt").write_text(effective + "\n")
        self.resources("before-registration")

    def read_source(self, budget):
        return read_fixture(self.source, SOURCE_TABLES, min(budget, 8))

    def wal(self, label):
        if self.members:
            self.observer.source = replace(self.observer.source, slot=self.slot,
                                           publication=self.publication, members=self.members)
        sample = self.observer.sample(self.trial, label)
        self.event(label, "publisher_sample", sample=sample)
        require(sample["error"] is None, f"publisher sample: {sample['error']}")
        slot = sample["postgresql"]["slot"]
        require(not slot or slot["wal_status"] in ("reserved", "extended"), "publisher WAL unavailable")
        return slot

    def status(self, label):
        out = self.checked("connector observation", ("bash", "scripts/cdc/consumer/status.sh",
                           self.consumer_id, self.group, self.run_id, label,
                           str((time.monotonic_ns() - self.start) // 1_000_000)))
        data = json.loads(out)
        self.event(label, "connector_sample", sample=data)
        require(not data["mapping_overflow"], "connector mapping overflow")
        expected = {(name, name.replace("fixture.", "bronze.")) for name in self.members}
        require({(row["source_table"], row["target_table"]) for row in data["mappings"]} == expected,
                "unexpected connector mapping inventory")
        require(all(not row["error_present"] for row in data["mappings"]), "connector reports a mapping error")
        return data

    def group_sql(self, stage, sql):
        return self.sql(stage, sql, target=True,
                        variables=("-v", f"group={self.group}", "-v", f"slot={self.slot}",
                                   "-v", f"publication={self.publication}", "-v", f"publisher={self.publisher}"))

    def create(self):
        check_firewall(os.environ["BRIDGE"])
        password = Path("secrets/publisher-password").read_text().strip()
        self.group_sql("create remote group", f"\\set secret '{password}'\n" + """
            SELECT duckpipe.create_group(:'group', publication => :'publication', slot_name => :'slot',
                conninfo => 'host=source-db port=5432 dbname=source_lab sslmode=disable user=' || :'publisher'
                    || ' password=' || :'secret', mode => 'bgworker');
        """)
        self.controller("inventory")
        row = self.sql("initial group inventory", """
            SELECT p.pubname, pg_get_userbyid(p.pubowner), s.slot_name, s.plugin, s.slot_type,
                   s.database, s.temporary, p.puballtables,
                   (SELECT count(*) FROM pg_publication_tables),
                   (SELECT count(*) FROM pg_publication), (SELECT count(*) FROM pg_replication_slots),
                   p.oid, s.restart_lsn, s.confirmed_flush_lsn
            FROM pg_publication p CROSS JOIN pg_replication_slots s;
        """).split("|")
        require(row[:11] == [self.publication, self.publisher, self.slot, "pgoutput", "logical",
                            "source_lab", "f", "f", "0", "1", "1"], "created group publisher inventory")
        self.event("S00", "empty_publication_and_persistent_slot", creation=row)

    def register(self, table):
        self.event(table, "registration_started")
        self.group_sql("add mapping", f"""
            SELECT duckpipe.add_table('fixture.{table}', target_table => 'bronze.{table}',
                sync_group => :'group', copy_data => true, sync_mode => 'upsert');
        """)
        self.members += (f"fixture.{table}",)
        self.event(table, "registration_returned")

    def initial(self, table, step):
        deadline = time.monotonic() + DEADLINE
        expected = load_expectations()[step][table]
        check = {table: (TARGET[table], COLUMNS[table], PRIMARY_KEYS[table])}
        last = None
        while (remaining := deadline - time.monotonic()) > 0:
            status = self.status(table)
            slots = self.sql("snapshot slot inventory", """
                SELECT slot_name, plugin, slot_type, database, temporary, active,
                       active_pid, restart_lsn, confirmed_flush_lsn
                FROM pg_replication_slots ORDER BY temporary, slot_name LIMIT 3;
            """).splitlines()
            self.event(table, "onboarding_slots", slots=slots)
            require(len(slots) in (1, 2) and slots[0].split("|")[:5]
                    == [self.slot, "pgoutput", "logical", "source_lab", "f"], "onboarding slot identity")
            if len(slots) == 2:
                name, plugin, kind, db, temporary, active, *_ = slots[1].split("|")
                require(name.startswith("duckpipe_snap_") and (plugin, kind, db, temporary, active)
                        == ("pgoutput", "logical", "source_lab", "t", "t"), "temporary slot identity")
            capture = read_projections(self.target, check, min(remaining, 5))
            rows = normalize_rows(table, capture.rows[table], COLUMNS[table], PRIMARY_KEYS[table],
                                  INTEGERS, TIMESTAMPS)
            mapping = status["mappings"][-1]
            if rows == expected and len(slots) == 1 and mapping["snapshot_lsn"] and (
                    mapping["state"] in ("CATCHUP", "STREAMING")):
                require(time.monotonic() < deadline, f"{table} copy exceeded deadline")
                self.save(f"{table}.initial.json", dict(rows=rows, previous=last, mapping=mapping))
                self.event(table, "initial_table_exact")
                self.wal(table)
                return
            last = dict(rows=rows, mapping=mapping)
            self.save(f"{table}.last-initial-observation.json", last)
            time.sleep(min(POLL, max(0, deadline - time.monotonic())))
        raise RuntimeError(f"{table} initial copy timed out")

    def checkpoint(self, label, step):
        self.wal(label)
        self.status(label)

        def read_target(budget):
            self.event(label, "target_read_started")
            rows = read_fixture(self.target, TARGET, min(budget, 8))
            self.event(label, "target_read_finished")
            return rows

        result = verify_checkpoint(self.trial, step, self.read_source, read_target,
                                   target_timeout=DEADLINE, interval=POLL)
        write_evidence(self.evidence / label, result)
        self.event(label, "exact_target" if result.passed else "parity_failed",
                   source=result.source.status, target=result.target.status, attempts=result.target_attempts,
                   snapshot_boundary=asdict(result.target.snapshot) if result.target.snapshot else None)
        self.wal(label)
        self.status(label)
        self.resources(label)
        require(result.passed, f"{label} independent parity failed")

    def rollback(self):
        label = "S04-aborted"
        self.wal(label)
        self.status(label)
        self.fixture(label, "S04", rollback=True)
        limit = time.monotonic() + ABORT_HOLD
        count = 0
        while True:
            last = time.monotonic() >= limit
            result = verify_checkpoint(self.trial, "S03", self.read_source,
                                       lambda budget: read_fixture(self.target, TARGET, min(budget, 5)),
                                       target_timeout=5, interval=POLL)
            count += 1
            write_evidence(self.evidence / label / f"{count:02}", result)
            # For exclusion every observed sample must pass, including the first attempt.
            require(result.passed and result.target_attempts == 1, "rollback window exact S03 violation")
            self.wal(label)
            self.status(label)
            if last:
                break
            time.sleep(min(POLL, max(0, limit - time.monotonic())))
        self.event(label, "rollback_window_exact", reads=count, minimum_hold_seconds=ABORT_HOLD)
        self.resources(label)

    def inventory(self):
        self.controller("reduce", self.oid)
        self.controller("permission-probe")
        self.controller("inventory")
        expected = "\n".join(f"fixture|{table}|f|{len(COLUMNS[table])}" for table in sorted(TABLES))
        actual = self.sql("publication membership and column coverage", """
            SELECT t.schemaname, t.tablename, t.rowfilter IS NOT NULL, cardinality(t.attnames)
            FROM pg_publication_tables t ORDER BY t.tablename;
        """)
        require(actual == expected, "publication row/column scope")
        require(self.sql("no source-only target relations", """
            SELECT to_regclass('bronze.scenario_receipts') IS NULL
                AND to_regclass('bronze.installation') IS NULL
                AND (SELECT count(*) FROM pg_class c JOIN pg_am a ON a.oid=c.relam
                     WHERE c.relnamespace='bronze'::regnamespace AND a.amname='ducklake')=4;
        """, target=True) == "t", "Bronze relation inventory")
        self.event("inventory", "four_full_publication_members_and_ducklake_targets", rows=actual)

    def copy_window(self):
        table = TABLES[-1]
        self.sql("install copy barrier", Path(__file__).with_name("copy-hold.sql").read_text(),
                 variables=("-v", f"publisher={self.publisher}"))
        # The source-side timeout and idle transaction timeout release the
        # advisory lock even if its guest-side controller disappears.
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
                self.register(table)
                before = self.wait_copy("blocked", 12)
                if before is None:
                    self.event("copy-window", "inconclusive_copy_window_unhit")
                else:
                    self.fixture("during-copy", "S01")
                    after = self.copy_probe()
                    require(after == before, "copy did not stay on the same blocked boundary across S01")
                    self.event("copy-window", "same_copy_blocked_after_commit", session=after)
            finally:
                holder.stdin.write("ROLLBACK;\n")
                holder.stdin.close()
                try:
                    require(holder.wait(timeout=6) == 0, "source advisory holder failed")
                except subprocess.TimeoutExpired:
                    holder.kill()
                    holder.wait()
                    raise RuntimeError("advisory holder release timed out") from None
        self.event("copy-window", "advisory_hold_released")
        self.initial(table, "S01" if before else "S00")
        self.sql("remove copy barrier", """
            DROP POLICY exp017_copy_gate ON fixture.order_items;
            DROP POLICY exp017_fixture_io ON fixture.order_items;
            ALTER TABLE fixture.order_items NO FORCE ROW LEVEL SECURITY;
            ALTER TABLE fixture.order_items DISABLE ROW LEVEL SECURITY;
            DROP FUNCTION fixture.exp017_copy_gate();
        """)
        self.inventory()
        self.checkpoint("copy-window", "S01" if before else "S00")
        require(before, "copy-window inconclusive: deterministic COPY wait was not observed")

    def copy_probe(self):
        row = self.sql("snapshot COPY boundary", """
            SELECT s.slot_name, a.pid, a.backend_xmin, a.xact_start, a.query_start,
                   h.pid, a.wait_event_type, a.wait_event
            FROM pg_replication_slots s JOIN pg_stat_activity a ON a.pid = s.active_pid
            JOIN pg_stat_activity h ON h.pid = ANY(pg_blocking_pids(a.pid))
            WHERE s.temporary AND s.slot_name ~ '^duckpipe_snap_[0-9]+$'
              AND s.plugin='pgoutput' AND s.database='source_lab'
              AND a.query LIKE 'COPY (SELECT * FROM "fixture"."order_items") TO STDOUT%'
              AND a.wait_event_type='Lock' AND a.wait_event='advisory'
              AND h.application_name='exp017_copy_holder'
            LIMIT 2;
        """)
        self.event("copy-window", "copy_probe", session=row or None)
        return row or None

    def wait_copy(self, boundary, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if boundary == "holder":
                row = self.sql("advisory holder boundary", """
                    SELECT l.pid FROM pg_locks l JOIN pg_stat_activity a USING (pid)
                    WHERE l.locktype='advisory' AND l.classid=17026 AND l.objid=1
                      AND l.objsubid=2 AND l.mode='ExclusiveLock' AND l.granted
                      AND a.application_name='exp017_copy_holder' LIMIT 2;
                """)
            else:
                row = self.copy_probe()
            if row and "\n" not in row:
                self.event("copy-window", f"{boundary}_observed", session=row)
                return row
            time.sleep(POLL)
        if boundary == "holder":
            raise RuntimeError("advisory holder boundary was not observed")
        return None

    def run(self):
        self.setup()
        self.create()
        for table in TABLES[:-1]:
            self.register(table)
            self.initial(table, "S00")
        if self.trial == "copy-window":
            self.copy_window()
        else:
            self.register(TABLES[-1])
            self.initial(TABLES[-1], "S00")
            self.inventory()
            self.checkpoint("S00", "S00")
            for step in ("S01", "S02", "S03"):
                self.wal(step)
                self.status(step)
                self.fixture(step, step)
                self.checkpoint(step, step)
            self.rollback()
            self.wal("S04")
            self.status("S04")
            self.fixture("S04", "S04")
            self.checkpoint("S04", "S04")

        self.save("catalog.json", catalog(self.consumer_id))
        self.wal("final")
        self.status("final")
        self.event("final", "experiment_passed")


if __name__ == "__main__":
    Experiment().run()
