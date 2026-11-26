#!/usr/bin/env bash
# Execute only the independent source probes on the enrolled VM project.
set -euo pipefail
here=$(cd -- "$(dirname -- "$0")" && pwd)
cd -- "$here/../../.."

: "${COMPOSE_PROJECT_NAME:?set the enrolled project}"
: "${SOURCE_INPUT_ID:?set its verified full bridge ID}"
: "${CDC_RUN_KEY:?set the independent probe run key}"
[[ $CDC_RUN_KEY =~ ^[a-z][a-z0-9]{7,23}$ ]]
if [[ $COMPOSE_PROJECT_NAME != "cdc22-$CDC_RUN_KEY" ]]; then
    printf 'Refusing publisher probe on project %s for run %s\n' "$COMPOSE_PROJECT_NAME" "$CDC_RUN_KEY" >&2
    exit 1
fi
[[ $SOURCE_INPUT_ID =~ ^[0-9a-f]{64}$ ]]

operation=${1:?specify the independent probe operation}
shift
case "$operation" in
    inventory|prepare|permission-probe|ownership-probe|publish|drop-publication|create-slot|reject-publication|snapshot-slot-probe|drop-slot|drop-role|enable-login|disable-login) ;;
    *) printf 'Unknown publisher probe operation %s\n' "$operation" >&2; exit 2 ;;
esac
variables=()
sql_file=$operation
case "$operation" in
    ownership-probe|publish)
        [[ $# == 0 ]]
        sql_file=ownership-probe
        if [[ $operation == publish ]]; then
            variables=(-v keep_publication=true)
        else
            variables=(-v keep_publication=false)
        fi
        ;;
    drop-publication)
        [[ $# == 1 && $1 =~ ^[0-9]+$ ]]
        variables=(-v "created_publication_oid=$1")
        ;;
    snapshot-slot-probe|drop-slot)
        [[ $# == 2 && $1 =~ ^[0-9A-F]+/[0-9A-F]+$ && $2 =~ ^[0-9A-F]+/[0-9A-F]+$ ]]
        variables=(-v "created_restart_lsn=$1" -v "created_flush_lsn=$2")
        ;;
    drop-role|enable-login|disable-login)
        [[ $# == 1 && $1 =~ ^[0-9]+$ ]]
        variables=(-v "created_role_oid=$1")
        if [[ $operation == *-login ]]; then
            sql_file=login
            variables+=(-v "enable_login=$([[ $operation == enable-login ]] && printf true || printf false)")
        fi
        ;;
    *) [[ $# == 0 ]] ;;
esac

disposable_id=$(<"secrets/$COMPOSE_PROJECT_NAME-fixture-id")
[[ $disposable_id =~ ^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$ ]]
docker=(docker --host unix:///var/run/docker.sock)
compose=("${docker[@]}" compose -f compose.source.yaml --profile source)
cid=$("${compose[@]}" ps -q source-db)
volume="${COMPOSE_PROJECT_NAME}_source-pg"
image=$(sed -n 's/^    image: //p' compose.source.yaml)

test "$("${docker[@]}" inspect -f '{{.State.Health.Status}} {{.Image}}' "$cid")" = \
    "healthy $("${docker[@]}" image inspect -f '{{.Id}}' "$image")"
test "$("${docker[@]}" inspect -f '{{len .NetworkSettings.Networks}} {{range .NetworkSettings.Networks}}{{.NetworkID}}{{end}}' "$cid")" = "1 $SOURCE_INPUT_ID"
test -z "$("${docker[@]}" port "$cid")"
test "$("${docker[@]}" inspect -f '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Type}} {{.Name}}{{end}}{{end}}' "$cid")" = "volume $volume"
test "$("${docker[@]}" volume inspect -f '{{.Driver}} {{index .Labels "com.docker.compose.project"}} {{index .Labels "com.docker.compose.volume"}}' "$volume")" = "local $COMPOSE_PROJECT_NAME source-pg"
test "$("${docker[@]}" network inspect -f '{{.Id}} {{.Driver}} {{.Internal}} {{.EnableIPv6}}' "$SOURCE_INPUT_ID")" = "$SOURCE_INPUT_ID bridge true true"

bridge=$("${docker[@]}" network inspect -f '{{index .Options "com.docker.network.bridge.name"}}' "$SOURCE_INPUT_ID")
python3 - "${bridge:-br-${SOURCE_INPUT_ID:0:12}}" <<'PYTHON'
import sys
from scripts.isolation.preflight import check_firewall

check_firewall(sys.argv[1])
PYTHON

{
    cat "$here/guard.sql"
    cat "$here/$sql_file.sql"
} | "${docker[@]}" exec -i "$cid" sh -ec '
    PGPASSWORD=$(cat "$POSTGRES_PASSWORD_FILE")
    export PGPASSWORD PGCONNECT_TIMEOUT=3 PGREQUIREAUTH=scram-sha-256 LC_ALL=C
    exec psql -XwqAt -v ON_ERROR_STOP=1 -v VERBOSITY=verbose -h 127.0.0.1 -U source_admin -d source_lab "$@" -f -
' sh -v "disposable_id=$disposable_id" -v "run_key=$CDC_RUN_KEY" "${variables[@]}"
