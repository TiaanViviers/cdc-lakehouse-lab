"""Compare both runs' independently verified checkpoint rows and gate outcomes."""

import hashlib
import json
from pathlib import Path
import sys

from tests.fixture_oracle import compare_checkpoint, load_expectations


CHECKPOINTS = ("S00", "S01", "S02", "S03", "S04", "S05")


def canonical_hash(rows):
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def verified_hashes(run):
    expected = load_expectations()
    hashes = {}
    for step in CHECKPOINTS:
        for side in ("source", "target"):
            snapshot = json.loads((run / step / f"{side}.snapshot.json").read_text())
            diff = json.loads((run / step / f"{side}.diff.json").read_text())
            rows = snapshot["rows"]
            if (snapshot["checkpoint"] != step or snapshot["side"] != side
                    or diff["status"] != "pass" or diff["diffs"]
                    or compare_checkpoint(expected[step], rows)):
                raise RuntimeError(f"{run.name}: {step} {side} is not independently exact")
            hashes[f"{step}/{side}"] = canonical_hash(rows)
    return hashes


def verdict(pair):
    runs = sorted(path for path in pair.iterdir() if path.is_dir())
    if len(runs) != 2:
        raise RuntimeError("expected two fresh gate runs")
    observed = [verified_hashes(run) for run in runs]
    results = [json.loads((run / "gate.json").read_text()) for run in runs]
    if observed[0] != observed[1] or any(
        observed[0][f"{step}/source"] != observed[0][f"{step}/target"] for step in CHECKPOINTS
    ):
        raise RuntimeError("canonical checkpoint hashes differ")
    for key in ("project", "bridge", "source_system", "consumer_system"):
        if results[0][key] == results[1][key]:
            raise RuntimeError(f"fresh-run identity was reused: {key}")
    if results[0]["revision"] != results[1]["revision"] or results[0]["images"] != results[1]["images"]:
        raise RuntimeError("the two runs used different revisions or images")
    for run in runs:
        if not (run / "teardown.ok").is_file():
            raise RuntimeError(f"{run.name}: missing verified teardown")

    retention = {run.name: result["retention"] for run, result in zip(runs, results, strict=True)}
    passed = {"progress_observed": True, "persistent_growth": False}
    met = all(result == passed for result in retention.values())
    summary = dict(verdict="M2 met" if met else "M2 unmet", hashes=observed[0], retention=retention)
    (pair / "verdict.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(summary["verdict"])
    return 0 if met else 1


if __name__ == "__main__":
    sys.exit(verdict(Path(sys.argv[1])))
