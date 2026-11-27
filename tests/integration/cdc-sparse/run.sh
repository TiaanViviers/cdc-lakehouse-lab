#!/usr/bin/env bash
# Run against the reviewed image archives in the reserved, disconnected guest.
set -euo pipefail
cd "$(dirname "$0")/../../.."
media=$(realpath "${1:?read-only staging media directory}")
trial=${2:-sparse}
case $trial in sparse|sparse-delayed-flush) ;; *) exit 2 ;; esac
launcher=$(mktemp)
trap 'rm -f "$launcher"' EXIT
python3 tests/integration/cdc-sparse/launcher.py > "$launcher"
timeout --foreground -k 60s 480s bash "$launcher" "$media" "$trial"
