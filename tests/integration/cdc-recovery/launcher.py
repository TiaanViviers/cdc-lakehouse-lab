"""Render the verified 2.6 guest launcher with only ticket-specific changes."""
from pathlib import Path

source = Path("tests/integration/cdc-baseline/run.sh").read_text()
replacements = (
    ('cd "$(dirname "$0")/../../.."', "# Caller is already in the workspace root."),
    ("trial=${2:?baseline or copy-window}", "trial=${2:?graceful, abrupt or retention}"),
    ("[[ $trial == baseline || $trial == copy-window ]]", 'case $trial in graceful|abrupt|retention) ;; *) exit 2 ;; esac'),
    ("-p01-26", "-p01-27"),
    ("artifacts/EXP-017", "artifacts/EXP-018"),
    ("ticket=43", "ticket=44"),
    ("bridge=\"p26", "bridge=\"p27"),
    ("rollback hold 10s", "ordinary offline WAL span <16MiB, retention trial <=11 segment switches"),
    ("tests/integration/cdc-baseline/baseline.py", "tests/integration/cdc-recovery/recovery.py"),
)
for old, new in replacements:
    if source.count(old) != 1:
        raise SystemExit(f"2.6 launcher interface changed at {old!r}")
    source = source.replace(old, new)
print(source, end="")
