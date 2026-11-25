#!/usr/bin/env bash
# Run only inside the verified disposable source VM with both fixture roles ready.
set -euo pipefail

run_id=${1:?Usage: run.sh RUN_ID NEW_ARTIFACT_DIRECTORY}
evidence=${2:?Provide a new local artifact directory}
: "${COMPOSE_PROJECT_NAME:?Set the verified disposable project name}"
: "${SOURCE_INPUT_ID:?Set the verified bridge ID}"
mkdir -m 700 "$evidence"

source_compose=(docker --host unix:///var/run/docker.sock compose -f compose.source.yaml --profile source)
fixture_compose=("${source_compose[@]}" -f compose.runner.yaml)

runner() {
    "${fixture_compose[@]}" run --rm --no-deps -T fixture-runner --run-id "$run_id" "$@" </dev/null
}

# This privileged check reads only the PostgreSQL backend catalog in the verified source.
writer_backends() {
    "${source_compose[@]}" exec -T source-db sh -ec '
        export PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")" PGCONNECT_TIMEOUT=3
        exec psql -XwAt -v ON_ERROR_STOP=1 -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -c "SELECT pid FROM pg_stat_activity WHERE usename = '\''source_fixture_writer'\'' ORDER BY pid;"
    '
}

fresh_s04() {
    local attempt=$1
    runner --attempt "$attempt" reset --confirm >"$evidence/$attempt-reset.jsonl"
    for step in S01 S02 S03 S04; do
        runner --attempt "$attempt" run "$step" >"$evidence/$attempt-$step.jsonl"
    done
    runner --attempt "$attempt" inspect S04 >"$evidence/$attempt-predecessor.jsonl"
}

exercise() {
    local attempt=$1 expected_exit=$2 expected_checkpoint=$3
    shift 3
    fresh_s04 "$attempt"
    local start_ns elapsed_ms status=0
    start_ns=$(date +%s%N)
    runner --attempt "$attempt" run S05 "$@" >"$evidence/$attempt-overlap.jsonl" || status=$?
    elapsed_ms=$(( ($(date +%s%N) - start_ns) / 1000000 ))
    printf '%s %s\n' "$status" "$elapsed_ms" >"$evidence/$attempt-result.txt"
    test "$status" -eq "$expected_exit"
    # Allow bounded server-side disconnect processing after the client closes.
    local probe
    for probe in {1..20}; do
        writer_backends >"$evidence/$attempt-writer-backends.txt"
        if [[ ! -s "$evidence/$attempt-writer-backends.txt" ]]; then
            break
        fi
        sleep 0.1
    done
    test ! -s "$evidence/$attempt-writer-backends.txt"
    runner --attempt "$attempt" inspect "$expected_checkpoint" >"$evidence/$attempt-final.jsonl"
}

exercise 1 0 S05
exercise 2 1 S04 --s05-fault barrier-timeout
exercise 3 1 S05-A --s05-fault after-a-commit
exercise 4 0 S05

python3 - "$evidence" <<'PY'
import hashlib
import json
import re
import sys
from pathlib import Path

evidence = Path(sys.argv[1])


def events(attempt, filename):
    return [json.loads(line) for line in
            (evidence / f"{attempt}-{filename}.jsonl").read_text().splitlines()]


def canonical(snapshot):
    assert snapshot["differences"] == [], snapshot
    return json.dumps([snapshot["rows"], snapshot["receipts"]],
                      sort_keys=True, separators=(",", ":")).encode()


def one(trace, event):
    (entry,) = [row for row in trace if row["event"] == event]
    return entry


def schedule_events(trace):
    return [" ".join(filter(None, (row["event"], row.get("transaction")))) for row in trace]


baseline = canonical(one(events(1, "predecessor"), "inspection"))
starts = ["start", "predecessor", "writer_staged A", "writer_staged B", "both_open"]
commits_a = ["barrier_release A", "commit_requested A", "commit_acknowledged A", "a_only"]
commits_b = ["barrier_release B", "commit_requested B", "commit_acknowledged B", "after_commit"]
failed = ["failure_state", "writers_closed", "error", "resources"]

for attempt in (1, 2, 3, 4):
    trace = events(attempt, "overlap")
    assert canonical(one(events(attempt, "predecessor"), "inspection")) == baseline
    assert canonical(one(trace, "predecessor")) == baseline
    both_open = one(trace, "both_open")
    assert canonical(both_open) == baseline
    assert both_open["transaction_statuses"] == {"A": "in progress", "B": "in progress"}
    writers = [row for row in trace if row["event"] == "writer_staged"]
    assert len({row["xid"] for row in writers} - {None}) == 2
    assert len({row["backend_pid"] for row in writers} | {both_open["backend_pid"]}) == 3
    assert one(trace, "writers_closed")["writers"] == {
        row["transaction"]: {"backend_pid": row["backend_pid"], "closed": True}
        for row in writers
    }
    final = canonical(one(events(attempt, "final"), "inspection"))

    if attempt == 2:
        assert schedule_events(trace) == starts + ["barrier_release_withheld A"] + failed
        failure = one(trace, "failure_state")
        assert failure["checkpoint"] == "S04" and failure["outcome"] == "rolled_back"
        assert failure["transaction_statuses"] == {"A": "aborted", "B": "aborted"}
        assert canonical(failure) == final == baseline
        reason = one(trace, "error")["reason"]
        match = re.fullmatch(r"S05 A commit barrier broke after (\d+) ms \(deadline 4 s\)", reason)
        assert match and 3900 <= int(match[1]) <= 5000, reason
        _, elapsed = (evidence / "2-result.txt").read_text().split()
        assert int(elapsed) < 15000, elapsed
    else:
        a_only = one(trace, "a_only")
        assert a_only["transaction_statuses"] == {"A": "committed", "B": "in progress"}
        if attempt == 1:
            expected_a_only = canonical(a_only)
        assert canonical(a_only) == expected_a_only
        if attempt == 3:
            assert schedule_events(trace) == starts + commits_a + failed
            failure = one(trace, "failure_state")
            assert failure["checkpoint"] == "S05-A" and failure["outcome"] == "partial_commit"
            assert failure["transaction_statuses"] == {"A": "committed", "B": "aborted"}
            assert canonical(failure) == final == expected_a_only
            assert "after A commit and before B release" in one(trace, "error")["reason"]
        else:
            assert schedule_events(trace) == starts + commits_a + commits_b + ["writers_closed", "resources"]
            committed = one(trace, "after_commit")
            assert committed["transaction_statuses"] == {"A": "committed", "B": "committed"}
            if attempt == 1:
                expected_s05 = canonical(committed)
            assert canonical(committed) == final == expected_s05
    print(f"Attempt {attempt}: exact snapshots and schedule verified, zero writer backends, "
          f"final SHA-256 {hashlib.sha256(final).hexdigest()}")
PY
