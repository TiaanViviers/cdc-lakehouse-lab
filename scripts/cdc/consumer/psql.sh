#!/usr/bin/env bash
# Authenticated administrative SQL inside the consumer. SQL travels on stdin.
set -euo pipefail
cid=${1:?usage: psql.sh CONSUMER_ID [psql arguments]}
shift
[[ $cid =~ ^[0-9a-f]{64}$ ]] || exit 2
exec timeout --foreground -k 1s "${CDC_SQL_TIMEOUT:-10}s" \
    docker --host unix:///var/run/docker.sock exec -i --user postgres "$cid" sh -ec '
    export PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")"
    export PGREQUIREAUTH=scram-sha-256 PGCONNECT_TIMEOUT=2
    export PGOPTIONS="-c statement_timeout=5000 -c lock_timeout=2000 -c timezone=UTC"
    exec psql -XwqAt -v ON_ERROR_STOP=1 -h cdc-catalog -U postgres -d postgres "$@"
' sh "$@"
