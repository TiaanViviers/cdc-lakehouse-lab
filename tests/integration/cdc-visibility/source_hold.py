"""Run the Phase 1 schedules in the pinned fixture container with read-only holds."""

import sys

from scripts.source.overlap import run_s05, transaction_statuses
from scripts.source.runner import Trace, parse_args, run_step, trace_resources
from scripts.source.transactions import FixtureError, connect, sequential_writer, writer_identity


class HeldTrace(Trace):
    def __call__(self, event, **details):
        # Both S05 hold events already verify exact fixture rows and XID status.
        # For S04 expose its XID while the original writer remains in run_step.
        if event == "before_commit":
            identity = writer_identity(self.writer)
            details.update(identity=identity, transaction_statuses=transaction_statuses(
                self.reader, {"S04": identity},
            ))
            if details["transaction_statuses"] != {"S04": "in progress"}:
                raise FixtureError("S04 writer is no longer in progress")
        super().__call__(event, **details)
        if event in ("before_commit", "both_open", "a_only"):
            if sys.stdin.readline() != "release\n":
                raise FixtureError(f"controller did not release {event}")
            super().__call__("controller_released", gate=event)


def main():
    args = parse_args(sys.argv[1:])
    if args.command != "run" or args.scenario not in ("S04", "S05"):
        raise FixtureError("expected the S04 or S05 Phase 1 schedule")
    trace = HeldTrace(args)
    try:
        with connect("reader") as trace.reader:
            if args.scenario == "S05":
                run_s05(trace, trace.reader, args.s05_fault)
            else:
                with connect("writer") as trace.writer, sequential_writer(trace.writer):
                    run_step(trace, trace.writer, trace.reader, args.scenario, args.rollback)
    except FixtureError as error:
        trace("error", stage=trace.stage, reason=str(error))
        return 1
    finally:
        trace_resources(trace)
    return 0


if __name__ == "__main__":
    sys.exit(main())
