#!/usr/bin/env bash
# Reuse the merged 2.6 guest isolation, provisioning and guarded disposal.
set -euo pipefail
cd "$(dirname "$0")/../../.."
media=${1:?staging media}
trial=${2:?graceful, abrupt or retention}
case $trial in graceful|abrupt|retention) ;; *) exit 2 ;; esac
launcher=$(mktemp)
trap 'rm -f "$launcher"' EXIT
python3 tests/integration/cdc-recovery/launcher.py > "$launcher"
bash "$launcher" "$media" "$trial"
