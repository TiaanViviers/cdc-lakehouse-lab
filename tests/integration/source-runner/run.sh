#!/usr/bin/env bash
# Run against a fresh schema in the verified disposable VM.
set -euo pipefail
: "${COMPOSE_PROJECT_NAME:?set the verified source project}"
: "${SOURCE_INPUT_ID:?set the verified source network ID}"
run_id=${1:?usage: run.sh RUN_ID NEW_EVIDENCE_DIR}
evidence=${2:?usage: run.sh RUN_ID NEW_EVIDENCE_DIR}
mkdir -m 0700 "$evidence"
docker_cmd=(docker --host unix:///var/run/docker.sock)
compose=("${docker_cmd[@]}" compose -f compose.source.yaml -f compose.runner.yaml --profile source)
source_id=$("${compose[@]}" ps -q source-db)
test "$("${docker_cmd[@]}" inspect -f '{{.State.Health.Status}}' "$source_id")" = healthy
test "$("${docker_cmd[@]}" inspect -f '{{range .NetworkSettings.Networks}}{{.NetworkID}}{{end}}' "$source_id")" = "$SOURCE_INPUT_ID"
test -z "$("${docker_cmd[@]}" port "$source_id")"
inspect_name="${COMPOSE_PROJECT_NAME}-runner-acceptance"
wrong_id_file=

cleanup() {
    if [[ -n "$wrong_id_file" ]]; then
        rm -f -- "$wrong_id_file"
    fi
    if [[ -n "${retained_id:-}" ]]; then
        "${docker_cmd[@]}" rm "$retained_id" >/dev/null
    fi
}
trap cleanup EXIT

runner() {
    "${compose[@]}" run --rm --no-deps -T fixture-runner --run-id "$run_id" "$@" </dev/null
}
pass() {
    local name=$1
    shift
    runner "$@" >"$evidence/$name.log" 2>"$evidence/$name.stderr" || {
        cat "$evidence/$name.log" "$evidence/$name.stderr"
        return 1
    }
}
reject() {
    local name=$1 status=$2 message=$3 actual=0
    shift 3
    runner "$@" >"$evidence/$name.log" 2>&1 || actual=$?
    test "$actual" -eq "$status" && grep -Fq -- "$message" "$evidence/$name.log" || {
        printf 'Unexpected rejection result for %s (exit %s)\n' "$name" "$actual" >&2
        cat "$evidence/$name.log" >&2
        return 1
    }
}
advance_to_s04() {
    local name=$1 step
    for step in S01 S02 S03 S04; do
        pass "$name-$step" run "$step"
    done
}

pass fresh inspect empty
reject skip_bootstrap 1 'expected exact S00 state' run S01
pass after_skip_bootstrap inspect empty
test -z "$("${docker_cmd[@]}" ps -aq --filter "name=^/${inspect_name}$")"
if ! "${compose[@]}" run --name "$inspect_name" --no-deps -T fixture-runner \
    --run-id "$run_id" run S00 </dev/null >"$evidence/run-S00.log" 2>"$evidence/run-S00.stderr"; then
    cat "$evidence/run-S00.log" "$evidence/run-S00.stderr"
    exit 1
fi
retained_id=$("${docker_cmd[@]}" inspect -f '{{.Id}}' "$inspect_name")
limits=$("${docker_cmd[@]}" inspect -f '{{.HostConfig.Memory}} {{.HostConfig.MemorySwap}} {{.HostConfig.NanoCpus}} {{.HostConfig.PidsLimit}} {{.State.OOMKilled}} {{.State.ExitCode}}' "$retained_id")
printf 'memory_bytes memory_swap_bytes nano_cpus pids oom_killed exit\n%s\n' "$limits" >"$evidence/engine-limits.txt"
test "$limits" = '268435456 268435456 500000000 32 false 0'
"${docker_cmd[@]}" rm "$retained_id" >/dev/null
unset retained_id

pass inspect-S00 inspect S00
reject skip_S01 1 'expected exact S01 state' run S02
pass after_skip_S01 inspect S00
pass run-S01 run S01
pass inspect-S01 inspect S01
reject repeat_S01 1 'expected exact S00 state' run S01
pass after_repeat_S01 inspect S01
pass run-S02 run S02
pass inspect-S02 inspect S02
pass run-S03 run S03
pass inspect-S03 inspect S03
pass rollback-S04 run S04 --rollback
pass after_rollback_S04 inspect S03
pass run-S04 --attempt 2 run S04
pass inspect-S04 inspect S04

reject scenario 2 'invalid choice' run S05
reject seed 2 'invalid choice' --seed 43 run S04
reject version 2 'invalid choice' --fixture v2 run S04
reject wrong_variant 2 '--rollback requires S04' run S03 --rollback
reject repeat_S04 1 'expected exact S03 state' run S04
reject reset_intent 2 'the following arguments are required: --confirm' reset
pass after_invalid inspect S04

wrong_id_file=$(mktemp "$PWD/secrets/wrong-fixture-id.XXXXXXXX")
cat /proc/sys/kernel/random/uuid >"$wrong_id_file"
SOURCE_FIXTURE_ID_FILE="$wrong_id_file" reject reset_identity 1 '"sqlstate": "55000"' reset --confirm
pass after_wrong_identity inspect S04
reject reset_fault 1 'forced failure after cleanup and before S00 inserts' reset --confirm --fail-after-cleanup
pass after_reset_fault inspect S04
pass reset-first reset --confirm
pass after_reset_first inspect S00
advance_to_s04 second
pass second-S04-inspect inspect S04
pass reset-repeat reset --confirm
pass after_reset_repeat inspect S00

python3 - "$evidence" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])

def event(file, label):
    return next(row for row in map(json.loads, (root / f"{file}.log").read_text().splitlines())
                if row["event"] == label)

def same_snapshot(file, baseline):
    actual, expected = (event(name, "inspection") for name in (file, baseline))
    for field in ("rows", "receipts"):
        assert actual[field] == expected[field], (file, baseline, field)

for file, baseline in {
    "after_skip_bootstrap": "fresh",
    "after_skip_S01": "inspect-S00",
    "after_repeat_S01": "inspect-S01",
    "after_rollback_S04": "inspect-S03",
    "after_invalid": "inspect-S04",
    "after_wrong_identity": "inspect-S04",
    "after_reset_fault": "inspect-S04",
    "second-S04-inspect": "inspect-S04",
    "after_reset_first": "inspect-S00",
    "after_reset_repeat": "inspect-S00",
}.items():
    same_snapshot(file, baseline)

for file, final, visible in (
    ("rollback-S04", "after_rollback", False), ("run-S04", "after_commit", True),
):
    staged, before, after = (event(file, label) for label in ("writer_staged", "before_commit", final))
    assert staged["backend_pid"] != before["backend_pid"] == after["backend_pid"]
    assert list(staged["s04_visible"].values()) == [True] * 4
    assert list(before["s04_visible"].values()) == [False] * 4
    assert list(after["s04_visible"].values()) == [visible] * 4
    assert all(not row["differences"] for row in (staged, before, after))

assert not event("reset_fault", "writer_after_cleanup")["differences"]
assert event("reset_fault", "after_rollback")["prior_state_preserved"]
resources = event("run-S00", "resources")
assert (resources["python"], resources["driver"], resources["driver_impl"]) == ("3.12.12", "3.2.13", "binary")
controls = resources["cgroup"]
assert controls["memory.max"] == "268435456"
assert controls["memory.swap.max"] == "0"
assert controls["cpu.max"] == "50000 100000"
assert 0 < int(controls["memory.peak"]) <= 268435456
assert "oom_kill 0" in controls["memory.events"].splitlines()
print("Exact checkpoint, rejection, reset, atomic visibility and resource checks passed")
PY
