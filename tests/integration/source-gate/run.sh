#!/usr/bin/env bash
# Run inside the disconnected lab VM, after the source startup gate and schema enrollment.
set -euo pipefail
umask 077
export LC_ALL=C

: "${COMPOSE_PROJECT_NAME:?set the verified disposable project}"
: "${SOURCE_INPUT_ID:?set its verified full bridge ID}"
: "${RUN_ID:?set the UTC Phase 1 run ID}"
: "${EVIDENCE_DIR:?set a new local evidence directory}"
[[ "$RUN_ID" =~ ^[0-9]{8}T[0-9]{6}Z-p01-[0-9]{2}$ ]]
[[ "$SOURCE_INPUT_ID" =~ ^[0-9a-f]{64}$ ]]
mkdir -m 0700 -- "$EVIDENCE_DIR"
evidence=$(realpath -- "$EVIDENCE_DIR")
here=tests/integration/source-gate
docker_cmd=(docker --host unix:///var/run/docker.sock)
source_compose=("${docker_cmd[@]}" compose -f compose.source.yaml --profile source)
fixture_compose=("${source_compose[@]}" -f compose.runner.yaml)
export SOURCE_FIXTURE_ID_FILE="secrets/${COMPOSE_PROJECT_NAME}-fixture-id"
disposable_id=$(<"$SOURCE_FIXTURE_ID_FILE")
[[ "$disposable_id" =~ ^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$ ]]
test "$disposable_id" != 00000000-0000-0000-0000-000000000000
image=$(sed -n 's/^    image: //p' compose.source.yaml)

# Check the running endpoint and its volume before any fixture command.
source_id=$("${source_compose[@]}" ps -q source-db)
volume="${COMPOSE_PROJECT_NAME}_source-pg"
test "$("${docker_cmd[@]}" inspect -f '{{.State.Health.Status}}' "$source_id")" = healthy
test "$("${docker_cmd[@]}" inspect -f '{{.Image}}' "$source_id")" = "$("${docker_cmd[@]}" image inspect -f '{{.Id}}' "$image")"
test "$("${docker_cmd[@]}" inspect -f '{{len .NetworkSettings.Networks}} {{range .NetworkSettings.Networks}}{{.NetworkID}}{{end}}' "$source_id")" = "1 $SOURCE_INPUT_ID"
test -z "$("${docker_cmd[@]}" port "$source_id")"
test "$("${docker_cmd[@]}" inspect -f '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Type}} {{.Name}}{{end}}{{end}}' "$source_id")" = "volume $volume"
test "$("${docker_cmd[@]}" volume inspect -f '{{.Driver}} {{index .Labels "com.docker.compose.project"}} {{index .Labels "com.docker.compose.volume"}}' "$volume")" = "local $COMPOSE_PROJECT_NAME source-pg"
test "$("${docker_cmd[@]}" network inspect -f '{{.Id}} {{.Driver}} {{.Internal}} {{.EnableIPv6}} {{len .Containers}}' "$SOURCE_INPUT_ID")" = "$SOURCE_INPUT_ID bridge true true 1"
bridge=$("${docker_cmd[@]}" network inspect -f '{{index .Options "com.docker.network.bridge.name"}}' "$SOURCE_INPUT_ID")
python3 - "${bridge:-br-${SOURCE_INPUT_ID:0:12}}" <<'PY'
import sys
from scripts.isolation.preflight import check_firewall

check_firewall(sys.argv[1])
PY

admin_psql=("${source_compose[@]}" exec -T source-db sh -ec '
    PGPASSWORD=$(cat "$POSTGRES_PASSWORD_FILE")
    export PGPASSWORD PGCONNECT_TIMEOUT=3 PGREQUIREAUTH=scram-sha-256
    export PGOPTIONS="-c statement_timeout=5000 -c lock_timeout=2000"
    exec psql -w -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"
' sh)
admin() { "${admin_psql[@]}" -XwqAt -v ON_ERROR_STOP=1 "$@"; }

peer_psql() {
    local role=$1
    shift
    "${docker_cmd[@]}" run --rm -i --pull never --network "$SOURCE_INPUT_ID" \
        --memory 96m --cpus 0.5 --pids-limit 32 --read-only --cap-drop ALL \
        --env PGCONNECT_TIMEOUT=3 --env PGREQUIREAUTH=scram-sha-256 \
        --env 'PGOPTIONS=-c statement_timeout=5000 -c lock_timeout=2000' \
        --entrypoint sh "$image" -ec '
            IFS= read -r PGPASSWORD
            export PGPASSWORD
            role=$1
            shift
            exec psql -XwqAt -v ON_ERROR_STOP=1 -h source-db -U "$role" -d source_lab "$@"
        ' sh "$role" "$@"
}

capture_logs() {
    # Keep selected lines. SQL statements could contain bootstrap credentials.
    "${source_compose[@]}" logs --no-color source-db |
        awk '/connection authenticated:|password authentication failed for user|checkpoint (starting|complete)|database system is ready|shutting down|database system is shut down/' \
        >"$evidence/source.log"
}
trap capture_logs EXIT

test "$(admin -v "disposable_id=$disposable_id" -f - <<'SQL'
SELECT EXISTS (
    SELECT FROM fixture.installation AS i JOIN pg_database AS db ON db.oid = i.database_oid
    WHERE i.schema_version = 1 AND i.disposable_id = :'disposable_id'::uuid
      AND current_database() = 'source_lab' AND db.datname = current_database()
      AND i.system_identifier = (SELECT system_identifier FROM pg_control_system())
);
SQL
)" = t
cat >"$evidence/run.txt" <<META
run_id=$RUN_ID
project=$COMPOSE_PROJECT_NAME
source_id=$source_id
bridge_id=$SOURCE_INPUT_ID
volume=$volume
start_utc=$(date -u +%FT%TZ)
META

engine_limits=$("${docker_cmd[@]}" inspect -f '{{.HostConfig.Memory}} {{.HostConfig.MemorySwap}} {{.HostConfig.NanoCpus}} {{.HostConfig.PidsLimit}} {{.HostConfig.ShmSize}} {{.HostConfig.LogConfig.Type}} {{index .HostConfig.LogConfig.Config "max-size"}} {{index .HostConfig.LogConfig.Config "max-file"}}' "$source_id")
printf 'memory_bytes swap_inclusive_bytes nano_cpus pids shm_bytes log_driver log_file_size log_files\n%s\n' \
    "$engine_limits" >"$evidence/source-limits.txt"
test "$engine_limits" = '805306368 805306368 1000000000 128 134217728 local 5m 3'
test "$("${docker_cmd[@]}" exec "$source_id" cat /sys/fs/cgroup/{memory.max,memory.swap.max,cpu.max,pids.max})" \
    = "$(printf '805306368\n0\n100000 100000\n128')"
"${docker_cmd[@]}" image inspect -f '{{.Os}}/{{.Architecture}} {{.Id}} {{json .RepoDigests}}' "$image" >"$evidence/source-image.txt"
"${source_compose[@]}" config >"$evidence/source-compose.yaml"
"${fixture_compose[@]}" --profile generator config >"$evidence/runner-compose.yaml"
runner_image=$("${fixture_compose[@]}" --profile generator config --format json |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["fixture-runner"]["image"])')
"${docker_cmd[@]}" image inspect -f '{{.Os}}/{{.Architecture}} {{.Id}}' "$runner_image" >"$evidence/runner-image.txt"
"${admin_psql[@]}" --version >"$evidence/psql-version.txt"

admin -f - >"$evidence/settings.txt" <<'SQL'
SELECT version();
SELECT name, setting, unit, source FROM pg_settings
WHERE name IN ('max_connections', 'shared_buffers', 'password_encryption', 'wal_level',
               'max_wal_senders', 'max_replication_slots', 'max_slot_wal_keep_size', 'wal_keep_size',
               'min_wal_size', 'max_wal_size', 'checkpoint_timeout', 'wal_segment_size',
               'archive_mode', 'logging_collector', 'log_connections') ORDER BY name;
SELECT line_number, type, database, user_name, address, auth_method, error
FROM pg_hba_file_rules ORDER BY line_number;
SQL
test "$(admin -c "SELECT current_setting('server_version_num'), current_setting('max_connections'), current_setting('password_encryption'), count(*) FILTER (WHERE error IS NOT NULL) FROM pg_hba_file_rules;")" \
    = '160016|20|scram-sha-256|0'
for role in source_fixture_writer source_fixture_reader; do
    secret="secrets/source-fixture-${role##*_}-password"
    peer_psql "$role" -c 'SELECT current_user, current_database(), inet_client_addr() IS NOT NULL;' \
        <"$secret" >"$evidence/$role.auth"
    test "$(<"$evidence/$role.auth")" = "$role|source_lab|t"
    if peer_psql "$role" -c 'SELECT 1;' <<< 'incorrect-phase-1-password' >"$evidence/$role.reject" 2>&1; then
        echo "Unexpected password acceptance for $role" >&2
        exit 1
    fi
    grep -Fq "password authentication failed for user \"$role\"" "$evidence/$role.reject"
done

sample_source() {
    local label=$1 disk data_kib wal_kib available_kib counters
    local -a disk_fields
    disk=$("${docker_cmd[@]}" exec "$source_id" sh -ec '
        du -sk "$PGDATA" | cut -f1
        du -sk "$PGDATA/pg_wal" | cut -f1
        df -Pk "$PGDATA" | awk "NR == 2 {print \$4}"
    ')
    mapfile -t disk_fields <<< "$disk"
    read -r data_kib wal_kib available_kib <<< "${disk_fields[*]}"
    printf '%s data_kib=%s wal_kib=%s free_kib=%s\n' "$label" "$data_kib" "$wal_kib" "$available_kib" >>"$evidence/storage.txt"
    counters=$("${docker_cmd[@]}" exec "$source_id" sh -ec '
        for key in memory.current memory.peak memory.events cpu.stat; do
            echo "$key"
            cat "/sys/fs/cgroup/$key"
        done
    ')
    printf '%s\n%s\n' "$label" "$counters" >>"$evidence/source-cgroup.txt"
    if ! (( data_kib > 0 && data_kib < 524288 && wal_kib > 0 && wal_kib < 262144 && available_kib >= 1048576 )) ||
        ! grep -Fxq 'oom 0' <<< "$counters" || ! grep -Fxq 'oom_kill 0' <<< "$counters"; then
        echo "Source stop threshold reached at $label. Pausing writes and stopping source." >&2
        "${source_compose[@]}" stop source-db
        return 1
    fi
    admin -v "label=$label" -f - >>"$evidence/wal.txt" <<'SQL'
SELECT :'label', clock_timestamp(), pg_current_wal_insert_lsn(), pg_current_wal_lsn(),
       pg_current_wal_flush_lsn(), (SELECT count(*) FROM pg_ls_waldir()),
       (SELECT coalesce(sum(size), 0) FROM pg_ls_waldir()),
       (SELECT count(*) FROM pg_publication), (SELECT count(*) FROM pg_replication_slots);
SQL
    test "$(tail -1 "$evidence/wal.txt" | cut -d '|' -f8,9)" = '0|0'
}

snapshot() {
    local checkpoint=$1 label=$2
    shift 2
    peer_psql source_fixture_reader -c "$(<"$here/snapshot.sql")" \
        <secrets/source-fixture-reader-password >"$evidence/$label.json"
    PYTHONPATH=. python3 "$here/compare.py" "$checkpoint" "$evidence/$label.json" "$@" |
        tee -a "$evidence/comparisons.jsonl"
}

runner() {
    local label=$1
    shift
    if ! "${fixture_compose[@]}" run --rm --no-deps -T fixture-runner --run-id "$RUN_ID" "$@" \
        </dev/null >"$evidence/$label.jsonl" 2>"$evidence/$label.stderr"; then
        cat "$evidence/$label.jsonl" "$evidence/$label.stderr" >&2
        return 1
    fi
}

test "$(admin -c "SELECT current_setting('wal_level'), current_setting('max_wal_senders'), current_setting('max_replication_slots'), current_setting('max_slot_wal_keep_size'), current_setting('wal_keep_size'), current_setting('max_wal_size'), current_setting('archive_mode');")" \
    = 'logical|2|2|128MB|0|128MB|off'
printf 'label|utc|insert_lsn|write_lsn|flush_lsn|wal_files|wal_logical_bytes|publications|slots\n' >"$evidence/wal.txt"
sample_source baseline
snapshot empty baseline
bash tests/integration/source-schema/run.sh "$evidence/schema" "$disposable_id" "${admin_psql[@]}" |
    tee "$evidence/schema-summary.txt"
sample_source after-schema
snapshot empty after-schema --reference "$evidence/baseline.json"

for step in S00 S01 S02 S03 S04 S05 S06; do
    runner "run-$step" --attempt "$((901 + 10#${step#S}))" run "$step"
    case "$step" in
        S05) snapshot "$step" "$step" --receipt-reference "$evidence/S04.json" ;;
        S06) snapshot "$step" "$step" --reference "$evidence/S05.json" ;;
        *) snapshot "$step" "$step" ;;
    esac
    sample_source "after-$step"
done
runner run-reset --attempt 908 reset --confirm
snapshot S00 reset --reference "$evidence/S00.json"
sample_source after-reset

# The existing sequential harness requires an empty fixture. Clear only the enrolled fixture
# via the same guarded SQL interface after recording the requested S00 restore.
admin -v "disposable_id=$disposable_id" -f - >"$evidence/cleanup-for-failures.txt" <<'SQL'
SET SESSION AUTHORIZATION source_fixture_writer;
SELECT fixture.cleanup(true, :'disposable_id'::uuid);
SQL
bash tests/integration/source-runner/run.sh "$RUN_ID" "$evidence/sequential"
sample_source after-sequential
bash tests/integration/source-overlap/run.sh "$RUN_ID" "$evidence/overlap"
sample_source after-overlap
bash tests/integration/source-replay/run.sh "$RUN_ID" "$evidence/replay"
sample_source after-replay
runner run-final-reset --attempt 909 reset --confirm
snapshot S00 final-reset --reference "$evidence/S00.json"
sample_source final
"${docker_cmd[@]}" stats --no-stream --format '{{.CPUPerc}} {{.MemUsage}} {{.BlockIO}} {{.PIDs}}' "$source_id" >"$evidence/source-stats.txt"
printf 'end_utc=%s\n' "$(date -u +%FT%TZ)" >>"$evidence/run.txt"
printf '%s all Phase 1 source-gate checks passed\n' "$RUN_ID"
