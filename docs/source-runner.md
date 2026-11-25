# Source fixture runner

[Ticket 1.5 (#23)](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/23) runs fixture v1, seed 42, on the isolated Phase 1 source. [EXP-006](experiments/EXP-006-source-runner.md) records the sequential checkpoint, visibility and resource evidence. [S05 ordered overlap](source-overlap.md) uses the same CLI and staging instructions below.

## Stage and provision

Build the linux/amd64 image on the staging host and transfer the archive on read-only media to the disconnected source VM. The image uses the pinned CPython base and hash-locked wheels in [the runner build](../scripts/source/runner.Dockerfile). The PostgreSQL image, schema and network gate come from the [source profile](source-profile.md) and [schema setup](source-schema.md). Run the startup gate on `compose.source.yaml` alone, then load the runner image. Keep the isolation rules active for the life of both services.

```bash
mkdir -p artifacts
set -o pipefail
tar -cf - scripts/source/runner.Dockerfile scripts/source/runner.requirements.txt \
    scripts/source/{runner,workload,checkpoints,transactions,overlap,replay}.py \
    tests/{__init__,fixture_oracle}.py tests/fixtures/v1/expected.json |
    docker build --platform linux/amd64 -f scripts/source/runner.Dockerfile \
        -t cdc-lab-fixture-runner:v1-1.7 -
docker image save -o artifacts/runner.tar cdc-lab-fixture-runner:v1-1.7
# Inside the disconnected VM, after source startup and schema bootstrap
labdocker load -i /mnt/source/runner.tar
labdocker image inspect -f '{{.Id}} {{.Os}}/{{.Architecture}}' cdc-lab-fixture-runner:v1-1.7
```

During schema password provisioning, save the two distinct disposable role passwords in root-owned files, mode `0600`, in the VM's repository-local `secrets/` directory. Use `source-fixture-writer-password` and `source-fixture-reader-password` as filenames. The reset identity file is the existing `secrets/${COMPOSE_PROJECT_NAME}-fixture-id` created at schema bootstrap. Use the UUID saved for that project and volume. The runner overlay mounts these files and attaches to the same external bridge ID as `source-db`. It publishes no ports and uses no source administrator credentials.

## Run and inspect

Use the same `COMPOSE_PROJECT_NAME` and `SOURCE_INPUT_ID` as the verified source. Pause other fixture clients before sequential writes or reset. S00–S04 validate their complete predecessors, including the report and receipts. S00 requires the empty state. Use the guarded reset to start over from any previously populated checkpoint. The [S06 replay guide](source-replay.md) describes receipt-based recovery and its concurrent delivery test.

```bash
run_id="$(date -u +%Y%m%dT%H%M%SZ)-p01-01"
fixture_runner() {
    labdocker compose -f compose.source.yaml -f compose.runner.yaml --profile source \
        run --rm --no-deps -T fixture-runner --run-id "$run_id" "$@"
}

fixture_runner --fixture v1 --seed 42 run S00
fixture_runner run S01
fixture_runner run S02
fixture_runner run S03
fixture_runner run S04 --rollback
fixture_runner --attempt 2 run S04
fixture_runner inspect S04
fixture_runner reset --confirm
fixture_runner inspect S00
```

`run S04 --rollback` succeeds when the requested rollback is observed and the reader still sees exact S03. `reset --confirm --fail-after-cleanup` intentionally fails after verifying cleanup inside the transaction and rolls back to the original state. Reset checks the identity through `fixture.cleanup` and commits cleanup and S00 together. `inspect` is read-only and emits the complete canonical state, report, receipt rows and any differences. For a wrong-identity acceptance probe only, the overlay supports setting `SOURCE_FIXTURE_ID_FILE` to a local file with a different UUID while leaving the enrolled file intact.

Each JSON trace carries the run ID, fixture version, seed, scenario, attempt, variant and actual UTC observation time. The fixed workload clock supplies business timestamps. The Compose job has a 256 MiB memory cap with swap disabled, 0.5 CPU and 32 PIDs. It uses 3 s connect, 5 s statement, 2 s lock and 15 s idle-in-transaction timeouts, with a 45 s process deadline and a 2 s forced-kill grace period. Exit 2 rejects arguments, exit 1 reports a source or checkpoint failure, and GNU `timeout` uses exit 124 when its deadline expires. A `commit_requested` event without `commit_acknowledged` requires an independent inspection before another write. If the writer acknowledged commit and inspection then failed, the committed rows still need verification.

## Interfaces for the next Phase 1 tickets

- [workload.py](../scripts/source/workload.py) supplies fixture identity, the UTC fixture clock and the ordered S04 payload and digest.
- [transactions.py](../scripts/source/transactions.py) supplies connection setup, the explicit writer transaction context, the S04 claim and the ordered insert operations. Callers own their connection and commit or roll back when exiting the transaction context. The sequential CLI holds an advisory lock across its preflight, write and post-transaction observation. Coordinate any concurrent schedule with reset and other writers.
- [checkpoints.py](../scripts/source/checkpoints.py) supplies consistent independent reads and comparison with the stable 1.4 oracle. The receipt check is separate from business and report parity.

## Reproduce the acceptance suite

Bootstrap a fresh disposable project and provision both fixture roles. Use the [source disk checks](source-profile.md#verify-limits-and-storage) before and after the suite. The harness runs the accepted steps, verifies rejected commands against the prior exact snapshots, checks both reset runs, and records Engine and cgroup measurements in a new directory under local artifacts. Expect the suite to end at S00.

```bash
mkdir -p artifacts
bash tests/integration/source-runner/run.sh "$run_id" "artifacts/$run_id"
```

When finished, stop the source and remove the lab bridge rules using the [source stop procedure](source-profile.md#verify-a-clean-restart-and-stop).
