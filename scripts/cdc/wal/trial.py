"""Prepare the accepted EXP-011 reproducer with EXP-014 hold-point observations."""

import argparse
import json
from pathlib import Path
import sys

from scripts.cdc.wal.observe import Observer, Source

REPRODUCER = Path("tests/integration/remote-probe/run.sh")
HOOKS = r"""
full_id=$(docker_local inspect -f '{{.Id}}' "$source_id")
base=(--project "$COMPOSE_PROJECT_NAME" --container "$full_id" --bridge "$SOURCE_INPUT_ID"
      --system-identifier "$publisher_identity" --run-id "$run" --phase 2.4)
observe() { python3 -m scripts.cdc.wal.observe "${base[@]}" "$@"; }
capture() {
    printf '%s\n' "$1" >&"${timeline[1]}"
    local row
    IFS= read -r -t 8 -u "${timeline[0]}" row
    printf '%s\n' "$row" >> "$evidence/timeline.jsonl"
    test "$(python3 -c 'import json,sys; print(json.load(sys.stdin)["error"])' <<< "$row")" = None
}
start_timeline() {
    coproc timeline {
        python3 -u -m scripts.cdc.wal.trial stream "$COMPOSE_PROJECT_NAME" "$full_id" \
            "$SOURCE_INPUT_ID" "$publisher_identity" "$slot" "$publication" "$run"
    }
}
finish_timeline() {
    local pid=$timeline_PID fd=${timeline[1]}
    exec {fd}>&-
    wait "$pid"
}
docker_local exec "$source_id" psql --version
observe --checkpoint empty > "$evidence/empty.jsonl"
if [[ $trial == source ]]; then
    rows='SELECT id,value FROM probe.items ORDER BY id LIMIT 3'
    source_sql -c "$rows" > "$evidence/before.rows"
    test "$(cat "$evidence/before.rows")" = '1|seed'
    source_sql -v slot="$slot" -v publication="$publication" <<'SQL'
SET ROLE probe_replicator;
CREATE PUBLICATION :"publication" FOR TABLE probe.items;
RESET ROLE;
SELECT * FROM pg_create_logical_replication_slot(:'slot', 'pgoutput');
SQL
    publisher_state > "$evidence/before.state"
    start_timeline
    capture before
    source_sql -c "INSERT INTO probe.items VALUES (2, 'inserted');"
    capture after
    finish_timeline
    source_sql -c "$rows" > "$evidence/after.rows"
    test "$(cat "$evidence/after.rows")" = $'1|seed\n2|inserted'
    publisher_state > "$evidence/after.state"
    expected=(--slot "$slot" --publication "$publication" --member probe.items)
    if observe "${expected[@]}" --slot "unexpected_$run" --checkpoint wrong-slot \
        > "$evidence/wrong-slot.jsonl"; then exit 1; fi
    extra="extra_$run"
    source_sql -c "SELECT * FROM pg_create_logical_replication_slot('$extra', 'pgoutput');"
    unexpected=0
    observe "${expected[@]}" --checkpoint extra-slot > "$evidence/extra-slot.jsonl" || unexpected=$?
    test "$(source_sql -c "SELECT count(*) FROM pg_replication_slots WHERE slot_name='$extra'
        AND NOT active AND NOT temporary AND database='source_lab' AND plugin='pgoutput'")" = 1
    source_sql -c "SELECT pg_drop_replication_slot('$extra');"
    test "$unexpected" = 1
    if observe "${expected[@]}" --checkpoint deadline --budget-seconds 0.000001 \
        > "$evidence/deadline.jsonl"; then exit 1; fi
    python3 -m scripts.cdc.wal.trial verify source "$evidence"
    exit 0
fi
"""


def instrument(trial):
    script = REPRODUCER.read_text()

    def replace(anchor, value):
        nonlocal script
        if script.count(anchor) != 1:
            raise ValueError(f"EXP-011 anchor changed: {anchor}")
        script = script.replace(anchor, value)

    replace("probe=tests/integration", f"trial={trial}\nprobe=tests/integration")
    replace("EXP-011/$run", "EXP-014/$run")
    replace("owner=2.1/Codex ticket=38", "owner=2.4/Codex ticket=41")
    for old, new in (("cdc21-", "cdc24-"), ("g21_", "g24_"), ("pub21_", "pub24_"),
                     ("slot21_", "slot24_"), ('bridge="p21', 'bridge="p24')):
        replace(old, new)
    anchor = "subnets=$(docker_local"
    replace(anchor, HOOKS + "\n" + anchor)
    anchor = 'echo "Commit insert"'
    replace(anchor, "start_timeline\ncapture initial\n" + anchor)
    for checkpoint in ("insert", "update", "delete"):
        anchor = f"checkpoint {checkpoint} "
        line = next(line for line in script.splitlines() if line.startswith(anchor))
        replace(line, line + f"\ncapture {checkpoint}")
    anchor = 'echo "Remove mapping and drop group with the pinned API"'
    replace(anchor, 'finish_timeline\npython3 -m scripts.cdc.wal.trial verify active "$evidence"\n' + anchor)
    anchor = 'echo "EXP-011 ROW AND LIFECYCLE CHECKS PASSED"'
    replace(anchor, 'observe --checkpoint cleaned > "$evidence/cleaned.jsonl"\n' + anchor)
    return script


def lsn(value):
    high, low = (int(part, 16) for part in value.split("/"))
    return (high << 32) + low


def verify(trial, evidence):
    def read(name):
        return [json.loads(line) for line in (evidence / (name + ".jsonl")).read_text().splitlines()]

    empty, = read("empty")
    assert empty["error"] is None
    telemetry = empty["postgresql"]
    assert telemetry["slot"] is telemetry["publication"] is telemetry["feedback"] is None
    assert telemetry["members"] == [] and all(value is None for value in telemetry["wal_bytes"].values())
    rows = read("timeline")
    checkpoints = ["before", "after"] if trial == "source" else ["initial", "insert", "update", "delete"]
    assert [row["checkpoint"] for row in rows] == checkpoints
    previous_end, previous_insert = 0, None
    confirmed_positions = []
    for row in rows:
        assert row["error"] is row["commit_lsn"] is row["end_lsn"] is None
        assert previous_end <= row["sample_started_elapsed_ns"] <= row["monotonic_elapsed_ns"]
        telemetry = row["postgresql"]
        slot = telemetry["slot"]
        assert telemetry["members"] == [{"schema": "probe", "table": "items", "filtered": False}]
        assert telemetry["publication"]["pubname"] == row["ownership"]["publication"]
        assert slot["slot_name"] == row["ownership"]["slot"]
        assert slot["wal_status"] in ("reserved", "extended") and slot["safe_wal_size"] > 0
        insert = lsn(telemetry["positions"]["insert_lsn"])
        confirmed = lsn(slot["confirmed_flush_lsn"])
        assert telemetry["wal_bytes"] == {
            "insert_since_previous": None if previous_insert is None else insert - previous_insert,
            "insert_to_restart": insert - lsn(slot["restart_lsn"]),
            "insert_to_confirmed_flush": insert - confirmed,
        }
        assert 0 < row["storage"]["wal_kib"] < row["storage"]["pgdata_kib"] < 524288
        assert row["storage"]["wal_kib"] < 262144 and row["storage"]["available_kib"] >= 1048576
        assert slot["active"] == (trial == "active")
        if trial == "active":
            assert telemetry["feedback"]["pid"] == slot["active_pid"]
        else:
            assert telemetry["feedback"] is slot["active_pid"] is None
        confirmed_positions.append(confirmed)
        previous_insert, previous_end = insert, row["monotonic_elapsed_ns"]
    if trial == "source":
        before, after = (row["postgresql"] for row in rows)
        for position in ("restart_lsn", "confirmed_flush_lsn"):
            assert before["slot"][position] == after["slot"][position]
        assert after["wal_bytes"]["insert_since_previous"] > 0
        for name in ("wrong-slot", "extra-slot"):
            rejected, = read(name)
            assert rejected["error"] == "slot_identity" and rejected["postgresql"] is rejected["storage"] is None
        deadline, = read("deadline")
        assert deadline["error"] == "deadline_exhausted"
    else:
        assert confirmed_positions == sorted(confirmed_positions)
        assert confirmed_positions[-1] > confirmed_positions[0]
    print(f"EXP-014 {trial}: JSON, identity, timeline and WAL span checks passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("instrument")
    validate = subparsers.add_parser("verify")
    for subparser in (prepare, validate):
        subparser.add_argument("trial", choices=("source", "active"))
    validate.add_argument("evidence", type=Path)
    stream = subparsers.add_parser("stream")
    for name in ("project", "container", "bridge", "system_identifier", "slot", "publication", "run"):
        stream.add_argument(name)
    args = parser.parse_args()
    if args.command == "instrument":
        print(instrument(args.trial), end="")
    elif args.command == "verify":
        verify(args.trial, args.evidence)
    else:
        source = Source(args.project, args.container, args.bridge, args.system_identifier,
                        args.slot, args.publication, ("probe.items",))
        observer = Observer(source, args.run, 275, 4)
        for line in sys.stdin:
            row = observer.sample("2.4", line.strip())
            print(json.dumps(row, separators=(",", ":")), flush=True)
            if row["error"]:
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
