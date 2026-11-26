#!/usr/bin/env bash
set -euo pipefail
if [[ $# != 5 || ! $2 =~ ^[a-z][a-z0-9_]{0,39}$ ||
      ! $3 =~ ^[a-zA-Z0-9_.-]{1,64}$ || ! $4 =~ ^[a-zA-Z0-9_.-]{1,64}$ ||
      ! $5 =~ ^[0-9]{1,15}$ ]]; then
    echo "usage: status.sh CONSUMER_ID GROUP RUN_ID CHECKPOINT ELAPSED_MS" >&2
    exit 2
fi
dir=$(cd -- "$(dirname -- "$0")" && pwd)
# Forward only explicit SQL output. The server may include stored credentials in an error.
if ! result=$(bash "$dir/psql.sh" "$1" -v group="$2" -v run_id="$3" -v checkpoint="$4" \
    -v elapsed_ms="$5" < "$dir/status.sql" 2>/dev/null); then
    echo "consumer status query failed" >&2
    exit 1
fi
printf '%s\n' "$result"
