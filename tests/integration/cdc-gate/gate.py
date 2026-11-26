"""Compose the reviewed CDC checkpoint, recovery and visibility experiments."""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from scripts.cdc.wal.observe import DOCKER
from scripts.isolation.preflight import check_firewall, host_control
from tests.fixture_oracle import load_expectations

HERE = Path(__file__).resolve().parent
for experiment in ("cdc-recovery", "cdc-visibility"):
    sys.path.insert(0, str(HERE.parent / experiment))

from recovery import MIB, Recovery, catalog, lsn, require  # noqa: E402
from visibility import VisibilityExperiment, exact  # noqa: E402


class Gate(VisibilityExperiment, Recovery):
    def auth(self):
        def connection(container, host, database, role, password):
            return subprocess.run(
                (*DOCKER, "exec", "-i", "--user", "postgres", container, "sh", "-ec", """
                IFS= read -r PGPASSWORD
                export PGPASSWORD PGREQUIREAUTH=scram-sha-256 PGCONNECT_TIMEOUT=2
                export PGOPTIONS="-c statement_timeout=3000"
                exec psql -XwAtq -h "$1" -d "$2" -U "$3" -v ON_ERROR_STOP=1 \
                    -c 'SELECT current_user, current_database(), inet_client_addr() IS NOT NULL'
                """, "sh", host, database, role),
                input=password, text=True, capture_output=True, timeout=8,
            )

        for client, host, database, role, secret in (
            (self.consumer_id, "source-db", "source_lab", self.publisher, "publisher"),
            (self.source_id, "cdc-catalog", "postgres", "postgres", "cdc-catalog"),
        ):
            password = Path(f"secrets/{secret}-password").read_text()
            good = connection(client, host, database, role, password)
            require(good.returncode == 0 and good.stdout.strip() == f"{role}|{database}|t",
                    f"fresh TCP SCRAM failed for {host}")
            bad = connection(client, host, database, role, "incorrect-gate-password\n")
            require(bad.returncode == 2 and "password authentication failed" in bad.stderr,
                    f"wrong password did not receive a specific rejection from {host}")
            if host == "source-db":
                outside = connection(client, host, "postgres", role, password)
                require(outside.returncode == 2 and "pg_hba.conf rejects connection" in outside.stderr,
                        "publisher connection outside source_lab was not rejected by HBA")
            self.event("auth", "tcp_scram_success_and_wrong_password_rejected", host=host, database=database,
                       role=role, other_database_rejected=host == "source-db")

    def quiescent_data(self, label, step):
        require(not self.data(label, step, "target"), f"{label}: persisted {step} differs")
        require(not self.group_state(label)["worker_pids"], f"{label}: worker started during read")
        require(not self.slot_sample(label)["slot"]["active"], f"{label}: slot active during read")

    def graceful_restart(self):
        self.resources("before-graceful-stop")
        before = self.fault("graceful-exit")
        self.offline_step("S03")
        self.boot_consumer("graceful-restart")
        self.quiescent_data("graceful-before-worker", "S02")
        require(self.slot_sample("graceful-before-worker")["slot"]["confirmed_flush_lsn"] ==
                before["slot"]["confirmed_flush_lsn"], "offline slot acknowledgement changed")
        self.worker("graceful-restart")
        self.checkpoint("S03", "S03")
        for side in ("source", "target"):
            snapshot = json.loads((self.evidence / "S03" / f"{side}.snapshot.json").read_text())
            require(all(row["item_id"] != 102 for row in snapshot["rows"]["order_items"]),
                    f"S03 deleted item 102 visible on {side}")
            self.event("S03", "deleted_key_absent", side=side, item_id=102)
        self.logs("graceful-restart")

    def replace_consumer(self):
        self.resources("before-replacement")
        before = self.fault("replace-consumer")["slot"]
        old_id = self.consumer_id
        require(self.consumer_identity(running=False) == self.original_volume, "replacement volume changed")
        self.checked("force-recreate stopped consumer", (*self.compose, "up", "-d", "--wait",
                     "--wait-timeout", "30", "--force-recreate", "--no-deps", "--no-build",
                     "--pull", "never", "cdc-catalog"), timeout=35)
        new_id = self.checked("replica container identity", (*self.compose, "ps", "-q", "cdc-catalog")).strip()
        self.consumer_id = self.docker("inspect", "-f", "{{.Id}}", new_id)
        self.target = ("bash", "scripts/cdc/consumer/psql.sh", self.consumer_id)
        self.target_reader = (*self.target, "--pset=tuples_only=off")
        require(self.consumer_id != old_id and self.consumer_identity(running=True) == self.original_volume,
                "replacement did not preserve the named volume")
        system = self.sql("replacement cluster", "SELECT system_identifier FROM pg_control_system();", target=True)
        require(system == self.consumer_system, "replacement changed PostgreSQL cluster")
        require(self.docker("network", "inspect", "-f", "{{len .Containers}}", self.bridge) == "2",
                "replacement bridge endpoint count")
        self.docker("exec", "--user", "postgres", self.consumer_id, "sh", "-ec", """
            test "$(ls /sys/class/net | sort | paste -sd ' ')" = 'eth0 lo'
            awk '$2=="00000000" {bad=1} END {exit bad}' /proc/net/route
            awk '$2=="00" && $NF!="lo" {bad=1} END {exit bad}' /proc/net/ipv6_route
        """)
        self.replacement_host_denial()
        require(self.group_state("replacement")["group"]["slot_name"] == self.slot, "replacement changed slot")
        self.quiescent_data("replacement-before-worker", "S04")
        after = self.slot_sample("replacement")["slot"]
        require(before == after, "inactive slot changed across consumer replacement")
        require(catalog(self.consumer_id) == self.catalog_before_replacement, "replacement changed local catalog")
        self.auth()
        self.event("replacement", "consumer_replaced_with_same_cluster_catalog_and_volume",
                   old=old_id, new=self.consumer_id, system_identifier=system, volume=self.original_volume)
        self.worker("replacement")
        self.resources("after-replacement")

    def replacement_host_denial(self):
        configurations = json.loads(self.docker("network", "inspect", "-f",
                                                "{{json .IPAM.Config}}", self.bridge))
        addresses = [network["Gateway"] for network in configurations]
        require(len(addresses) == 2 and sum(":" in address for address in addresses) == 1,
                "expected both bridge gateway families")
        with ExitStack() as listeners:
            for address in addresses:
                port = host_control(listeners, address)
                probe = subprocess.run(
                    (*DOCKER, "exec", "--user", "postgres", self.consumer_id, "timeout", "2s",
                     "bash", "-c", 'exec 3<>"/dev/tcp/$1/$2"', "bash", address, str(port)),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4,
                )
                require(probe.returncode == 124, "replacement consumer host access was not blocked")
                self.event("replacement", "positive_guest_listener_denied_from_consumer", address=address)

    def walkthrough(self):
        label = "read-only-S04"
        pg = self.wait_active(label, True)
        status = self.group_state(label)
        require(len(status["worker_pids"]) == 1 and status["group"]["slot_name"] == self.slot,
                "walkthrough worker and publisher slot are not linked")
        sql = HERE.joinpath("walkthrough.sql").read_text()
        queries = {}
        for schema, target in (("fixture", False), ("bronze", True)):
            queries[schema] = self.sql(label, sql, target=target, variables=("-v", f"schema={schema}"))
        capture = self.engine(label)
        require(exact("S04", capture["rows"]), "walkthrough snapshot differs")
        require(queries["fixture"] == queries["bronze"] and queries["bronze"].startswith("on\n"),
                "target and source walkthrough projections differ")
        self.save("walkthrough.json", dict(rows=queries, slot=pg["slot"], worker=status["worker_pids"],
                  group=status["group"], tables=status["mappings"], snapshot_id=capture["snapshot_id"]))
        self.event(label, "walkthrough_exact", snapshot_id=capture["snapshot_id"])

    def retention_control(self):
        # Three checkpoint epochs accelerate segment use while the same worker
        # applies noncustomer updates. The customer table remains idle.
        label = "active-sparse"
        check_firewall(os.environ["BRIDGE"])
        settings = self.sql("retention settings", """
            SELECT current_setting('wal_segment_size'), current_setting('max_slot_wal_keep_size'),
                   current_setting('wal_keep_size'), current_setting('archive_mode');
        """)
        require(settings == "16MB|128MB|0|off", "unexpected active retention settings")
        before = self.wait_active(label, True)
        previous = before
        status = self.group_state(label)
        growth_epochs = []
        for epoch in range(1, 4):
            phase = f"{label}-{epoch}"
            require(previous["wal_bytes"]["insert_to_restart"] + 17 * MIB < 64 * MIB,
                    "active retention switch would exceed declared budget")
            applied_before = {row["source_table"]: row["applied_lsn"] for row in status["mappings"]}
            self.touch(phase, """
                UPDATE fixture.orders SET status=status WHERE order_id=30 RETURNING order_id;
                UPDATE fixture.order_items SET quantity=quantity WHERE item_id=301 RETURNING item_id;
                UPDATE fixture.payments SET amount_cents=amount_cents WHERE payment_id=303 RETURNING payment_id;
            """, ["30", "301", "303"])
            self.sql("bounded WAL switch and checkpoint", "SELECT pg_switch_wal(); CHECKPOINT;")
            deadline = time.monotonic() + 18
            while time.monotonic() < deadline:
                status = self.group_state(phase)
                changed = [row for row in status["mappings"] if row["source_table"] != "fixture.customers"]
                if len(changed) == 3 and all(
                    row["queued_changes"] == 0 and row["applied_lsn"]
                    and lsn(row["applied_lsn"]) >= lsn(previous["positions"]["insert_lsn"])
                    and lsn(row["applied_lsn"]) > lsn(applied_before[row["source_table"]])
                    for row in changed
                ):
                    break
                time.sleep(.5)
            else:
                raise RuntimeError(f"{phase}: noncustomer apply progress was not witnessed")
            after = self.slot_sample(phase)
            slot = after["slot"]
            require(slot["active"] and slot["active_pid"] == before["slot"]["active_pid"]
                    and after["wal_bytes"]["insert_to_restart"] < 64 * MIB
                    and slot["safe_wal_size"] > 0, "active-retention isolation or WAL budget")
            growth_epochs.append(
                after["wal_bytes"]["insert_to_restart"] > previous["wal_bytes"]["insert_to_restart"]
                and slot["safe_wal_size"] < previous["slot"]["safe_wal_size"]
            )
            self.resources(phase)
            previous = after
        self.checkpoint("after-active-sparse", "S05")
        result = dict(
            progress_observed=lsn(previous["slot"]["confirmed_flush_lsn"]) > lsn(before["slot"]["confirmed_flush_lsn"]),
            persistent_growth=all(growth_epochs),
        )
        self.event(label, "retention_decision", epochs=growth_epochs, **result)
        return result

    def file_control(self):
        self.group_sql("quiesce for scoped flush", """
            SELECT duckpipe.disable_group(:'group');
            SELECT duckpipe.stop_worker(:'group');
        """)
        self.wait_active("before-file-control", False)
        self.quiescent_data("inline-quiescent", "S05")
        initial = catalog(self.consumer_id)
        self.save("inline-catalog.json", initial)
        require(initial["catalog_schema"] == "ducklake"
                and any(row["key"] == "version" and row["value"] == "0.4" for row in initial["options"])
                and len(initial["inline_tables"]) == 4 and not initial["data_files"] and not initial["delete_files"],
                "ordinary inline catalog differs from the selected build's baseline")
        self.sql("scoped flush of DuckPipe-written order items", """
            CALL ducklake.set_option('data_inlining_row_limit', 0, 'bronze.order_items'::regclass);
            SELECT * FROM ducklake.flush_inlined_data('bronze.order_items'::regclass);
        """, target=True)
        flushed = catalog(self.consumer_id)
        self.save("file-catalog.json", flushed)
        table_id = next(row["table_id"] for row in flushed["tables"] if row["table_name"] == "order_items")
        files = flushed["data_files"]
        require(files and all(row["magic"] == "PAR1" and row["table_id"] == table_id for row in files)
                and sum(row["record_count"] for row in files) == len(load_expectations()["S05"]["order_items"])
                and not flushed["delete_files"], "scoped DuckLake Parquet reference check failed")
        self.quiescent_data("file-quiescent", "S05")
        self.resources("after-file-control")
        self.event("catalog", "layer_and_files_verified", format="0.4", inlined_tables=len(initial["inline_tables"]),
                   physical_files=len(files))

    def run(self):
        self.before_fault()
        self.auth()
        self.graceful_restart()
        predecessor = self.engine("S04-abort-predecessor")
        self.rollback()
        require(all(exact("S03", row["rows"]) for row in self.history("S04-abort", predecessor["snapshot_id"])),
                "aborted S04 affected a retained version")
        self.s04(False)
        self.checkpoint("S04", "S04")
        self.walkthrough()
        self.catalog_before_replacement = catalog(self.consumer_id)
        self.save("before-replacement-catalog.json", self.catalog_before_replacement)
        self.replace_consumer()
        self.s05(False)
        self.checkpoint("S05", "S05")
        retention = self.retention_control()
        self.file_control()
        self.remove_source_objects()
        inventory = self.sql("no publisher object leaks", """
            BEGIN READ ONLY;
            SELECT (SELECT count(*) FROM pg_replication_slots),
                   (SELECT count(*) FROM pg_publication),
                   (SELECT count(*) FROM pg_roles WHERE rolname = :'publisher'),
                   (SELECT count(*) FROM pg_class c
                    WHERE c.oid IN ('fixture.customers'::regclass, 'fixture.orders'::regclass,
                                   'fixture.payments'::regclass, 'fixture.order_items'::regclass)
                      AND c.relreplident = 'd' AND pg_get_userbyid(c.relowner) = 'source_fixture_owner');
            ROLLBACK;
        """, variables=("-v", f"publisher={self.publisher}"))
        require(inventory == "0|0|0|4", "publisher teardown inventory")
        self.event("cleanup", "zero_publisher_objects", slots=0, publications=0, roles=0, restored_tables=4)
        self.save("gate.json", dict(project=self.project, bridge=self.bridge, source_system=self.system,
                  consumer_system=self.consumer_system, revision=os.environ["CDC_REVISION"],
                  images=[self.docker("inspect", "-f", "{{.Image}}", container)
                          for container in (self.source_id, self.consumer_id)],
                  retention=retention))
        self.event("final", "gate_observations_complete")


if __name__ == "__main__":
    Gate().run()
