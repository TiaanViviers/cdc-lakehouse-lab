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
