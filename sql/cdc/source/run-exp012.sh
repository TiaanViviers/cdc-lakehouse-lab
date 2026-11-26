#!/usr/bin/env bash
# EXP-012 on the disconnected VM, with the reviewed EXP-011 media.
set -Eeuo pipefail
umask 077
export LC_ALL=C TZ=UTC COMPOSE_DISABLE_ENV_FILE=1
unset DOCKER_CONTEXT COMPOSE_ENV_FILES SOURCE_INPUT_ID
exec </dev/null

media=${1:?provide staged image media}
: "${PROBE_SHA:?set the staged revision}" "${PROBE_OVERLAY:?set the fresh overlay identity}"
[[ $(id -u) == 0 ]]
[[ -z $(ip -4 route show default; ip -6 route show default) ]]
[[ $(ip -o link show | awk -F ': ' '{print $2}' | sort | paste -sd ,) == docker0,lo ]]
export CDC_RUN_KEY="r$(date -u +%Y%m%dt%H%M%Sz)"
export COMPOSE_PROJECT_NAME="cdc22-$CDC_RUN_KEY"
evidence="$PWD/artifacts/EXP-012/${CDC_RUN_KEY:1}"
mkdir -p "${evidence%/*}"
mkdir "$evidence" secrets
exec > >(tee "$evidence/observations.log") 2>&1
trap 'printf "FAIL line=%s status=%s\n" "$LINENO" "$?" >&2' ERR
trap 'exit 124' TERM

publisher="publisher_$CDC_RUN_KEY"
publication="pub_$CDC_RUN_KEY"
slot="slot_$CDC_RUN_KEY"
group="g_$CDC_RUN_KEY"
bridge="p22${CDC_RUN_KEY:10:6}"
enrollment="secrets/$COMPOSE_PROJECT_NAME-fixture-id"
echo "owner=2.2/Codex ticket=39 run=$CDC_RUN_KEY sha=$PROBE_SHA overlay=$PROBE_OVERLAY project=$COMPOSE_PROJECT_NAME db=source_lab group=$group publication=$publication slot=$slot"
echo "Limits: run 600s, polling 45s per checkpoint, source WAL <256MiB, volumes <512MiB each, free >=1GiB."
docker=(docker --host unix:///var/run/docker.sock)
source_compose=("${docker[@]}" compose -f compose.source.yaml --profile source)
stack=("${docker[@]}" compose -f compose.source.yaml -f tests/integration/remote-probe/compose.probe.yaml --profile source)
source_image=$(sed -n 's/^    image: //p' compose.source.yaml)
consumer_image=$(sed -n 's/^    image: //p' tests/integration/remote-probe/compose.probe.yaml)

source_sql() {
    timeout -k 2s 12s "${docker[@]}" exec -i "$source_id" sh -ec '
        export PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")" PGREQUIREAUTH=scram-sha-256
        export PGCONNECT_TIMEOUT=3 PGOPTIONS="-c statement_timeout=5000 -c lock_timeout=2000"
        exec psql -XwqAt -v ON_ERROR_STOP=1 -v VERBOSITY=verbose -h 127.0.0.1 -U source_admin -d source_lab "$@"
    ' sh "$@"
}
consumer_sql() {
    timeout -k 2s 15s "${docker[@]}" exec -i --user postgres         -e PGOPTIONS='-c statement_timeout=10000 -c duckdb.force_execution=off' "$consumer_id"         psql -XwqAt -v ON_ERROR_STOP=1 -h 127.0.0.1 -U postgres -d postgres "$@"
}
peer_sql() {
    local role=$1
    shift
    timeout -k 2s 8s "${docker[@]}" run --rm -i --pull never --network "$SOURCE_INPUT_ID"         --memory 96m --memory-swap 96m --cpus .5 --pids-limit 32 --read-only --cap-drop ALL         --env PGREQUIREAUTH=scram-sha-256 --env PGCONNECT_TIMEOUT=3 --env LC_ALL=C         --entrypoint sh "$source_image" -ec '
        IFS= read -r PGPASSWORD; export PGPASSWORD
        exec psql -XwqAt -v ON_ERROR_STOP=1 -v VERBOSITY=verbose -h source-db "$@"
    ' sh -U "$role" -d source_lab "$@"
}
redact() {
    python3 -c '
import re, sys
from pathlib import Path
secrets = [f.read_text().strip() for f in Path("secrets").glob("*-password")]
for line in sys.stdin:
    for secret in secrets:
        line = line.replace(secret, "[redacted]")
    print(re.sub(r"(?i)\b(?:host|hostaddr|port|dbname|user|sslmode|password)=\S+", "[conninfo field]", line), end="")
'
}
admin() { bash sql/cdc/source/admin.sh "$@"; }
reject() {
    local label=$1 diagnostic=$2 status=0
    shift 2
    "$@" > "$evidence/$label.txt" 2>&1 || status=$?
    test "$status" -ne 0
    grep -F -- "$diagnostic" "$evidence/$label.txt"
}
healthy() {
    local id=$1
    for _ in $(seq 40); do
        if [[ $("${docker[@]}" inspect -f '{{.State.Health.Status}}' "$id") == healthy ]]; then return; fi
        sleep 1
    done
    return 1
}
identity() {
    local id=$1 service=$2 image=$3 volume=$4
    test "$("${docker[@]}" inspect -f '{{index .Config.Labels "com.docker.compose.project"}}/{{index .Config.Labels "com.docker.compose.service"}} {{len .NetworkSettings.Networks}} {{range .NetworkSettings.Networks}}{{.NetworkID}}{{end}} {{.Image}} {{.HostConfig.Privileged}}' "$id")"         = "$COMPOSE_PROJECT_NAME/$service 1 $SOURCE_INPUT_ID ${image##*@} false"
    test -z "$("${docker[@]}" port "$id")"
    test "$("${docker[@]}" inspect -f '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}}{{end}}{{end}}' "$id")" = "$volume"
    test "$("${docker[@]}" volume inspect -f '{{index .Labels "com.docker.compose.project"}}' "$volume")" = "$COMPOSE_PROJECT_NAME"
    "${docker[@]}" volume inspect -f '{{.Name}} {{json .Labels}}' "$volume"
}
sample() {
    local id
    for id in "$source_id" ${consumer_id:+"$consumer_id"}; do
        "${docker[@]}" inspect -f 'id={{.Id}} image={{.Image}} pid={{.State.Pid}} oom={{.State.OOMKilled}} memory={{.HostConfig.Memory}} swap={{.HostConfig.MemorySwap}} cpu={{.HostConfig.NanoCpus}} pids={{.HostConfig.PidsLimit}}' "$id"
        "${docker[@]}" exec "$id" sh -ec '
            path=$(dirname "$PGDATA")
            if [ -d "$PGDATA/pg_wal" ] && [ -f "$PGDATA/PG_VERSION" ]; then path=$PGDATA; fi
            if [ "$1" = consumer ]; then path=/var/lib/postgresql; fi
            du -sk "$path" "$PGDATA/pg_wal"
            df -Pk "$PGDATA"
            cat /sys/fs/cgroup/memory.peak /sys/fs/cgroup/memory.events /sys/fs/cgroup/cpu.stat
            test "$(du -sk "$path" | cut -f1)" -lt 524288
            test "$(du -sk "$PGDATA/pg_wal" | cut -f1)" -lt 262144
            test "$(df -Pk "$PGDATA" | awk '\''NR==2 {print $4}'\'')" -ge 1048576
            test "$(awk '\''$1=="oom" || $1=="oom_kill" {sum+=$2} END {print sum+0}'\'' /sys/fs/cgroup/memory.events)" = 0
        ' sh "$( [[ "$id" == "$source_id" ]] && echo source || echo consumer )"
    done >> "$evidence/resources.txt"
}
finish() {
    local status=$?
    trap - EXIT
    set +e
    if [[ -n ${source_id:-} ]]; then
        admin inventory > "$evidence/at-exit.txt" 2>&1
        "${docker[@]}" logs --tail=700 "$source_id" 2>&1 | redact |
            awk '/connection authenticated:|password authentication failed|pg_hba.conf rejects|permission denied|CREATE PUBLICATION|START_REPLICATION|pg_create_logical_replication_slot|consistent point|COPY "fixture"|REPLICA IDENTITY/'             > "$evidence/source-audit.txt"
    fi
    if [[ -n ${consumer_id:-} ]]; then
        "${docker[@]}" logs --tail=200 "$consumer_id" 2>&1 | redact |
            awk '/snapshot|STREAMING|CATCHUP|worker|ERROR|flush/' > "$evidence/consumer-audit.txt"
    fi
    if [[ -n ${SOURCE_INPUT_ID:-} ]]; then
        "${stack[@]}" down -t 12 --volumes || status=1
        for fw in iptables ip6tables; do
            "$fw" -D DOCKER-USER -i "$bridge" ! -o "$bridge" -j DROP || status=1
            "$fw" -D INPUT -i "$bridge" -j DROP || status=1
        done
        "${docker[@]}" network rm "$SOURCE_INPUT_ID" || status=1
        [[ -z $("${docker[@]}" ps -aq --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME") ]] || status=1
        [[ -z $("${docker[@]}" volume ls -q --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME") ]] || status=1
    fi
    echo "EXP-012 project teardown status=$status"
    exit "$status"
}

test -z "$("${docker[@]}" ps -q)"
test -z "$("${docker[@]}" ps -aq --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME")"
test -z "$("${docker[@]}" volume ls -q --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME")"
test -z "$("${docker[@]}" network ls -q --filter "name=^$COMPOSE_PROJECT_NAME-input$")"
test ! -e "/sys/class/net/$bridge"
(cd "$media" && sha256sum -c SHA256SUMS)
for archive in source consumer probe; do
    timeout -k 2s 90s "${docker[@]}" load -i "$media/$archive.tar"
done
for image in "$source_image" "$consumer_image"; do
    test "$("${docker[@]}" image inspect "$image" -f '{{.Os}}/{{.Architecture}} {{.Id}}')" = "linux/amd64 ${image##*@}"
done
for account in source-db probe-consumer publisher reader; do
    openssl rand -hex 24 > "secrets/$account-password"
done
chmod 0444 secrets/probe-consumer-password
cat /proc/sys/kernel/random/uuid > "$enrollment"

for fw in iptables ip6tables; do
    test "$("$fw" -S FORWARD | awk '$1=="-A" {print; exit}')" = '-A FORWARD -j DOCKER-USER'
done
trap finish EXIT
SOURCE_INPUT_ID=$("${docker[@]}" network create --internal --ipv6     --opt "com.docker.network.bridge.name=$bridge" "$COMPOSE_PROJECT_NAME-input")
export SOURCE_INPUT_ID
for fw in iptables ip6tables; do
    "$fw" -I INPUT 1 -i "$bridge" -j DROP
    "$fw" -I DOCKER-USER 1 -i "$bridge" ! -o "$bridge" -j DROP
done
"${docker[@]}" network inspect "$SOURCE_INPUT_ID" -f '{{.Id}} {{.Name}} {{.Internal}} {{json .IPAM.Config}}'
"${stack[@]}" config > "$evidence/compose.resolved.yaml"
python3 -u scripts/isolation/preflight.py --start-compose "$PWD/compose.source.yaml"
source_id=$("${source_compose[@]}" ps -q source-db)
healthy "$source_id"
identity "$source_id" source-db "$source_image" "${COMPOSE_PROJECT_NAME}_source-pg"
sample

# Use the existing full source schema acceptance suite as the pre-CDC regression.
source_cmd=(timeout -k 2s 12s "${docker[@]}" exec -i "$source_id" sh -ec '
    export PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")" PGREQUIREAUTH=scram-sha-256 PGCONNECT_TIMEOUT=3
    exec psql -w -h 127.0.0.1 -U source_admin -d source_lab "$@"
' sh)
disposable_id=$(<"$enrollment")
bash tests/integration/source-schema/run.sh "$evidence/fixture-regression" "$disposable_id" "${source_cmd[@]}"
admin inventory > "$evidence/before.txt"
IFS='|' read -r role_oid observed_role < <(admin prepare)
test "$observed_role" = "$publisher"
reject repeated-role 42710 admin prepare
admin permission-probe
admin ownership-probe | tee "$evidence/ownership.txt"
grep -Fx '911|2' "$evidence/ownership.txt"
grep -Fx '901|910|912|S04|t' "$evidence/ownership.txt"

{
    printf "ALTER ROLE %s PASSWORD '%s';\n" "$publisher" "$(<secrets/publisher-password)"
    printf "ALTER ROLE source_fixture_reader PASSWORD '%s';\n" "$(<secrets/reader-password)"
    printf "ALTER ROLE %s IN DATABASE source_lab SET log_statement = 'all';\n" "$publisher"
} | source_sql 2>&1 | redact
subnets=$("${docker[@]}" network inspect "$SOURCE_INPUT_ID" -f '{{range .IPAM.Config}}{{println .Subnet}}{{end}}')
ipv4=$(awk '/[.]/ {print}' <<< "$subnets")
ipv6=$(awk '/:/ {print}' <<< "$subnets")
[[ $ipv4 =~ ^[0-9.]+/[0-9]+$ && $ipv6 =~ ^[0-9a-f:]+/[0-9]+$ ]]
"${docker[@]}" exec -i --user postgres "$source_id" sh -ec '
    umask 077
    cp -p "$PGDATA/pg_hba.conf" "$PGDATA/pg_hba.exp012"
    { cat; cat "$PGDATA/pg_hba.exp012"; } > "$PGDATA/pg_hba.new"
    mv "$PGDATA/pg_hba.new" "$PGDATA/pg_hba.conf"
' <<HBA
host source_lab $publisher $ipv4 scram-sha-256
host source_lab $publisher $ipv6 scram-sha-256
host replication $publisher all reject
host all $publisher all reject
local replication $publisher reject
local all $publisher reject
HBA
test "$(source_sql -c 'SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL')" = 0
test "$(source_sql -c 'SELECT pg_reload_conf()')" = t
admin enable-login "$role_oid"
peer_sql "$publisher" -c 'SELECT current_user,current_database(),inet_client_addr() IS NOT NULL' <secrets/publisher-password |
    tee "$evidence/peer-auth.txt" | grep -Fx "$publisher|source_lab|t"
reject wrong-password 'password authentication failed' peer_sql "$publisher" -c 'SELECT 1' <<<'intentionally-incorrect'
reject wrong-database 'pg_hba.conf rejects connection' peer_sql "$publisher" -d postgres -c 'SELECT 1' <secrets/publisher-password
reject physical 'pg_hba.conf rejects replication connection' peer_sql "$publisher" -d 'dbname=source_lab replication=true' -c IDENTIFY_SYSTEM <secrets/publisher-password
peer_sql source_fixture_reader -c 'SELECT current_user,current_database()' <secrets/reader-password
reject reader-repl 'permission denied to start WAL sender' peer_sql source_fixture_reader -d 'dbname=source_lab replication=database' -c IDENTIFY_SYSTEM <secrets/reader-password
reject reader-impersonation 42501 peer_sql source_fixture_reader -c "SET ROLE $publisher" <secrets/reader-password
peer_sql "$publisher" -c 'SELECT current_user' <secrets/publisher-password
admin inventory > "$evidence/prepared.txt"

slot_row() {
    source_sql -c "SELECT slot_name,datoid,slot_type,plugin,temporary,active,restart_lsn,confirmed_flush_lsn
        FROM pg_replication_slots ORDER BY slot_name"
}
fingerprint() {
    local active_expected=$1
    local db_oid
    db_oid=$(source_sql -c 'SELECT oid FROM pg_database WHERE datname=current_database()')
    local row
    row=$(slot_row)
    printf '%s\n' "$row" | tee -a "$evidence/slot-inventory.txt"
    [[ $row =~ ^$slot\|$db_oid\|logical\|pgoutput\|f\|$active_expected\|([0-9A-F]+/[0-9A-F]+)\|([0-9A-F]+/[0-9A-F]+)$ ]]
    fingerprint=("${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}")
}
admin create-slot
fingerprint f
admin snapshot-slot-probe "${fingerprint[@]}" | tee "$evidence/native-snapshot.txt"
grep -Fx 'Slot cap rejected third allocation (53400)' "$evidence/native-snapshot.txt"
fingerprint f
reject wrong-project 'Refusing publisher probe' env COMPOSE_PROJECT_NAME=cdc22-other bash sql/cdc/source/admin.sh drop-slot "${fingerprint[@]}"
reject wrong-fingerprint 'refusing slot drop' admin drop-slot 0/1 0/1
cat sql/cdc/source/{guard,drop-slot}.sql |
    reject wrong-database-guard 'refusing CDC operation on unexpected source' source_sql -d postgres -v "run_key=$CDC_RUN_KEY"         -v "disposable_id=$disposable_id" -v "created_restart_lsn=${fingerprint[0]}" -v "created_flush_lsn=${fingerprint[1]}" -f -
admin drop-slot "${fingerprint[@]}"
test -z "$(slot_row)"
# Occupy the exact reserved name with a deliberately unrelated physical slot.
source_sql -c "SELECT * FROM pg_create_physical_replication_slot('$slot',true)"
collision_slot=$(slot_row)
reject unrelated-slot 'refusing slot drop' admin drop-slot "${fingerprint[@]}"
test "$(slot_row)" = "$collision_slot"
source_sql -c "SELECT pg_drop_replication_slot('$slot')" # The test owns this collision sentinel.
test -z "$(slot_row)"
sample

# Reuse the already reviewed isolated 2.1 service for this experiment.
test "$("${docker[@]}" network inspect "$SOURCE_INPUT_ID" -f '{{len .Containers}}')" = 1
"${stack[@]}" up -d --no-deps --pull never probe-consumer
consumer_id=$("${stack[@]}" ps -q probe-consumer)
healthy "$consumer_id"
identity "$consumer_id" probe-consumer "$consumer_image" "${COMPOSE_PROJECT_NAME}_probe-pg"
test "$("${docker[@]}" network inspect "$SOURCE_INPUT_ID" -f '{{len .Containers}}')" = 2
consumer_sql -c "SELECT version(); SHOW shared_preload_libraries; SELECT extname,extversion FROM pg_extension ORDER BY 1;"
sample

create_group() {
    {
        printf "\\set password '%s'\n" "$(<secrets/publisher-password)"
        cat <<'SQL'
SELECT duckpipe.create_group(:'group', publication => :'publication', slot_name => :'slot',
    conninfo => 'host=source-db port=5432 dbname=source_lab sslmode=disable user=' || :'publisher'
        || ' password=' || :'password', mode => 'bgworker');
SQL
    } | consumer_sql -v "group=$group" -v "slot=$slot" -v "publication=$publication" -v "publisher=$publisher" 2>&1 | redact
}
no_objects() {
    test "$(source_sql -c 'SELECT (SELECT count(*) FROM pg_replication_slots),(SELECT count(*) FROM pg_publication)')" = '0|0'
}
reject group-without-create 'remote create publication' create_group
fingerprint f
test -z "$(source_sql -c 'SELECT pubname FROM pg_publication')"
consumer_sql -c 'SELECT name, mode, enabled FROM duckpipe.sync_groups ORDER BY name' > "$evidence/groups-after-denial.txt"
test "$(consumer_sql -c "SELECT count(*) FROM duckpipe.sync_groups WHERE name='$group'")" = 0
admin drop-slot "${fingerprint[@]}"
no_objects

admin elevate "$role_oid"
source_sql -c "CREATE PUBLICATION $publication FOR TABLE fixture.customers"
collision_oid=$(source_sql -c "SELECT oid FROM pg_publication WHERE pubname='$publication'")
reject publication-collision 'remote create publication' create_group
fingerprint f
admin drop-slot "${fingerprint[@]}"
reject unrelated-publication 'refusing publication drop' admin drop-publication "$collision_oid"
test "$(source_sql -c "SELECT oid,pg_get_userbyid(pubowner) FROM pg_publication WHERE pubname='$publication'")" = "$collision_oid|source_admin"
test "$(source_sql -c 'SELECT schemaname,tablename FROM pg_publication_tables')" = 'fixture|customers'
source_sql -c "DROP PUBLICATION $publication" # The test itself created this verified collision sentinel.
no_objects
admin inventory > "$evidence/elevated.txt"

# Exercise the real Phase 1 fixture roles while the publisher owns the tables.
source_sql < tests/integration/source-schema/probe-rows.sql
source_sql < tests/integration/source-schema/rows.sql > "$evidence/source-seeded.txt"
diff -u tests/integration/source-schema/expected-probe-rows.txt "$evidence/source-seeded.txt"

consumer_sql <<'SQL'
CREATE SCHEMA bronze;
SELECT duckpipe.set_config('duckdb_threads', '1');
SELECT duckpipe.set_config('duckdb_buffer_memory_mb', '16');
SELECT duckpipe.set_config('duckdb_flush_memory_mb', '96');
SELECT duckpipe.set_config('max_concurrent_flushes', '1');
SELECT duckpipe.set_config('max_queued_bytes', '1048576');
SQL
create_group
fingerprint f
reject repeated-group 'remote create slot' create_group
test "$(source_sql -c "SELECT pg_get_userbyid(pubowner) FROM pg_publication WHERE pubname='$publication'")" = "$publisher"
publication_oid=$(source_sql -c "SELECT oid FROM pg_publication WHERE pubname='$publication'")

declare -A columns=(
    [customers]='customer_id,code,name,created_at,updated_at'
    [orders]='order_id,customer_id,order_ref,status,created_at,updated_at'
    [order_items]='item_id,order_id,line_no,sku,quantity,unit_cents,created_at,updated_at'
    [payments]='payment_id,order_id,payment_ref,amount_cents,created_at,updated_at'
)
tables=(customers orders order_items payments)
compare() {
    local table=$1 stage=$2 projection=${columns[$1]} since=$SECONDS
    local query="SELECT $projection FROM"
    source_sql -c "$query fixture.$table ORDER BY 1 LIMIT 3" > "$evidence/$stage-$table.source"
    while (( SECONDS - since < 45 )); do
        if consumer_sql -c "$query bronze.$table ORDER BY 1 LIMIT 3" > "$evidence/$stage-$table.target" 2>&1 &&
            cmp -s "$evidence/$stage-$table.source" "$evidence/$stage-$table.target"; then
            printf '%s %s parity after %ss\n' "$stage" "$table" "$((SECONDS-since))"
            return 0
        fi
        sleep .5
    done
    diff -u "$evidence/$stage-$table.source" "$evidence/$stage-$table.target" || true
    return 1
}
for table in "${tables[@]}"; do
    consumer_sql -c "SELECT duckpipe.add_table('fixture.$table',target_table=>'bronze.$table',
        sync_group=>'$group',copy_data=>true,sync_mode=>'upsert')"
    compare "$table" initial
    test "$(source_sql -c 'SELECT count(*) FROM pg_replication_slots WHERE NOT temporary')" = 1
    sample
done
test "$(source_sql -c 'SELECT schemaname,tablename FROM pg_publication_tables ORDER BY 2')" = \
    $'fixture|customers\nfixture|order_items\nfixture|orders\nfixture|payments'
test "$(source_sql -c "SELECT count(*) FROM pg_class WHERE relnamespace='fixture'::regnamespace AND relreplident='f'")" = 4
test "$(consumer_sql -c "SELECT to_regclass('bronze.scenario_receipts') IS NULL AND to_regclass('bronze.installation') IS NULL")" = t
admin inventory > "$evidence/registered.txt"
fingerprint t
reject active-slot 'refusing slot drop' admin drop-slot "${fingerprint[@]}"
test "$(source_sql -c "SELECT active FROM pg_replication_slots WHERE slot_name='$slot'")" = t

admin reduce "$role_oid"
admin permission-probe
admin inventory > "$evidence/reduced.txt"
source_sql -c 'SET SESSION AUTHORIZATION source_fixture_writer; UPDATE fixture.order_items SET quantity=3 WHERE item_id=911'
compare order_items reduced-apply

"${stack[@]}" stop -t 15 probe-consumer
fingerprint f
"${stack[@]}" start probe-consumer
healthy "$consumer_id"
consumer_sql -c "SELECT duckpipe.start_worker('$group')"
source_sql -c 'SET SESSION AUTHORIZATION source_fixture_writer; UPDATE fixture.order_items SET quantity=4 WHERE item_id=911'
compare order_items reduced-reconnect
fingerprint t
sample
"${stack[@]}" stop -t 15 probe-consumer
test "$("${docker[@]}" inspect -f '{{.State.ExitCode}} {{.State.OOMKilled}}' "$consumer_id")" = '0 false'
admin disable-login "$role_oid"
fingerprint f
reject publication-with-slot 'refusing publication drop' admin drop-publication "$publication_oid"
admin drop-slot "${fingerprint[@]}"
admin drop-publication "$publication_oid"
no_objects
admin restore-identity "$role_oid"
admin drop-role "$role_oid"
"${docker[@]}" exec --user postgres "$source_id" sh -ec 'mv "$PGDATA/pg_hba.exp012" "$PGDATA/pg_hba.conf"'
source_sql -c 'SELECT pg_reload_conf(); ALTER ROLE source_fixture_reader PASSWORD NULL;'
admin inventory > "$evidence/after.txt"
diff -u "$evidence/before.txt" "$evidence/after.txt"
source_sql -v "id=$disposable_id" -f - <<'SQL'
SET SESSION AUTHORIZATION source_fixture_writer;
SELECT fixture.cleanup(true, :'id'::uuid);
SQL
source_sql < tests/integration/source-schema/rows.sql > "$evidence/restored-empty.txt"
diff -u "$evidence/fixture-regression/expected-empty.rows" "$evidence/restored-empty.txt"
echo 'EXP-012 SOURCE AND CONNECTOR CHECKS PASSED'
