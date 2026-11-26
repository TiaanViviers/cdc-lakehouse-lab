#!/usr/bin/env bash
# Run from a fresh repository copy inside the scheduled, disconnected lab guest.
set -Eeuo pipefail
umask 077
export LC_ALL=C TZ=UTC
unset DOCKER_CONTEXT COMPOSE_ENV_FILES SOURCE_INPUT_ID
export COMPOSE_DISABLE_ENV_FILE=1

probe=tests/integration/remote-probe
media=${1:?usage: run.sh /path/to/read-only/image-media}
: "${PROBE_SHA:?set PROBE_SHA to the revision staged on the media}"
test -z "$(ip -4 route show default)$(ip -6 route show default)"
test "$(ip -o link show | awk -F ': ' '{print $2}' | sort | paste -sd ,)" = docker0,lo
test "$(id -u)" = 0

run=$(date -u +%Y%m%dt%H%M%Sz)
export COMPOSE_PROJECT_NAME="cdc21-$run"
group="g21_$run"
publication="pub21_$run"
slot="slot21_$run"
bridge="p21${run:9:6}"
evidence="$PWD/artifacts/EXP-011/$run"
mkdir -p "${evidence%/*}"
mkdir "$evidence"
mkdir -m 0700 secrets
exec </dev/null
exec > >(tee "$evidence/observations.log") 2>&1
echo "owner=2.1/Codex ticket=38 run=$run revision=$PROBE_SHA overlay=${PROBE_OVERLAY:?set PROBE_OVERLAY} project=$COMPOSE_PROJECT_NAME bridge=$bridge db=source_lab group=$group publication=$publication slot=$slot"
trap 'rc=$?; echo "probe step failed at line $LINENO (exit $rc)" >&2' ERR
uname -sr
sed -n '/^PRETTY_NAME=/p' /etc/os-release
echo "Budget: run 480s, checkpoint 60s, polls every 500ms after a read, WAL <256MiB, each PG volume <512MiB, consumer /tmp 64MiB, guest free >=1GiB"

docker_local() { docker --host unix:///var/run/docker.sock "$@"; }
source_compose() { docker_local compose -f compose.source.yaml --profile source "$@"; }
stack() { docker_local compose -f compose.source.yaml -f "$probe/compose.probe.yaml" --profile source "$@"; }
source_sql() {
    timeout -k 2s 8s docker --host unix:///var/run/docker.sock exec -i "$source_id" sh -ec '
        export PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")" PGREQUIREAUTH=scram-sha-256
        export PGOPTIONS="-c statement_timeout=5000" PGCONNECT_TIMEOUT=3
        exec psql -XwqAt -v ON_ERROR_STOP=1 -h 127.0.0.1 -U source_admin -d source_lab "$@"
    ' sh "$@"
}
consumer_sql() {
    timeout -k 2s 12s docker --host unix:///var/run/docker.sock exec -i --user postgres -e PGOPTIONS='-c statement_timeout=9000' \
        "$consumer_id" psql -XwqAt -v ON_ERROR_STOP=1 -U postgres -d postgres "$@"
}
publisher_state() { source_sql < "$probe/observe-source.sql"; }
consumer_state() { consumer_sql < "$probe/observe-consumer.sql"; }
catalog_state() { consumer_sql < "$probe/observe-catalog.sql"; }
redact() {
    python3 -c '
import re
import sys
from pathlib import Path

passwords = [f.read_text().strip() for f in Path("secrets").glob("*-password")]
for line in sys.stdin:
    for password in passwords:
        line = line.replace(password, "[redacted]")
    line = re.sub(r"(?i)\b(?:host|hostaddr|password|dbname|user|sslmode)=\S+", "[conninfo field]", line)
    sys.stdout.write(line)
'
}
fail() { echo "FAIL $*" >&2; exit 1; }
healthy() {
    local cid=$1
    for ((n=0; n<60; n++)); do
        state=$(docker_local inspect -f '{{.State.Status}} {{.State.Health.Status}}' "$cid")
        [[ $state != 'running healthy' ]] || return 0
        [[ $state != exited* && $state != *unhealthy ]] || break
        sleep 1
    done
    fail "health $cid ($state)"
}
owned() {
    local cid=$1 service=$2
    test "$(docker_local inspect -f '{{index .Config.Labels "com.docker.compose.project"}}/{{index .Config.Labels "com.docker.compose.service"}}' "$cid")" = "$COMPOSE_PROJECT_NAME/$service" &&
    test "$(docker_local inspect -f '{{range .NetworkSettings.Networks}}{{.NetworkID}}{{end}}' "$cid")" = "$SOURCE_INPUT_ID"
}
resources() {
    local cid=$1 service=$2 volume=$3
    echo "resources $service"
    docker_local inspect -f 'id={{.Id}} image={{.Image}} host_pid={{.State.Pid}} oom={{.State.OOMKilled}} memory={{.HostConfig.Memory}} swap={{.HostConfig.MemorySwap}} cpu={{.HostConfig.NanoCpus}} pids={{.HostConfig.PidsLimit}} ports={{json .HostConfig.PortBindings}} privileged={{.HostConfig.Privileged}} log={{json .HostConfig.LogConfig}}' "$cid"
    test -z "$(docker_local port "$cid")"
    test "$(docker_local inspect -f '{{.HostConfig.Privileged}} {{.State.OOMKilled}}' "$cid")" = 'false false'
    test "$(docker_local inspect -f '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}}{{end}}{{end}}' "$cid")" = "$volume"
    docker_local volume inspect -f '{{.Name}} {{json .Labels}}' "$volume"
    test "$(docker_local volume inspect -f '{{index .Labels "com.docker.compose.project"}}' "$volume")" = "$COMPOSE_PROJECT_NAME"
    docker_local exec "$cid" sh -ec '
        for f in memory.max memory.swap.max memory.peak memory.events cpu.max cpu.stat pids.max pids.current; do
            echo "$f"; cat "/sys/fs/cgroup/$f"
        done
        test "$(awk '"'"'$1=="oom" || $1=="oom_kill" {sum+=$2} END {print sum+0}'"'"' /sys/fs/cgroup/memory.events)" = 0
        path=$PGDATA
        if [ "$1" = probe-consumer ]; then
            path=/var/lib/postgresql
            du -sk /tmp
        fi
        du -sk "$path" "$PGDATA/pg_wal"
        df -Pk "$PGDATA"
        test "$(du -sk "$path" | cut -f1)" -lt 524288
        test "$(du -sk "$PGDATA/pg_wal" | cut -f1)" -lt 262144
        test "$(df -Pk "$PGDATA" | awk '"'"'NR==2 {print $4}'"'"')" -ge 1048576
    ' sh "$service"
}
sample() {
    resources "$source_id" source-db "${COMPOSE_PROJECT_NAME}_source-pg"
    resources "$consumer_id" probe-consumer "${COMPOSE_PROJECT_NAME}_probe-pg"
}
cleanup() {
    local status=$?
    trap - EXIT
    set +e
    if [[ -n ${consumer_id:-} ]] && owned "$consumer_id" probe-consumer; then
        consumer_state 2>&1 | redact > "$evidence/consumer-final.txt"
        catalog_state 2>&1 | redact > "$evidence/catalog-final.txt"
        resources "$consumer_id" probe-consumer "${COMPOSE_PROJECT_NAME}_probe-pg" 2>&1 | redact
        docker_local logs --tail=250 "$consumer_id" 2>&1 | redact > "$evidence/consumer.log"
        stack stop -t 12 probe-consumer || status=1
        docker_local inspect -f 'consumer_exit={{.State.ExitCode}} oom={{.State.OOMKilled}}' "$consumer_id"
    fi
    if [[ -n ${source_id:-} ]] && owned "$source_id" source-db; then
        publisher_state > "$evidence/source-final.txt"
        resources "$source_id" source-db "${COMPOSE_PROJECT_NAME}_source-pg" 2>&1 | redact
        docker_local logs --tail=350 "$source_id" 2>&1 | redact > "$evidence/source.log"
        if [[ -n ${publisher_identity:-} ]]; then
            source_sql -v cluster="$publisher_identity" -v publication="$publication" -v slot="$slot" <<'SQL' > "$evidence/cleanup.txt" 2>&1 || status=1
SELECT current_database() = 'source_lab'
   AND :'cluster' = (SELECT system_identifier::text FROM pg_control_system())
   AND NOT EXISTS (SELECT FROM pg_replication_slots WHERE active OR database <> 'source_lab'
                   OR plugin <> 'pgoutput' OR slot_name <> :'slot' OR temporary)
   AND NOT EXISTS (SELECT FROM pg_publication WHERE pubname <> :'publication'
                   OR pg_get_userbyid(pubowner) <> 'probe_replicator')
AS safe \gset
\if :safe
SELECT 'fallback-drop-slot', pg_drop_replication_slot(slot_name)
FROM pg_replication_slots WHERE slot_name = :'slot';
DROP PUBLICATION IF EXISTS :"publication";
DROP SCHEMA IF EXISTS probe CASCADE;
DROP OWNED BY probe_replicator;
DROP ROLE probe_replicator;
SELECT 'after', (SELECT count(*) FROM pg_replication_slots),
       (SELECT count(*) FROM pg_publication), to_regnamespace('probe') IS NULL,
       NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'probe_replicator');
\else
\echo Teardown identity, slot activity or inventory mismatch
\quit
\endif
SQL
            grep -Fxq 'after|0|0|t|t' "$evidence/cleanup.txt" || status=1
            fixture_acl > "$evidence/fixture-after.txt" || status=1
            diff -u "$evidence/fixture-before.txt" "$evidence/fixture-after.txt" || status=1
        fi
        stack stop -t 12 source-db || status=1
        docker_local inspect -f 'source_exit={{.State.ExitCode}} oom={{.State.OOMKilled}}' "$source_id"
    fi
    if [[ -n ${SOURCE_INPUT_ID:-} ]]; then
        # This project was checked empty before startup. Down is scoped to its exact name.
        stack down --volumes || status=1
        for fw in iptables ip6tables; do
            "$fw" -D DOCKER-USER -i "$bridge" ! -o "$bridge" -j DROP || status=1
            "$fw" -D INPUT -i "$bridge" -j DROP || status=1
        done
        docker_local network rm "$SOURCE_INPUT_ID" || status=1
        test -z "$(docker_local ps -aq --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME")" || status=1
        test -z "$(docker_local volume ls -q --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME")" || status=1
    fi
    echo "project_cleanup_exit=$status"
    exit "$status"
}

source_image=$(sed -n 's/^    image: //p' compose.source.yaml)
consumer_image=$(sed -n 's/^    image: //p' "$probe/compose.probe.yaml")
docker_local version --format 'engine={{.Server.Version}}'
docker_local compose version
docker_local info --format 'cgroup={{.CgroupVersion}} firewall={{json .FirewallBackend}}'
ip -br link
test -z "$(docker_local ps -q)"
test -z "$(docker_local ps -aq --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME")"
test -z "$(docker_local volume ls -q --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME")"
test -z "$(docker_local network ls -q --filter "name=^${COMPOSE_PROJECT_NAME}-input$")"
test "$(df -Pk "$(docker_local info -f '{{.DockerRootDir}}')" | awk 'NR==2 {print $4}')" -ge 1048576

(cd "$media" && sha256sum -c SHA256SUMS && sha256sum source.tar consumer.tar probe.tar)
for image_archive in source consumer probe; do
    timeout -k 2s 90s docker --host unix:///var/run/docker.sock load -i "$media/$image_archive.tar"
done
# Containerd inspect reports the index ID. Verify the selected member and
# config directly from the content-addressed OCI archive as well.
python3 - "$media" "${source_image##*@}" "${consumer_image##*@}" <<'PY_IMAGE'
import hashlib
import json
from pathlib import Path
import sys
import tarfile

directory, source_index, consumer_index = sys.argv[1:]
pins = [
    ("source", source_index, "d755a91aff87574a57060f86ecc0d55f83ccb51ceec6ec6f904c1210d018d998",
     "76500a7555b1f245546af93974bb208366013cf537fa3038f0bdd493efe0c612"),
    ("consumer", consumer_index, "de0a9036fd11a75eaff23508209c2cea675d081aecea51f60cdca78c0802a5a6",
     "a0452c3a54190ba6eeaf94dd3e434f97fd3862944c73b3f681f85eb8e3b2f56e"),
]
for role, index, manifest, config in pins:
    with tarfile.open(Path(directory) / f"{role}.tar") as archive:
        def blob(digest):
            digest = digest.removeprefix("sha256:")
            data = archive.extractfile(f"blobs/sha256/{digest}").read()
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError(f"{role}: digest mismatch for {digest}")
            return json.loads(data)

        refs = json.load(archive.extractfile("index.json"))["manifests"]
        members = blob(index)["manifests"]
        amd64 = [m["digest"] for m in members
                 if m.get("platform") == {"os": "linux", "architecture": "amd64"}]
        config_digest = blob(manifest)["config"]["digest"]
        image = blob(config)
        if ([ref["digest"] for ref in refs] != [index] or amd64 != [f"sha256:{manifest}"]
                or config_digest != f"sha256:{config}"
                or (image["os"], image["architecture"]) != ("linux", "amd64")):
            raise ValueError(f"{role}: archive identity mismatch")
        print(f"{role} index={index} amd64={amd64[0]} config={config_digest}")
PY_IMAGE
docker_local image ls --tree postgres
docker_local image ls --tree pgducklake/pipe-ci-builds
for ref in "$source_image" "$consumer_image"; do
    observed=$(docker_local image inspect "$ref" -f '{{.Os}}/{{.Architecture}} {{.Id}}')
    echo "$ref $observed"
    test "$observed" = "linux/amd64 ${ref##*@}"
done
for account in source-db probe-consumer probe-role; do
    openssl rand -hex 24 > "secrets/$account-password"
done
# Image starts as postgres. Restrict host access via the enclosing root-only directory.
chmod 0444 secrets/probe-consumer-password

trap cleanup EXIT
trap 'exit 124' TERM
for fw in iptables ip6tables; do
    test "$("$fw" -S FORWARD | awk '$1=="-A" {print; exit}')" = '-A FORWARD -j DOCKER-USER'
    "$fw" -S DOCKER-USER
done
test ! -e "/sys/class/net/$bridge"
SOURCE_INPUT_ID=$(docker_local network create --internal --ipv6 \
    --opt "com.docker.network.bridge.name=$bridge" "$COMPOSE_PROJECT_NAME-input")
export SOURCE_INPUT_ID
for fw in iptables ip6tables; do
    "$fw" -I INPUT 1 -i "$bridge" -j DROP
    "$fw" -I DOCKER-USER 1 -i "$bridge" ! -o "$bridge" -j DROP
done
docker_local network inspect "$SOURCE_INPUT_ID" -f '{{.Id}} {{.Name}} {{.Driver}} internal={{.Internal}} ipv6={{.EnableIPv6}} {{json .IPAM.Config}}'
stack config > "$evidence/compose.resolved.yaml"
python3 -u scripts/isolation/preflight.py --start-compose "$PWD/compose.source.yaml"
source_id=$(source_compose ps -q source-db)
owned "$source_id" source-db
healthy "$source_id"

echo "Source server, stock extensions, effective settings and identity"
source_sql <<'SQL'
SELECT version();
SHOW shared_preload_libraries;
SELECT extname, extversion FROM pg_extension ORDER BY extname;
SELECT name, default_version FROM pg_available_extensions WHERE name LIKE 'pg_duck%';
SELECT name, setting, unit FROM pg_settings WHERE name IN
    ('hba_file','password_encryption','wal_level','max_wal_senders','max_replication_slots','max_slot_wal_keep_size')
ORDER BY name;
SELECT current_database(), system_identifier FROM pg_control_system();
SQL
echo "Assert source version and empty replication inventory"
test "$(source_sql -c "SELECT current_setting('server_version_num') = '160016' AND current_setting('shared_preload_libraries') = '' AND NOT EXISTS (SELECT FROM pg_available_extensions WHERE name LIKE 'pg_duck%')")" = t
test "$(source_sql -c 'SELECT (SELECT count(*) FROM pg_publication), (SELECT count(*) FROM pg_replication_slots)')" = '0|0'
echo "Enroll Phase 1 fixture and provision probe-only scope"
disposable_id=$(cat /proc/sys/kernel/random/uuid)
source_sql -v disposable_id="$disposable_id" < sql/source/001_fixture_v1.sql
fixture_acl() {
    source_sql <<'SQL'
SELECT 'role', rolname, rolcanlogin, rolreplication
FROM pg_roles WHERE rolname LIKE 'source_fixture_%' ORDER BY rolname;
SELECT 'schema', nspname, pg_get_userbyid(nspowner), nspacl FROM pg_namespace WHERE nspname='fixture';
SELECT 'relation', relname, pg_get_userbyid(relowner), relacl, relreplident
FROM pg_class WHERE relnamespace=to_regnamespace('fixture') ORDER BY relname;
SELECT 'enrollment', schema_version, database_oid, system_identifier, disposable_id
FROM fixture.installation;
SQL
}
fixture_acl > "$evidence/fixture-before.txt"
{
    printf "\\set password '%s'\n" "$(cat secrets/probe-role-password)"
    cat <<'SQL'
BEGIN;
CREATE ROLE probe_replicator LOGIN REPLICATION NOSUPERUSER NOCREATEROLE NOCREATEDB NOBYPASSRLS PASSWORD :'password';
GRANT CONNECT, CREATE ON DATABASE source_lab TO probe_replicator;
CREATE SCHEMA probe AUTHORIZATION probe_replicator;
ALTER ROLE probe_replicator IN DATABASE source_lab SET log_statement = 'all';
SET LOCAL ROLE probe_replicator;
CREATE TABLE probe.items (id integer PRIMARY KEY, value text NOT NULL);
INSERT INTO probe.items VALUES (1, 'seed');
COMMIT;
SELECT 'scope', rolreplication, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls,
       rolpassword LIKE 'SCRAM-SHA-256$%',
       has_schema_privilege(rolname, 'fixture', 'USAGE'),
       has_table_privilege(rolname, 'fixture.customers', 'SELECT,INSERT,UPDATE,DELETE'),
       pg_has_role(rolname, 'source_fixture_owner', 'MEMBER')
FROM pg_authid WHERE rolname='probe_replicator';
SQL
} | source_sql 2>&1 | redact | tee "$evidence/source-scope.txt"
publisher_identity=$(source_sql -c 'SELECT system_identifier FROM pg_control_system()')
grep -Fxq 'scope|t|f|f|f|f|t|f|f|f' "$evidence/source-scope.txt"
subnet=$(docker_local network inspect "$SOURCE_INPUT_ID" -f '{{range .IPAM.Config}}{{println .Subnet}}{{end}}' | awk '/\./ {print}')
[[ $subnet =~ ^[0-9.]+/[0-9]+$ ]] || fail "unexpected IPv4 subnet"
docker_local exec -i "$source_id" sh -ec '
    { cat; cat "$PGDATA/pg_hba.conf"; } > "$PGDATA/pg_hba.conf.probe"
    mv "$PGDATA/pg_hba.conf.probe" "$PGDATA/pg_hba.conf"
' <<HBA
host source_lab probe_replicator $subnet scram-sha-256
host all probe_replicator all reject
host replication probe_replicator all reject
HBA
test "$(source_sql -c 'SELECT pg_reload_conf()')" = t

test "$(docker_local network inspect "$SOURCE_INPUT_ID" -f '{{len .Containers}}')" = 1
stack up -d --no-deps --pull never probe-consumer
consumer_id=$(stack ps -q probe-consumer)
owned "$consumer_id" probe-consumer
healthy "$consumer_id"
test "$(docker_local network inspect "$SOURCE_INPUT_ID" -f '{{len .Containers}}')" = 2
docker_local network inspect "$SOURCE_INPUT_ID" -f '{{range .Containers}}{{println .Name .IPv4Address .IPv6Address}}{{end}}'
for cid in "$source_id" "$consumer_id"; do
    docker_local exec --user postgres "$cid" sh -ec 'ls /sys/class/net; cat /proc/net/route; cat /proc/1/comm; readlink /proc/1/ns/net; readlink /proc/1/ns/pid'
done
sample

echo "Consumer versions, HBA and actual preload libraries"
consumer_sql <<'SQL'
SELECT version();
SHOW shared_preload_libraries;
SHOW hba_file;
SHOW password_encryption;
SHOW duckpipe.query_routing;
SELECT extname, extversion FROM pg_extension ORDER BY extname;
SELECT duckdb.raw_query('SELECT version()');
SELECT name, setting, unit, source FROM pg_settings
WHERE name IN ('max_connections','shared_buffers','duckdb.memory_limit','duckdb.threads',
               'duckdb.max_temp_directory_size','duckdb.unsafe_allow_mixed_transactions')
ORDER BY name;
SQL
docker_local exec "$consumer_id" sh -ec '
    sha256sum /docker-entrypoint-initdb.d/*;
    lib=$(pg_config --pkglibdir);
    sha256sum "$lib"/pg_duck*.so "$lib"/libduckdb.so "$lib"/ducklake.duckdb_extension
'
test "$(consumer_sql -c "SELECT current_setting('server_version_num') = '180004' AND current_setting('duckpipe.query_routing') = 'off'")" = t
hba='SELECT line_number,type,database,user_name,address,auth_method,error FROM pg_hba_file_rules ORDER BY rule_number;'
# The PG16 probe file has no includes. Line order is sufficient there.
source_sql -c "${hba/rule_number/line_number}"
consumer_sql -c "$hba"
test "$(source_sql -c 'SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL')" = 0
test "$(consumer_sql -c 'SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL')" = 0

tcp_client='IFS= read -r PGPASSWORD; export PGPASSWORD PGREQUIREAUTH=scram-sha-256 PGCONNECT_TIMEOUT=3; exec psql -XwqAt -v ON_ERROR_STOP=1 "$@"'
source_from_consumer() {
    timeout -k 2s 8s docker --host unix:///var/run/docker.sock exec -i --user postgres "$consumer_id" sh -ec "$tcp_client" sh \
        -h source-db -U probe_replicator "$@"
}
consumer_from_peer() {
    timeout -k 2s 8s docker --host unix:///var/run/docker.sock run --rm -i --pull never --network "$SOURCE_INPUT_ID" \
        --memory 96m --memory-swap 96m --cpus .5 --pids-limit 32 --read-only --cap-drop ALL \
        --env LC_ALL=C --entrypoint sh "$source_image" -ec "$tcp_client" sh -h probe-consumer -U postgres -d postgres "$@"
}
assert_rejected() {
    local match=$1
    shift
    if "$@" > "$evidence/rejected.txt" 2>&1; then fail "unexpected login or access"; fi
    grep -F "$match" "$evidence/rejected.txt"
}
source_from_consumer -d source_lab -c 'SELECT current_user,current_database(),inet_client_addr(),inet_server_addr();' < secrets/probe-role-password
printf 'incorrect\n' | assert_rejected 'password authentication failed' source_from_consumer -d source_lab -c 'SELECT 1'
assert_rejected 'pg_hba.conf rejects connection' source_from_consumer -d postgres -c 'SELECT 1' < secrets/probe-role-password
assert_rejected 'permission denied for schema fixture' source_from_consumer -d source_lab -c 'TABLE fixture.customers' < secrets/probe-role-password
consumer_from_peer -c 'SELECT current_user,current_database(),inet_client_addr(),inet_server_addr();' < secrets/probe-consumer-password
printf 'incorrect\n' | assert_rejected 'password authentication failed' consumer_from_peer -c 'SELECT 1'
docker_local exec --user postgres "$consumer_id" psql -h 127.0.0.1 -U postgres -d postgres -XwAtqc \
    'SELECT current_user,current_database(),inet_client_addr(),inet_server_addr();'

test "$(docker_local network inspect "$SOURCE_INPUT_ID" -f '{{len .Containers}}')" = 2
publisher_state > "$evidence/before-registration.source"
catalog_state > "$evidence/before-registration.catalog"
consumer_sql <<'SQL'
CREATE SCHEMA bronze;
SELECT duckpipe.set_config('duckdb_threads', '1');
SELECT duckpipe.set_config('duckdb_buffer_memory_mb', '16');
SELECT duckpipe.set_config('duckdb_flush_memory_mb', '96');
SELECT duckpipe.set_config('max_concurrent_flushes', '1');
SELECT duckpipe.set_config('max_queued_bytes', '1048576');
SELECT 'config', duckpipe.get_config();
SQL
{
    printf "\\set password '%s'\n" "$(cat secrets/probe-role-password)"
    cat <<'SQL'
SELECT duckpipe.create_group(:'group', publication => :'publication', slot_name => :'slot',
    conninfo => 'host=source-db port=5432 dbname=source_lab user=probe_replicator sslmode=disable password=' || :'password',
    mode => 'bgworker');
SQL
} | consumer_sql -v group="$group" -v publication="$publication" -v slot="$slot" 2>&1 | redact
publisher_state > "$evidence/after-create-group.source"

source_rows='SELECT id,value FROM probe.items ORDER BY id,value LIMIT 3'
target_rows='SELECT id,value FROM bronze.items ORDER BY id,value LIMIT 3'
checkpoint() {
    local label=$1 expected=$2 start=$SECONDS last='none' result attempt=0
    local file="$evidence/$label"
    source_sql -c "$source_rows" | tee "$file.source.rows"
    test "$(cat "$file.source.rows")" = "$expected" || fail "$label source row mismatch"
    printf 'expected\n%s\n' "$expected" > "$file.poll"
    while (( SECONDS - start < 60 )); do
        attempt=$((attempt + 1))
        if result=$(consumer_sql -c "$target_rows" 2>&1 | redact) && [[ $result == "$expected" ]]; then
            printf 'last failing observation\n%s\nfirst passing observation attempt=%s elapsed_seconds=%s UTC=%s\n%s\n' \
                "$last" "$attempt" "$((SECONDS - start))" "$(date -u +%FT%T.%3NZ)" "$result" | tee -a "$file.poll"
            printf '%s\n' "$result" > "$file.target.rows"
            publisher_state > "$file.source.state"
            consumer_state > "$file.consumer.state"
            catalog_state > "$file.catalog"
            sample >> "$evidence/resources.txt"
            return 0
        fi
        last=$(printf 'attempt=%s UTC=%s\n%s' "$attempt" "$(date -u +%FT%T.%3NZ)" "$result")
        # Check kernel OOM counters and disk limits during long or failed checkpoints.
        if (( attempt % 10 == 0 )); then sample >> "$evidence/resources.txt"; fi
        sleep .5
    done
    printf 'last failing observation\n%s\n' "$last" | tee -a "$file.poll"
    fail "$label exact row parity deadline expired"
}
test "$(source_sql -c "$source_rows")" = '1|seed'
echo "Register snapshot mapping"
consumer_sql -v group="$group" <<'SQL'
SELECT duckpipe.add_table('probe.items', target_table => 'bronze.items', sync_group => :'group',
                          copy_data => true, sync_mode => 'upsert');
SQL
checkpoint initial '1|seed'
test "$(source_sql -c "SELECT count(*) FROM pg_replication_slots WHERE slot_name='$slot' AND active AND NOT temporary AND plugin='pgoutput'")" = 1
test "$(source_sql -c 'SELECT count(*) FROM pg_replication_slots')" = 1
test "$(source_sql -c "SELECT pubname,schemaname,tablename FROM pg_publication_tables")" = "$publication|probe|items"

echo "Commit insert"
source_sql -c "BEGIN; INSERT INTO probe.items VALUES (2, 'inserted'); COMMIT;"
checkpoint insert $'1|seed\n2|inserted'
echo "Commit update"
source_sql -c "BEGIN; UPDATE probe.items SET value = 'updated' WHERE id = 1; COMMIT;"
checkpoint update $'1|updated\n2|inserted'
echo "Commit delete"
source_sql -c 'BEGIN; DELETE FROM probe.items WHERE id = 2; COMMIT;'
checkpoint delete '1|updated'

consumer_sql -c "SELECT 'deleted_absent', NOT EXISTS (SELECT FROM bronze.items WHERE id=2);
SELECT 'duplicate_keys', count(*) FROM (SELECT id FROM bronze.items GROUP BY id HAVING count(*) > 1) AS duplicates;" |
    tee "$evidence/final-keys.txt"
grep -Fxq 'deleted_absent|t' "$evidence/final-keys.txt"
grep -Fxq 'duplicate_keys|0' "$evidence/final-keys.txt"
docker_local exec "$consumer_id" sh -ec 'find "$PGDATA/pg_ducklake" -maxdepth 5 -type f -printf "%P %s bytes\n" | sort' |
    tee "$evidence/files.txt"

echo "Remove mapping and drop group with the pinned API"
consumer_sql -v group="$group" <<'SQL'
SELECT duckpipe.remove_table('probe.items', drop_target => false, sync_group => :'group');
SELECT duckpipe.drop_group(:'group');
SQL
publisher_state > "$evidence/after-drop-group.source"
test "$(source_sql -c 'SELECT (SELECT count(*) FROM pg_publication), (SELECT count(*) FROM pg_replication_slots)')" = '0|0'
echo "EXP-011 ROW AND LIFECYCLE CHECKS PASSED"
