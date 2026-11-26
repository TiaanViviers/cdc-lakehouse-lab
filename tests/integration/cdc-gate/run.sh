#!/usr/bin/env bash
# Run the whole pair in the reserved, disconnected guest.
set -euo pipefail
umask 077
cd "$(dirname "$0")/../../.."
media=$(realpath "${1:?read-only staging media directory}")
mkdir -p artifacts/EXP-020
pair=$(mktemp -d "$PWD/artifacts/EXP-020/pair-XXXXXXXX")
echo "Gate evidence: $pair"

for attempt in first repeat; do
    echo "Fresh gate project: $attempt"
    # A second project starts only after the prior launcher's checked teardown.
    timeout --foreground -k 60s 480s bash tests/integration/cdc-baseline/run.sh "$media" gate "$pair"
done
PYTHONPATH=. python3 tests/integration/cdc-gate/verdict.py "$pair"
