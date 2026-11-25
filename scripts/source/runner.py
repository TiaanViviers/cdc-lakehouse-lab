"""One-shot fixture runner for the isolated PostgreSQL source."""
import argparse
import json
import re
import resource
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import psycopg

from .checkpoints import check_state, observe, read_state, s04_visibility
from .replay import ReplayUnknown, run_replay
from .transactions import (
    SECRETS, FixtureError, apply_step, connect, reset_to_s00, sequential_writer,
    write_transaction,
)
from .workload import PREVIOUS, SEED, VERSION, s04_payload


class InjectedRollback(Exception):
    """Deliberate failure inside a disposable fixture transaction."""


class Trace:
    def __init__(self, args):
        self.fields = dict(run_id=args.run_id, fixture_version=VERSION, seed=SEED,
                           attempt=args.attempt, command=args.command,
                           scenario=getattr(args, "scenario", "S00"),
                           variant=args.variant)
        self.stage = "startup"

    def __call__(self, event, **details):
        print(json.dumps(dict(self.fields, event=event,
                              utc=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                              **details), sort_keys=True), flush=True)
        self.stage = event


def require_state(trace, checkpoint, state, event, backend_pid, *, include_rows=False):
    problems = check_state(checkpoint, state)
    rows, receipts = state
    details = dict(checkpoint=checkpoint, backend_pid=backend_pid, differences=problems,
                   report=rows["report"], s04_visible=s04_visibility(state))
    if include_rows:
        details.update(rows=rows, receipts=receipts)
    trace(event, **details)
    if problems:
        raise FixtureError(f"expected exact {checkpoint} state; see checkpoint differences")


def observed_checkpoint(trace, checkpoint, reader, event, *, include_rows=False):
    state = observe(reader)
    require_state(trace, checkpoint, state, event, reader.info.backend_pid,
                  include_rows=include_rows)
    return state


def writer_identity(writer):
    identity = writer.execute("SELECT pg_current_xact_id_if_assigned()::text AS xid").fetchone()
    return dict(backend_pid=writer.info.backend_pid, xid=identity["xid"])


def run_step(trace, writer, reader, scenario, rollback):
    previous = PREVIOUS[scenario]
    observed_checkpoint(trace, previous, reader, "predecessor")
    try:
        with write_transaction(writer):
            apply_step(writer, scenario)
            identity = writer_identity(writer)
            if scenario == "S04":
                require_state(trace, scenario, read_state(writer), "writer_staged",
                              writer.info.backend_pid)
                observed_checkpoint(trace, previous, reader, "before_commit")
            if rollback:
                raise InjectedRollback("forced S04 rollback")
            trace("commit_requested", **identity)
    except InjectedRollback as fault:
        observed_checkpoint(trace, previous, reader, "after_rollback")
        trace("rolled_back", reason=str(fault), **identity)
        return
    trace("commit_acknowledged", **identity)
    observed_checkpoint(trace, scenario, reader, "after_commit")


def run_reset(trace, writer, reader, disposable_id, fail_after_cleanup):
    prior = observe(reader) if fail_after_cleanup else None

    def after_cleanup():
        if fail_after_cleanup:
            require_state(trace, "empty", read_state(writer), "writer_after_cleanup",
                          writer.info.backend_pid)
            raise InjectedRollback("forced failure after cleanup and before S00 inserts")

    try:
        with write_transaction(writer):
            reset_to_s00(writer, disposable_id, after_cleanup)
            identity = writer_identity(writer)
            trace("commit_requested", **identity)
    except InjectedRollback as fault:
        if observe(reader) != prior:
            raise FixtureError("reset rollback changed the prior rows, report or receipts") from fault
        trace("after_rollback", backend_pid=reader.info.backend_pid, prior_state_preserved=True)
        raise FixtureError(str(fault)) from fault
    trace("commit_acknowledged", **identity)
    observed_checkpoint(trace, "S00", reader, "after_commit")


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default=VERSION, choices=(VERSION,))
    parser.add_argument("--seed", type=int, default=SEED, choices=(SEED,))
    parser.add_argument("--run-id", required=True, help="UTC run ID such as 20261125T130000Z-p01-01")
    parser.add_argument("--attempt", type=int, default=1)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("scenario", choices=(*PREVIOUS, "S06"))
    run.add_argument("--rollback", action="store_true", help="observe then roll back S04")
    reset = commands.add_parser("reset")
    reset.add_argument("--confirm", action="store_true", required=True)
    reset.add_argument("--fail-after-cleanup", action="store_true")
    inspect = commands.add_parser("inspect")
    inspect.add_argument("scenario", choices=("empty", *PREVIOUS))

    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-p01-[0-9]{2}", args.run_id):
        parser.error("--run-id must have the form YYYYMMDDTHHMMSSZ-p01-NN")
    if not 1 <= args.attempt <= 999:
        parser.error("--attempt must be between 1 and 999")
    rollback = getattr(args, "rollback", False)
    if rollback and args.scenario != "S04":
        parser.error("--rollback requires S04")
    if getattr(args, "fail_after_cleanup", False):
        args.variant = "reset_failure"
    else:
        args.variant = "rollback" if rollback else "normal"
    return args


def read_disposable_id():
    try:
        identity = UUID((SECRETS / "source_fixture_id").read_text().strip())
        if identity.int:
            return identity
    except (OSError, ValueError):
        pass
    raise FixtureError("reset requires a nonzero UUID from the local source_fixture_id file")


def trace_resources(trace):
    cgroup = Path("/sys/fs/cgroup")
    files = ("memory.max", "memory.swap.max", "memory.peak", "memory.events", "cpu.max", "cpu.stat")
    counters = {}
    for name in files:
        path = cgroup / name
        if path.is_file():
            counters[name] = path.read_text().strip()
    usage = resource.getrusage(resource.RUSAGE_SELF)
    trace("resources", cgroup=counters, max_rss_kib=usage.ru_maxrss,
          user_cpu_s=usage.ru_utime, system_cpu_s=usage.ru_stime,
          python=sys.version.split()[0], driver=psycopg.__version__,
          driver_impl=psycopg.pq.__impl__, libpq=psycopg.pq.version())


def main(argv=None):
    args = parse_args(argv)
    trace = Trace(args)
    try:
        trace("start")
        if args.command == "run" and args.scenario == "S06":
            receipt, resolution = run_replay(trace, s04_payload())
            trace("outcome", status="committed", receipt=receipt, resolution=resolution)
            return 0
        disposable_id = read_disposable_id() if args.command == "reset" else None
        with connect("reader") as reader:
            if args.command == "inspect":
                observed_checkpoint(trace, args.scenario, reader, "inspection", include_rows=True)
            else:
                with connect("writer") as writer, sequential_writer(writer):
                    if args.command == "reset":
                        run_reset(trace, writer, reader, disposable_id, args.fail_after_cleanup)
                    else:
                        run_step(trace, writer, reader, args.scenario, args.rollback)
    except ReplayUnknown as error:
        trace("outcome", status="unknown", stage=trace.stage, reason=str(error))
        return 1
    except psycopg.Error as error:
        # Client connection errors can include configuration details. Server primary
        # diagnostics are sufficient for the fixture guards and statement deadlines.
        trace("error", stage=trace.stage, sqlstate=error.sqlstate,
              reason=error.diag.message_primary or type(error).__name__)
        return 1
    except (FixtureError, OSError) as error:
        trace("error", stage=trace.stage, reason=str(error))
        return 1
    finally:
        trace_resources(trace)
    return 0


if __name__ == "__main__":
    sys.exit(main())
