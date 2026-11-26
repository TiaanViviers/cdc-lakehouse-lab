"""Render the verified 2.6 guest launcher with only ticket-specific changes."""
from pathlib import Path

source = Path("tests/integration/cdc-baseline/run.sh").read_text()
replacements = (
    ('cd "$(dirname "$0")/../../.."', "# Caller is already in the workspace root."),
    ("    baseline|copy-window) experiment=017 ticket=43 sequence=26 controller=cdc-baseline/baseline.py ;;",
     "    graceful|abrupt|retention) experiment=018 ticket=44 sequence=27 controller=cdc-recovery/recovery.py ;;"),
    ("rollback hold 10s", "ordinary offline WAL span <16MiB, retention trial <=11 segment switches"),
)
for old, new in replacements:
    if source.count(old) != 1:
        raise SystemExit(f"2.6 launcher interface changed at {old!r}")
    source = source.replace(old, new)
print(source, end="")
