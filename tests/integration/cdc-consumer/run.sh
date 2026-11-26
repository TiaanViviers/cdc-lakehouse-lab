#!/usr/bin/env bash
# Run only from a fresh repo copy in the scheduled disconnected guest.
set -eEuo pipefail
umask 077
cd "$(dirname "$0")/../../.."
media=$(realpath "${1:?read-only staging media path}")
revision=${CDC_REVISION:?set tested revision}
overlay=${CDC_OVERLAY:?set guest overlay identity}
[[ $revision =~ ^[0-9a-f]{40}$ && $overlay =~ ^[a-zA-Z0-9_.-]+$ ]]
test "$(id -u)" = 0
test "$(findmnt -no OPTIONS --target "$media")" != "$(findmnt -no OPTIONS --target /)"
findmnt -no OPTIONS --target "$media" | tr , '\n' | grep -Fxq ro
test -z "$(ip -4 route show default; ip -6 route show default)"
[[ $(ls /sys/class/net | sort | paste -sd ' ') == 'docker0 lo' ]]
unset DOCKER_CONTEXT DOCKER_HOST COMPOSE_FILE COMPOSE_PROFILES SOURCE_INPUT_ID
run=$(date -u +%Y%m%dt%H%M%Sz)-$(openssl rand -hex 2)
export COMPOSE_PROJECT_NAME="cdc25-$run"
bridge="p25${run:9:6}${run:17:4}"
group="g25_${run/-/_}"
publication="p25_${run/-/_}"
slot="s25_${run/-/_}"
evidence="artifacts/EXP-015/$run"
consumer=scripts/cdc/consumer
mkdir -p "$evidence"
mkdir -m 0700 secrets
exec > >(tee "$evidence/run.txt") 2>&1
trap 'echo "assertion or command failed at line $LINENO (exit $?)" >&2' ERR
printf 'owner=2.5/Codex ticket=42 run=%s revision=%s overlay=%s project=%s bridge=%s database=source_lab consumer_db=postgres group=%s publication=%s slot=%s\n' \
    "$run" "$revision" "$overlay" "$COMPOSE_PROJECT_NAME" "$bridge" "$group" "$publication" "$slot"
echo 'Budgets: run 480s, parity 60s, poll 500ms after read, source/consumer PG volume <512MiB, WAL <256MiB, consumer tmpfs 64MiB, guest free >=1GiB'
read -r up _ </proc/uptime
start_cs=${up/./}
docker_cmd=(timeout --foreground -k 2s 25s docker --host unix:///var/run/docker.sock)
d() { "${docker_cmd[@]}" "$@"; }
stack() { d compose -f compose.source.yaml -f compose.cdc.yaml --profile source --profile cdc "$@"; }
src() {
    timeout --foreground -k 1s 8s docker --host unix:///var/run/docker.sock exec -i --user postgres "$source_id" sh -ec '
        export PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")"
        export PGREQUIREAUTH=scram-sha-256 PGCONNECT_TIMEOUT=2 PGOPTIONS="-c statement_timeout=5000"
        exec psql -XwqAt -v ON_ERROR_STOP=1 -h 127.0.0.1 -U source_admin -d source_lab "$@"
    ' sh "$@"
}
sql() { bash "$consumer/psql.sh" "$consumer_id" "$@"; }
status() {
    local up unused
    read -r up unused </proc/uptime
    bash "$consumer/status.sh" "$consumer_id" "$group" "$run" "$1" "$(( (10#${up/./} - 10#$start_cs) * 10 ))"
}
owned() {
    [[ $(d inspect -f '{{index .Config.Labels "com.docker.compose.project"}}/{{index .Config.Labels "com.docker.compose.service"}}' "$1") == "$COMPOSE_PROJECT_NAME/$2" ]] &&
    [[ $(d inspect -f '{{len .NetworkSettings.Networks}} {{range .NetworkSettings.Networks}}{{.NetworkID}}{{end}}' "$1") == "1 $SOURCE_INPUT_ID" ]]
}
volume_owned() {
    [[ $(d volume inspect -f '{{index .Labels "com.docker.compose.project"}}/{{index .Labels "com.docker.compose.volume"}}' "$COMPOSE_PROJECT_NAME"_"$1") == "$COMPOSE_PROJECT_NAME/$1" ]]
}
# Only remove assets enumerated from the fresh project after matching their identities.
cleanup() {
    local rc=$? id svc volume fw rule
    trap - EXIT ERR TERM
    set +e
    if [[ -n ${SOURCE_INPUT_ID:-} ]]; then
        for id in $(d ps -aq --no-trunc --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME"); do
            svc=$(d inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' "$id")
            if [[ $svc != cdc-catalog && $svc != source-db ]] || ! owned "$id" "$svc"; then
                echo 'Cleanup refused: unexpected container identity'
                exit 1
            fi
        done
        for volume in $(d volume ls -q --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME"); do
            if [[ $volume != "$COMPOSE_PROJECT_NAME"_source-pg && $volume != "$COMPOSE_PROJECT_NAME"_cdc-pg ]] ||
                ! volume_owned "${volume#"$COMPOSE_PROJECT_NAME"_}"; then
                echo 'Cleanup refused: unexpected volume identity'
                exit 1
            fi
        done
        # A failed trial may leave a slot in its private source cluster. Dispose of
        # the exact project only while no other endpoints are attached.
        if [[ $(d network inspect -f '{{len .Containers}}' "$SOURCE_INPUT_ID") != "$(d ps -q --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" | wc -l)" ]]; then
            echo 'Cleanup refused: unexpected bridge peers'
            exit 1
        fi
        stop_checked cdc-catalog || rc=1
        stop_checked source-db || rc=1
        stack down --volumes || rc=1
        d network rm "$SOURCE_INPUT_ID" || rc=1
        for rule in "${firewall_rules[@]}"; do
            read -r fw chain <<< "$rule"
            if [[ $chain == INPUT ]]; then
                "$fw" -D INPUT -i "$bridge" -j DROP || rc=1
            else
                "$fw" -D DOCKER-USER -i "$bridge" ! -o "$bridge" -j DROP || rc=1
            fi
        done
        [[ -z $(d ps -aq --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME") &&
           -z $(d volume ls -q --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME") &&
           -z $(d network ls -q --filter "name=^${COMPOSE_PROJECT_NAME}-input$") &&
           ! -e /sys/class/net/$bridge ]] || rc=1
    fi
    rm -f secrets/{source-db,cdc-catalog,fixture-owner}-password secrets/health-original || rc=1
    rmdir secrets || rc=1
    echo "project_cleanup_exit=$rc"
    exit "$rc"
}
stop_checked() {
    local svc=$1 id result
    id=$(stack ps -aq "$svc") || return
    [[ -n $id ]] || return 0
    stack stop -t 12 "$svc" || return
    result=$(d inspect -f '{{.State.Status}} {{.State.ExitCode}} {{.State.OOMKilled}}' "$id") || return
    echo "$svc stop: $result"
    [[ $result == 'exited 0 false' ]]
}
sample() {
    local cid=$1 service=$2 volume=$3 expected=$4
    owned "$cid" "$service"
    volume_owned "$volume"
    d volume inspect -f '{{.Name}} {{json .Labels}}' "${COMPOSE_PROJECT_NAME}_$volume"
    test "$(d inspect -f '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}}:{{.Destination}}{{end}}{{end}}' "$cid")" = "${COMPOSE_PROJECT_NAME}_$volume:$expected"
    test -z "$(d port "$cid")"
    test "$(d inspect -f '{{.HostConfig.Privileged}} {{.State.OOMKilled}}' "$cid")" = 'false false'
    d inspect -f 'id={{.Id}} image={{.Image}} memory={{.HostConfig.Memory}} swap={{.HostConfig.MemorySwap}} cpu={{.HostConfig.NanoCpus}} pids={{.HostConfig.PidsLimit}} log={{json .HostConfig.LogConfig}}' "$cid"
    d exec "$cid" sh -ec '
        for f in memory.max memory.swap.max memory.peak memory.events cpu.max cpu.stat pids.max pids.current; do
            printf "%s " "$f"; tr "\n" "|" < "/sys/fs/cgroup/$f"; echo
        done
        test "$(cat /sys/fs/cgroup/memory.swap.max)" = 0
        test "$(cat /sys/fs/cgroup/pids.max)" = 128
        test "$(awk '"'"'$1=="oom" || $1=="oom_kill" {sum+=$2} END {print sum+0}'"'"' /sys/fs/cgroup/memory.events)" = 0
        test "$(cat /sys/fs/cgroup/memory.max)" = "$2"
        test "$(cat /sys/fs/cgroup/cpu.max)" = "$3"
        du -sk "$1" "$PGDATA/pg_wal" /tmp
        test "$(du -sk "$1" | cut -f1)" -lt 524288
        test "$(du -sk "$PGDATA/pg_wal" | cut -f1)" -lt 262144
        test "$(df -Pk "$PGDATA" | awk '"'"'NR==2 {print $4}'"'"')" -ge 1048576
    ' sh "$expected" "$([[ $service == cdc-catalog ]] && echo 536870912 || echo 805306368)" \
        "$([[ $service == cdc-catalog ]] && echo '75000 100000' || echo '100000 100000')"
    d exec "$cid" sh -ec 'ls /sys/class/net; cat /proc/net/route; readlink /proc/1/ns/net; readlink /proc/1/ns/pid'
}
health() {
    local cid=$1 want=$2 state
    for ((n=0; n<60; n++)); do
        state=$(d inspect -f '{{.State.Status}} {{.State.Health.Status}}' "$cid")
        if [[ $state == "running $want" ]]; then echo "health $state"; return; fi
        [[ $state == running* ]] || break
        sleep 1
    done
    echo "Expected $want, observed $state"
    return 1
}
images=$(sed -n 's/^    image: //p' compose.source.yaml compose.cdc.yaml)
readarray -t refs <<< "$images"
d version --format 'engine={{.Server.Version}}'
d compose version
d info --format 'cgroup={{.CgroupVersion}} firewall={{json .FirewallBackend}}'
uname -sr
ip -br link
test -z "$(d ps -q)"
test -z "$(d ps -aq --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME")"
test -z "$(d volume ls -q --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME")"
test -z "$(d network ls -q --filter "name=^${COMPOSE_PROJECT_NAME}-input$")"
test "$(df -Pk "$(d info -f '{{.DockerRootDir}}')" | awk 'NR==2 {print $4}')" -ge 1048576
(cd "$media" && sha256sum -c SHA256SUMS && sha256sum source.tar consumer.tar probe.tar)
test "$(cat "$media/revision")" = "$revision"
python3 "$consumer/image.py" verify "$media/consumer.tar"
for account in source-db cdc-catalog fixture-owner; do openssl rand -hex 24 > "secrets/$account-password"; done
chmod 0444 secrets/{source-db,cdc-catalog}-password
firewall_rules=()
trap cleanup EXIT
trap 'exit 124' TERM
for fw in iptables ip6tables; do
    test "$("$fw" -S FORWARD | awk '$1=="-A" {print; exit}')" = '-A FORWARD -j DOCKER-USER'
done
test ! -e "/sys/class/net/$bridge"
SOURCE_INPUT_ID=$(d network create --internal --ipv6 --opt "com.docker.network.bridge.name=$bridge" "$COMPOSE_PROJECT_NAME-input")
export SOURCE_INPUT_ID
for fw in iptables ip6tables; do
    "$fw" -I INPUT 1 -i "$bridge" -j DROP
    firewall_rules+=("$fw INPUT")
    "$fw" -I DOCKER-USER 1 -i "$bridge" ! -o "$bridge" -j DROP
    firewall_rules+=("$fw DOCKER-USER")
done
d network inspect -f '{{.Id}} {{.Name}} {{.Driver}} internal={{.Internal}} ipv6={{.EnableIPv6}} {{json .IPAM.Config}}' "$SOURCE_INPUT_ID"
stack config > "$evidence/compose.resolved.yaml"
test "$(d network inspect -f '{{len .Containers}}' "$SOURCE_INPUT_ID")" = 0
# A missing local artifact must fail at Compose create with the no-pull profile.
if d image inspect "${refs[1]}" >/dev/null 2>&1; then
    echo 'Expected a fresh guest without the consumer image'
    exit 1
fi
if stack up -d --no-deps --no-build --pull never cdc-catalog > "$evidence/missing-image.txt" 2>&1; then
    echo 'Missing image unexpectedly started'
    exit 1
fi
grep -i 'No such image' "$evidence/missing-image.txt"
test -z "$(stack ps -aq cdc-catalog)"
for artifact in source consumer probe; do
    timeout --foreground -k 2s 90s docker --host unix:///var/run/docker.sock load -i "$media/$artifact.tar"
done
for ref in "${refs[@]}"; do
    found=$(d image inspect "$ref" -f '{{.Os}}/{{.Architecture}} {{.Id}}')
    echo "$ref $found"
    test "$found" = "linux/amd64 ${ref##*@}"
done
d image ls --tree pgducklake/pipe-ci-builds
timeout --foreground -k 2s 75s python3 -u scripts/isolation/preflight.py --start-compose "$PWD/compose.source.yaml"
source_id=$(d inspect -f '{{.Id}}' "$(stack ps -q source-db)")
owned "$source_id" source-db
health "$source_id" healthy
test "$(src -c "SELECT current_setting('server_version_num'), current_setting('shared_preload_libraries')")" = '160016|'
test "$(src -c 'SELECT (SELECT count(*) FROM pg_publication), (SELECT count(*) FROM pg_replication_slots)')" = '0|0'
src -v disposable_id="$(cat /proc/sys/kernel/random/uuid)" < sql/source/001_fixture_v1.sql
# One-table fixture, using the EXP-011 registration privileges on this fresh clone.
# Keep the Phase 1 fixture untouched. Publisher lifecycle implementation is 2.2.
{
    printf "\\set secret '%s'\n" "$(cat secrets/fixture-owner-password)"
    cat <<'SQL'
BEGIN;
CREATE ROLE probe_replicator LOGIN REPLICATION PASSWORD :'secret';
GRANT CONNECT, CREATE ON DATABASE source_lab TO probe_replicator;
CREATE SCHEMA probe AUTHORIZATION probe_replicator;
SET LOCAL ROLE probe_replicator;
CREATE TABLE probe.items (id integer PRIMARY KEY, value text NOT NULL);
INSERT INTO probe.items VALUES (1, 'file seed'), (2, 'second key');
COMMIT;
SQL
} | src 2>/dev/null
subnets=$(d network inspect -f '{{range .IPAM.Config}}{{println .Subnet}}{{end}}' "$SOURCE_INPUT_ID")
ipv4=$(awk '/[.]/ {print}' <<< "$subnets")
ipv6=$(awk '/:/ {print}' <<< "$subnets")
[[ $ipv4 =~ ^[0-9.]+/[0-9]+$ && $ipv6 =~ ^[0-9a-f:]+/[0-9]+$ ]]
d exec -i --user postgres "$source_id" sh -ec '
    { cat; cat "$PGDATA/pg_hba.conf"; } > "$PGDATA/pg_hba.cdc"
    mv "$PGDATA/pg_hba.cdc" "$PGDATA/pg_hba.conf"
' <<HBA
host source_lab probe_replicator $ipv4 scram-sha-256
host source_lab probe_replicator $ipv6 scram-sha-256
host all probe_replicator all reject
host replication probe_replicator all reject
HBA
test "$(src -c 'SELECT pg_reload_conf()')" = t
src -c "SELECT system_identifier FROM pg_control_system()"
test "$(d network inspect -f '{{len .Containers}}' "$SOURCE_INPUT_ID")" = 1
stack up -d --no-deps --no-build --pull never cdc-catalog
consumer_id=$(d inspect -f '{{.Id}}' "$(stack ps -q cdc-catalog)")
owned "$consumer_id" cdc-catalog
health "$consumer_id" healthy
test "$(d network inspect -f '{{len .Containers}}' "$SOURCE_INPUT_ID")" = 2
d network inspect -f '{{range .Containers}}{{println .Name .IPv4Address .IPv6Address}}{{end}}' "$SOURCE_INPUT_ID"
sample "$source_id" source-db source-pg /var/lib/postgresql/data
sample "$consumer_id" cdc-catalog cdc-pg /var/lib/postgresql
sql <<'SQL'
SELECT version();
SHOW shared_preload_libraries;
SHOW password_encryption;
SHOW duckpipe.query_routing;
SELECT extname, extversion FROM pg_extension ORDER BY extname;
SELECT duckdb.raw_query('SELECT version()');
SELECT name, setting, unit, source FROM pg_settings
WHERE name IN ('max_connections','shared_buffers','duckdb.memory_limit','duckdb.threads',
               'duckdb.temporary_directory','duckdb.max_temp_directory_size')
ORDER BY name;
SELECT line_number,type,database,user_name,address,auth_method,error
FROM pg_hba_file_rules WHERE rule_number IS NOT NULL ORDER BY rule_number;
SQL
test "$(sql -c "SELECT current_setting('server_version_num'), current_setting('shared_preload_libraries'), current_setting('duckpipe.query_routing')")" = '180004|pg_duckdb,pg_ducklake,pg_duckpipe|off'
test "$(sql -c "SELECT string_agg(extname||'='||extversion, ',' ORDER BY extname) FROM pg_extension WHERE extname LIKE 'pg_duck%'")" = 'pg_duckdb=1.1.0,pg_ducklake=0.1.0,pg_duckpipe=1.0.0'
test "$(sql -c 'SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL')" = 0
test "$(sql -c "SELECT count(*) FROM pg_hba_file_rules WHERE auth_method='trust' AND type<>'local' AND coalesce(address,'') NOT IN ('127.0.0.1','::1')")" = 0
test "$(sql -c "SELECT current_setting('max_connections'), current_setting('shared_buffers'), current_setting('duckdb.threads'), current_setting('duckdb.memory_limit'), current_setting('duckdb.max_temp_directory_size')")" = '20|64MB|1|96MB|48MiB'
d exec "$consumer_id" sh -ec '
    sha256sum /docker-entrypoint-initdb.d/*;
    lib=$(pg_config --pkglibdir)
    sha256sum "$lib"/pg_duck*.so "$lib"/libduckdb.so "$lib"/ducklake.duckdb_extension
'
test "$(d exec --user postgres "$consumer_id" env -u PGPASSWORD -u PGPASSFILE PGREQUIREAUTH=none \
    psql -h 127.0.0.1 -U postgres -d postgres -XwAtqc 'SELECT inet_client_addr()')" = 127.0.0.1
echo 'Loopback TCP succeeds with require_auth=none and no password'
peer() {
    d run --rm -i --pull never --network "$SOURCE_INPUT_ID" --memory 96m --memory-swap 96m --cpus .5 \
        --pids-limit 32 --read-only --cap-drop ALL --entrypoint sh "${refs[0]}" -ec '
        IFS= read -r PGPASSWORD
        export PGPASSWORD PGREQUIREAUTH=scram-sha-256 PGCONNECT_TIMEOUT=2 LC_ALL=C
        exec psql -XwqAt -v ON_ERROR_STOP=1 -h cdc-catalog -U postgres -d postgres "$@"
    ' sh "$@"
}
peer -c 'SELECT current_user, current_database(), inet_client_addr(), inet_server_addr()' < secrets/cdc-catalog-password
if printf '%s\n' wrong | peer -c 'SELECT 1' > "$evidence/bad-peer.txt" 2>&1; then
    echo 'Bad peer password accepted'
    exit 1
fi
grep -F 'password authentication failed' "$evidence/bad-peer.txt"
status before-registration | tee "$evidence/before-registration.json"
python3 -c 'import json,sys; x=json.load(sys.stdin); assert x["group"] is None and not x["worker_pids"] and not x["mappings"]' \
    < "$evidence/before-registration.json"

# Update the Compose bind mount in place so the health check and adapter read
# the wrong password while the server retains the correct SCRAM verifier.
cp secrets/cdc-catalog-password secrets/health-original
printf '%s\n' wrong > secrets/cdc-catalog-password
health "$consumer_id" unhealthy
d inspect -f '{{range .State.Health.Log}}{{println .ExitCode .Output}}{{end}}' "$consumer_id" > "$evidence/bad-health.txt"
grep -F 'password authentication failed' "$evidence/bad-health.txt"
if status bad-credentials > "$evidence/bad-status.txt" 2>&1; then exit 1; fi
test "$(cat "$evidence/bad-status.txt")" = 'consumer status query failed'
cat secrets/health-original > secrets/cdc-catalog-password
rm secrets/health-original
health "$consumer_id" healthy
test "$(d network inspect -f '{{len .Containers}}' "$SOURCE_INPUT_ID")" = 2

sql < "$consumer/bootstrap.sql"
group_sql() { sql -v group="$group" -v publication="$publication" -v slot="$slot" "$@"; }
{
    printf "\\set secret '%s'\n" "$(cat secrets/fixture-owner-password)"
    cat <<'SQL'
SELECT duckpipe.create_group(:'group', publication => :'publication', slot_name => :'slot',
    conninfo => 'host=source-db port=5432 dbname=source_lab user=probe_replicator sslmode=disable password=' || :'secret',
    mode => 'bgworker');
SELECT duckpipe.add_table('probe.items', target_table => 'bronze.items', sync_group => :'group',
    copy_data => true, sync_mode => 'upsert');
SQL
} | group_sql 2>/dev/null
expected=$'1|file seed\n2|second key'
source_rows='SELECT id,value FROM probe.items ORDER BY id LIMIT 3'
bronze_rows=${source_rows/probe/bronze}
test "$(src -c "$source_rows")" = "$expected"
read_rows() {
    local limit=$((SECONDS+60)) rows last='none' attempt=0 timeout
    while (( SECONDS + 1 < limit )); do
        timeout=$((limit - SECONDS - 1))
        (( timeout < 8 )) || timeout=8
        attempt=$((attempt+1))
        if rows=$(CDC_SQL_TIMEOUT=$timeout sql -c "$bronze_rows" 2>/dev/null) && [[ $rows == "$expected" ]]; then
            printf 'checkpoint=%s attempt=%s previous=%s exact_rows:\n%s\n' "$1" "$attempt" "$last" "$rows"
            return
        fi
        last=${rows:-empty-or-query-failed}
        sleep .5
    done
    printf 'checkpoint=%s exact rows timed out, last observation=%s\n' "$1" "$last"
    return 1
}
observe_catalog() {
    python3 "$consumer/catalog.py" "$consumer_id" | tee "$evidence/$1.catalog.json"
}
read_rows initial
test "$(sql -c "SELECT amname FROM pg_class JOIN pg_am ON pg_am.oid=relam WHERE pg_class.oid='bronze.items'::regclass")" = ducklake
observe_catalog initial
status initial | tee "$evidence/initial.status.json"
# Freeze changes before flushing inline rows or reading physical references.
group_sql <<'SQL'
SELECT duckpipe.disable_group(:'group');
SELECT duckpipe.stop_worker(:'group');
SQL
status stopped-worker | tee "$evidence/stopped-worker.status.json"
python3 -c '
import json,sys
data=json.load(sys.stdin)
assert not data["group"]["enabled"] and data["worker_pids"] == []
assert [(m["source_table"],m["target_table"]) for m in data["mappings"]] == [("probe.items","bronze.items")]
assert not data["mapping_overflow"]
' < "$evidence/stopped-worker.status.json"
health "$consumer_id" healthy
test "$(src -c "SELECT slot_name, plugin, active FROM pg_replication_slots")" = "$slot|pgoutput|f"
# The supported scoped flush preserves connector-written data while materializing Parquet.
sql <<'SQL'
CALL ducklake.set_option('data_inlining_row_limit', 0, 'bronze.items'::regclass);
SELECT * FROM ducklake.flush_inlined_data('bronze.items'::regclass);
SQL
observe_catalog before-recreation
python3 -c '
import json,sys
x=json.load(sys.stdin)
assert any(r["key"]=="version" and r["value"]=="0.4" for r in x["options"])
assert any(r["key"]=="data_inlining_row_limit" and r["value"]=="0" for r in x["options"])
assert sum(f["record_count"] for f in x["data_files"]) == 2
assert all(f["magic"]=="PAR1" for f in x["data_files"])
' < "$evidence/before-recreation.catalog.json"
read_rows before-recreation
identity=$(sql -c 'SELECT system_identifier FROM pg_control_system()')
sample "$consumer_id" cdc-catalog cdc-pg /var/lib/postgresql
previous=$consumer_id
stop_checked cdc-catalog
stack up -d --force-recreate --no-deps --no-build --pull never cdc-catalog
consumer_id=$(d inspect -f '{{.Id}}' "$(stack ps -q cdc-catalog)")
test "$consumer_id" != "$previous"
owned "$consumer_id" cdc-catalog
health "$consumer_id" healthy
test "$(sql -c 'SELECT system_identifier FROM pg_control_system()')" = "$identity"
test "$(src -c "SELECT slot_name, plugin, active FROM pg_replication_slots")" = "$slot|pgoutput|f"
test "$(src -c 'SELECT pubname,schemaname,tablename FROM pg_publication_tables')" = "$publication|probe|items"
printf 'same_cluster=%s former_container=%s recreated_container=%s slot=%s\n' "$identity" "$previous" "$consumer_id" "$slot"
status recreated | tee "$evidence/recreated.status.json"
python3 - "$evidence/stopped-worker.status.json" "$evidence/recreated.status.json" <<'PY'
import json
from pathlib import Path
import sys

before, after = [json.loads(Path(f).read_text()) for f in sys.argv[1:]]
assert before["group"] == after["group"]
assert not after["worker_pids"] and not after["mapping_overflow"]
for field in ("source_table", "target_table", "snapshot_lsn", "applied_lsn"):
    assert before["mappings"][0][field] == after["mappings"][0][field]
PY
# A fresh authenticated session reads exact keys and values with the worker still stopped.
test "$(sql -c "$bronze_rows")" = "$expected"
sql -c "$bronze_rows"
observe_catalog recreated
cmp "$evidence/before-recreation.catalog.json" "$evidence/recreated.catalog.json"
test "$(d network inspect -f '{{len .Containers}}' "$SOURCE_INPUT_ID")" = 2
sample "$consumer_id" cdc-catalog cdc-pg /var/lib/postgresql
sample "$source_id" source-db source-pg /var/lib/postgresql/data

# Use the verified consumer API and explicitly check publisher quiescence and inventory.
group_sql <<'SQL'
SELECT duckpipe.remove_table('probe.items', drop_target => false, sync_group => :'group');
SELECT duckpipe.drop_group(:'group');
SQL
test "$(src -c 'SELECT (SELECT count(*) FROM pg_publication), (SELECT count(*) FROM pg_replication_slots)')" = '0|0'
echo 'publisher_after_drop=0 publications, 0 slots'
echo 'EXP-015 ACCEPTANCE CHECKS PASSED'
