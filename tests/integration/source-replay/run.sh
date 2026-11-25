#!/usr/bin/env bash
# Run against the verified disposable source and provisioned fixture roles.
set -euo pipefail
: "${COMPOSE_PROJECT_NAME:?set the verified source project}"
: "${SOURCE_INPUT_ID:?set the verified source network ID}"
run_id=${1:?usage: run.sh RUN_ID NEW_EVIDENCE_DIR}
evidence=${2:?usage: run.sh RUN_ID NEW_EVIDENCE_DIR}
[[ "$run_id" =~ ^[0-9]{8}T[0-9]{6}Z-p01-[0-9]{2}$ ]]
docker_cmd=(docker --host unix:///var/run/docker.sock)
compose=("${docker_cmd[@]}" compose -f compose.source.yaml -f compose.runner.yaml --profile source)
source_id=$("${compose[@]}" ps -q source-db)
test "$("${docker_cmd[@]}" inspect -f '{{.State.Health.Status}}' "$source_id")" = healthy
test "$("${docker_cmd[@]}" inspect -f '{{range .NetworkSettings.Networks}}{{.NetworkID}}{{end}}' "$source_id")" = "$SOURCE_INPUT_ID"
test "$("${docker_cmd[@]}" inspect -f '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}' "$source_id")" = "${COMPOSE_PROJECT_NAME}_source-pg"
test -z "$("${docker_cmd[@]}" port "$source_id")"
mkdir -m 0700 -- "$evidence"
evidence=$(realpath -- "$evidence")
"${compose[@]}" run --rm --no-deps -T --entrypoint 'timeout --kill-after=2s 120s' \
    -e PYTHONPATH=/app \
    -v "$PWD/tests/integration/source-replay/run.py:/app/replay_experiment.py:ro" \
    -v "$evidence:/evidence" \
    fixture-runner python -B /app/replay_experiment.py "$run_id" | tee "$evidence/summary.txt"
