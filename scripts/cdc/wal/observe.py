"""Bounded publisher JSONL observations from the disconnected lab VM."""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time

DOCKER = ("docker", "--host", "unix:///var/run/docker.sock")
PGDATA = "/var/lib/postgresql/data"
SQL = Path(__file__).with_name("sample.sql").read_bytes()
INSPECT = (
    '{{index .Config.Labels "com.docker.compose.project"}} '
    '{{index .Config.Labels "com.docker.compose.service"}} '
    '{{len .NetworkSettings.Networks}} '
    '{{range .NetworkSettings.Networks}}{{.NetworkID}}{{end}} '
    '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}'
    '{{.Type}} {{.Name}}{{end}}{{end}}'
    '{{range .NetworkSettings.Ports}}{{if .}} published{{end}}{{end}}'
)
PSQL = r"""
    PGPASSWORD=$(cat "$POSTGRES_PASSWORD_FILE")
    export PGPASSWORD PGCONNECT_TIMEOUT=2 PGREQUIREAUTH=scram-sha-256
    export PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=2000"
    exec psql -XwqAt -h 127.0.0.1 -U "$POSTGRES_USER" -d source_lab -v ON_ERROR_STOP=1 "$@" -f -
"""
DISK = r"""
    test "$PGDATA" = "$1"
    test ! -L "$PGDATA/pg_wal"
    test "$(stat -c %d "$PGDATA")" = "$(stat -c %d "$PGDATA/pg_wal")"
    data=$(du -skx "$PGDATA")
    wal=$(du -skx "$PGDATA/pg_wal")
    free=$(df -Pk "$PGDATA")
    printf '%s\n' "$data" | cut -f1
    printf '%s\n' "$wal" | cut -f1
    printf '%s\n' "$free" | awk 'NR == 2 {print $4}'
"""


class ObservationError(Exception):
    """An error code safe to include in experiment evidence."""


@dataclass(frozen=True)
class Source:
    project: str
    container: str
    bridge: str
    system_identifier: str
    slot: str = ""
    publication: str = ""
    members: tuple = ()

    def __post_init__(self):
        if (not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", self.project)
                or any(name and not re.fullmatch(r"[a-z0-9_]{1,63}", name)
                       for name in (self.slot, self.publication))):
            raise ValueError("invalid source name")
        if not all(
            re.fullmatch(r"[0-9a-f]{64}", value) for value in (self.container, self.bridge)
        ) or not re.fullmatch(r"[1-9][0-9]{0,19}", self.system_identifier):
            raise ValueError("invalid source identity")
        if bool(self.slot) != bool(self.publication) or bool(self.publication) != bool(self.members):
            raise ValueError("provide a slot, publication and members together")
        if len(self.members) > 32 or len(set(self.members)) != len(self.members) or any(
            not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}\.[a-z_][a-z0-9_]{0,62}", name)
            for name in self.members
        ):
            raise ValueError("invalid publication member list")


class Observer:
    def __init__(self, source, run_id, budget_seconds, max_samples):
        if not 0 < budget_seconds <= 300 or not 1 <= max_samples <= 120:
            raise ValueError("budget must be within 300 seconds and 120 samples")
        validate_label(run_id)
        self.source = source
        self.run_id = run_id
        self.started_ns = time.monotonic_ns()
        self.deadline_ns = self.started_ns + int(budget_seconds * 1_000_000_000)
        self.max_samples = max_samples
        self.attempts = 0
        self.previous = {}
        self.closed = False

    def remaining(self):
        remaining = (self.deadline_ns - time.monotonic_ns()) / 1_000_000_000
        if remaining <= 0:
            raise ObservationError("deadline_exhausted")
        return remaining

    def command(self, args, *, code, data=None, in_container=False):
        remaining = self.remaining()
        if in_container:
            # Bound the guest-side process even if the local Docker client is killed.
            args = ("exec", "-i", self.source.container, "timeout", "--signal=KILL",
                    str(min(remaining, 5)), *args)
        try:
            result = subprocess.run(
                (*DOCKER, *args), input=data or b"", stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, timeout=min(remaining, 6), check=False,
            )
        except subprocess.TimeoutExpired:
            raise ObservationError("capture_timeout") from None
        except OSError:
            raise ObservationError(code) from None
        self.remaining()
        if result.returncode in (124, 137):
            raise ObservationError("capture_timeout")
        if result.returncode or len(result.stdout) > 32768:
            raise ObservationError(code)
        return result.stdout

    def validate_inventory(self, telemetry):
        source = self.source
        slot = telemetry["slot"]
        if telemetry["slot_inventory_count"] != bool(source.slot) or (slot is None) != (not source.slot):
            raise ObservationError("slot_identity")
        if slot is not None and (
            slot["slot_name"], slot["database"], slot["slot_type"], slot["plugin"], slot["temporary"]
        ) != (source.slot, "source_lab", "logical", "pgoutput", False):
            raise ObservationError("slot_identity")

        publication = telemetry["publication"]
        members = telemetry["members"]
        if (telemetry["publication_inventory_count"] != bool(source.publication)
                or (publication is None) != (not source.publication)
                or (publication and (publication["pubname"] != source.publication
                                     or publication["puballtables"] or publication["schema_wide"]))
                or sorted(f'{row["schema"]}.{row["table"]}' for row in members) != sorted(source.members)
                or any(row["filtered"] for row in members)):
            raise ObservationError("publication_identity")

    def sql_sample(self):
        source = self.source
        expected = f"{source.project} source-db 1 {source.bridge} volume {source.project}_source-pg"
        actual = self.command(("inspect", "-f", INSPECT, source.container), code="container_inspection")
        if actual.strip() != expected.encode():
            raise ObservationError("container_identity")

        variables = {
            "system_identifier": source.system_identifier,
            "slot": source.slot,
            "publication": source.publication,
            "previous_insert": self.previous.get("insert_lsn", ""),
            "previous_timeline": self.previous.get("checkpoint_timeline_id", ""),
            "previous_start": self.previous.get("postmaster_started_at", ""),
        }
        args = ["sh", "-ec", PSQL, "sh"]
        for variable, value in variables.items():
            args.extend(("-v", f"{variable}={value}"))
        telemetry = json.loads(self.command(args, code="sql_capture", data=SQL, in_container=True))
        if telemetry.get("error") == "source_identity":
            raise ObservationError("source_identity")
        self.validate_inventory(telemetry)
        del telemetry["slot_inventory_count"], telemetry["publication_inventory_count"]
        return telemetry

    def disk_sample(self):
        raw = self.command(("sh", "-ec", DISK, "sh", PGDATA), code="disk_capture", in_container=True)
        data_kib, wal_kib, free_kib = map(int, raw.split())
        if min(data_kib, wal_kib) <= 0 or free_kib < 0:
            raise ObservationError("disk_capture")
        return {"pgdata_kib": data_kib, "wal_kib": wal_kib, "available_kib": free_kib}

    def sample(self, phase, checkpoint):
        validate_label(phase)
        validate_label(checkpoint)
        if self.closed:
            raise ObservationError("observation_closed")
        started_ns = time.monotonic_ns()
        error = telemetry = storage = None
        try:
            self.remaining()
            if self.attempts >= self.max_samples:
                raise ObservationError("sample_budget_exhausted")
            telemetry = self.sql_sample()
            try:
                storage = self.disk_sample()
            except (ValueError, TypeError):
                raise ObservationError("disk_capture") from None
            if (storage["pgdata_kib"] >= 524288 or storage["wal_kib"] >= 262144
                    or storage["available_kib"] < 1048576):
                raise ObservationError("source_disk_threshold")
            self.remaining()
            self.previous = telemetry["positions"]
        except ObservationError as exc:
            error = str(exc)
        except (AttributeError, KeyError, TypeError, ValueError):
            error = "invalid_sql_capture"

        self.attempts += 1
        self.closed = error is not None
        return {
            "run_id": self.run_id,
            "phase": phase,
            "checkpoint": checkpoint,
            "utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "monotonic_elapsed_ns": time.monotonic_ns() - self.started_ns,
            "sample_started_elapsed_ns": started_ns - self.started_ns,
            "sample": self.attempts,
            "role": "publisher",
            "ownership": {
                "project": self.source.project, "container": self.source.container,
                "bridge": self.source.bridge, "database": "source_lab",
                "system_identifier": self.source.system_identifier,
                "slot": self.source.slot or None, "publication": self.source.publication or None,
            },
            "error": error,
            "postgresql": telemetry,
            "storage": storage,
            "commit_lsn": None,
            "end_lsn": None,
        }


def validate_label(value):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", value):
        raise ValueError("invalid trace label")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "container", "bridge", "system-identifier", "run-id", "phase", "checkpoint"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--slot", default="")
    parser.add_argument("--publication", default="")
    parser.add_argument("--member", action="append", default=[])
    parser.add_argument("--budget-seconds", type=float, default=15)
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--interval-seconds", type=float, default=0.5)
    args = parser.parse_args()
    try:
        source = Source(args.project, args.container, args.bridge, args.system_identifier,
                        args.slot, args.publication, tuple(args.member))
        if not 0 <= args.interval_seconds <= 60:
            raise ValueError("sample interval must be between zero and 60 seconds")
        validate_label(args.phase)
        validate_label(args.checkpoint)
        observer = Observer(source, args.run_id, args.budget_seconds, args.samples)
    except ValueError as exc:
        parser.error(str(exc))

    for index in range(args.samples):
        if index:
            wait = max(0, (observer.deadline_ns - time.monotonic_ns()) / 1_000_000_000)
            time.sleep(min(args.interval_seconds, wait))
        observation = observer.sample(args.phase, args.checkpoint)
        print(json.dumps(observation, separators=(",", ":")), flush=True)
        if observation["error"]:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
