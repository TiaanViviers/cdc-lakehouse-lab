# Four-table CDC experiment

Run [EXP-017](../../../docs/experiments/EXP-017-cdc-baseline.md) in the scheduled disconnected lab guest. Use a fresh guest overlay, checked-out repository copy and Compose project for each case. The baseline holds fixture writes during onboarding and advances S00 through S04 one checkpoint at a time. The copy-window case holds an active source COPY while the regular runner commits S01, then tests item 102 update and delete after exact S01. Both use the same CDC runtime and independent fixture comparator.

## Stage

Follow the [pinned consumer staging instructions](../../../docs/cdc-consumer.md#stage-and-verify-the-image) for `source.tar`, `consumer.tar` and `probe.tar`. Stage `runner.tar` from the [Phase 1 runner build](../../../docs/source-runner.md#stage-and-provision) under the tag `cdc-lab-fixture-runner:v1-1.8`. The EXP-009 artifact already has that tag. Use the selected linux/amd64 manifest digest as reported by the guest's containerd image store. On a classic Docker store the image ID can be the config digest instead. For the reviewed single-manifest archive, generate the staging files as follows:

```bash
set -euo pipefail
tar -xOf "$media/runner.tar" index.json |
    python3 -c 'import json,sys; (m,) = json.load(sys.stdin)["manifests"]; print(m["digest"])' > "$media/runner.id"
git archive --format=tar --prefix=repo/ HEAD > "$media/repo.tar"
git rev-parse HEAD > "$media/revision"
(cd "$media" && sha256sum source.tar consumer.tar probe.tar runner.tar runner.id revision repo.tar > SHA256SUMS)
xorriso -as mkisofs -quiet -r -J -o exp017.iso "$media"
```

## Run

Use the [Phase 2 runtime conventions](../../../backlog/phase-2.md#parallel-development-and-runtime-conventions) and hold the shared VM lock for the full guest lifetime. Start the rootful guest Docker daemon with the containerd store and both iptables families enabled. Boot with two vCPUs, 2 GiB RAM, no NIC, and the read-only ISO. In the guest root console:

```bash
mkdir /mnt/exp017 /root/exp017
mount -o ro /dev/sr0 /mnt/exp017
(cd /mnt/exp017 && sha256sum -c SHA256SUMS)
tar -xf /mnt/exp017/repo.tar -C /root/exp017
cd /root/exp017/repo
export CDC_REVISION="$(cat /mnt/exp017/revision)"
export CDC_OVERLAY=guest-baseline.qcow2  # Supply the actual overlay identity.
timeout --foreground -k 60s 480s bash tests/integration/cdc-baseline/run.sh /mnt/exp017 baseline
```

Repeat in a fresh overlay with the actual overlay identity and argument `copy-window`. Use one guest at a time. The guard uses the existing publisher CLI's `cdc22-` project prefix with a unique suffix. The script creates and disposes only its own projects. If ownership, quiescence or bridge removal is ambiguous it reports the retained project and leaves protections and root-only credentials in place.

## Inspect

Each run writes under `artifacts/EXP-017/<run-id>/`. Start with `run.txt` and `timeline.jsonl`. Match the Phase 1 runner commit or abort event, the publisher WAL samples, the DuckPipe status samples, and the exact target result for the same hold point. Inspect each checkpoint's normalized source and target snapshots and difference files. In the copy-window run, compare the blocked COPY identity before and after S01, the release event and the subsequent exact read. Catalog snapshots are sampled separately. Each parity read names its fresh PostgreSQL transaction boundary, with per-read timing and unknown per-table DuckLake snapshot attribution.

Exact expected rows, including customer aggregates, are defined in the existing v1 oracle. The supplemental item 102 update checks the full row, an updated timestamp, and customer 1 at 2,600 cents. The delete restores exact S00. A rollback run must observe exact S03 on every sampled post-abort read for at least 10 seconds. Check clean teardown independently of the experiment verdict by requiring both exit fields in `run.txt` to be zero.

## COPY-boundary correction candidate (ticket 2.12)

The [EXP-023 report](../../../docs/experiments/EXP-023-copy-boundary.md) records the
diagnostic counterexample, candidate, run IDs and independent row evidence.
Use the same verified archives and disconnected VM lease described above.
Each command uses a fresh VM overlay and a distinct disposable Compose
project, source and consumer volume. Set `CDC_REVISION` and `CDC_OVERLAY`
from that run's actual media and overlay. All variants use the existing fixture
and oracle. `copy-control` runs the held four-table baseline.

| Schedule | Source commit placement |
| --- | --- |
| `overlap` | After the temporary slot exists and COPY is blocked by the advisory policy. Release as soon as exact source S01 and the same blocked identity are observed. |
| `delayed` | Same witness as `overlap`, with three extra seconds for WAL delivery while COPY is held. |
| `handoff` | Same witness with a bounded delay on the persistent walsender only. The source commits normally. Resume delivery after the temporary slot disappears and mapping 4 is observed in CATCHUP. |
| `before-slot` | S01 commits before order-items registration and that table's temporary slot. |
| `after-copy` | S01 commits after exact order-items S00 and temporary slot release. |

The controller captures the runner XID, bounded XID-filtered PG16
`pg_waldump`, source and target parity, slot identities and redacted connector
traces. In the three overlap schedules, start the 60-second target budget at
advisory hold release. Each successful S01 has a full-row item 102 update and
a delete back to exact S00. Require both experiment and cleanup exit codes to
be zero. A failed or inconclusive trial retains its own artifacts.

The diagnostic library adds traces with the pinned admission rule. The fixed
library adds the catch-up change. Both start from upstream
`86d5c248d80370fb2e10ddc1abd780fd94c3a52b`. Apply patch 1 of the
two-message series to reproduce the diagnostic library, or apply both for the
candidate. The runtime overlay replaces only the DuckPipe shared library on
the exact consumer image and verifies the file and its read-only mount.

```bash
git clone https://github.com/relytcloud/pg_duckpipe.git "$upstream"
git -C "$upstream" switch -c lab-copy-212 86d5c248d80370fb2e10ddc1abd780fd94c3a52b
git -C "$upstream" am "$PWD/tests/integration/cdc-baseline/duckpipe/2.12.patch"
rustup toolchain install 1.95.0 --profile minimal --component rustfmt
bash tests/integration/cdc-baseline/duckpipe/build.sh "$upstream" "$media/consumer.tar" "$build"
```

Use Ubuntu 24.04 x86-64 with GCC 13.3, Clang/libclang 18.1.3, Python 3.12,
binutils and dpkg-deb on the staging host. The build script verifies the
consumer OCI and two development package digests, uses the locked Rust
workspace, checks the Bookworm ABI and runs the three targeted regressions.
Build in separate dedicated directories when comparing variants. Record
toolchain versions, source tree ID and library SHA-256.

Copy the built library to the read-only media as `pg_duckpipe.so`, add
`candidate.kind` containing precisely `fixed` or `diagnostic`, and include
both in `SHA256SUMS` with the existing media files. Follow the same
`git archive` and guest boot procedure above. From the extracted repository,
run the desired schedule and review the recorded library digest.

```bash
timeout --foreground -k 60s 480s bash tests/integration/cdc-baseline/run.sh "$media" copy-boundary handoff diagnostic
timeout --foreground -k 60s 480s bash tests/integration/cdc-baseline/run.sh "$media" copy-boundary handoff fixed
timeout --foreground -k 60s 480s bash tests/integration/cdc-baseline/run.sh "$media" copy-control held fixed
```

For the original binary, pass `stock` and omit both candidate files. For
reversal, tear down the candidate's disposable project and run the original
pin on a fresh project without the overlay. The version, SQL schema, stock
source and canonical Compose image pin stay the same throughout.
