"""Reuse the baseline's pin checks, isolation, provisioning and teardown."""
from pathlib import Path

source = Path("tests/integration/cdc-baseline/run.sh").read_text()
replacements = (
    ('cd "$(dirname "$0")/../../.."', "# Caller is already at the workspace root."),
    ("    baseline|copy-window) experiment=017 ticket=43 sequence=26 controller=cdc-baseline/baseline.py ;;",
     "    sparse) experiment=022 ticket=59 sequence=31 controller=cdc-sparse/sparse.py ;;"),
    ("rollback hold 10s", "first burst 3 epochs, silent 20s, second burst 1 epoch, sparse stage 150s"),
)
for old, new in replacements:
    if source.count(old) != 1:
        raise SystemExit(f"baseline launcher interface changed at {old!r}")
    source = source.replace(old, new)
print(source, end="")
