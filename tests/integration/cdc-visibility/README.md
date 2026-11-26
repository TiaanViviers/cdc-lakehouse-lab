# CDC transaction visibility

Run [EXP-019](../../../docs/experiments/EXP-019-cdc-visibility.md) on the ADR-002 disconnected guest. Reserve the VM with the maintainer and hold the shared runtime lock for the full guest lifetime. Each case uses a fresh guest overlay, checkout, project, bridge and pair of database volumes. The three cases use the existing Phase 1 S04 and S05 schedules. The observer temporarily holds the source runner at its verified boundaries and only reads Bronze.

## Stage and run

Stage the four image archives and runner manifest ID using the [EXP-017 staging commands](../cdc-baseline/README.md#stage). Archive this ticket's commit into `repo.tar`, write its SHA into `revision`, and regenerate `SHA256SUMS`. Boot the same no-NIC 2-vCPU / 2-GiB guest with the verified read-only ISO, after the preceding trial has shut down. Start the rootful guest Docker Engine with its containerd image store and both iptables families enabled. In the guest root console:

```bash
mkdir /mnt/exp019 /root/exp019
mount -o ro /dev/sr0 /mnt/exp019
(cd /mnt/exp019 && sha256sum -c SHA256SUMS)
tar -xf /mnt/exp019/repo.tar -C /root/exp019
cd /root/exp019/repo
export CDC_REVISION="$(cat /mnt/exp019/revision)"
export CDC_OVERLAY=guest-rollback.qcow2  # Use the actual overlay identity.
timeout --foreground -k 60s 480s bash tests/integration/cdc-visibility/run.sh /mnt/exp019 rollback
```

Repeat on separate overlays with `overlap-commit` and `overlap-abort` in place of `rollback`. Both overlap cases commit S04 first. `overlap-abort` treats exit 1 from the Phase 1 after-A fault as expected only when its independent source read proves exact A-only rows and B's aborted XID. Each full experiment and cleanup must exit 0.

## Read the trace

Start with `artifacts/EXP-019/<run-id>/run.txt`, `timeline.jsonl`, and the source runner JSONL for the relevant schedule. This example prints a bounded view of the observed row states:

```bash
jq -c 'select(.event == "target_read_finished") |
  {utc, checkpoint, started_ns, elapsed_ns, snapshot_id, engine_before,
   engine_after, pg_before, pg_after, visibility, exact, report: .rows.report}' timeline.jsonl
```

- `target_read_finished` records all four bounded projections and both customer report rows. It identifies one engine statement, an explicit version in all four scans, or a legacy-style PostgreSQL transaction by the fields present. `pg_snapshot` and `catalog_head` in the native capture describe PostgreSQL's snapshot. The DuckLake identity calls surround the native scans.
- `retained_catalog_versions` records the actual ordered list from the catalog, with timestamps and changesets. Pair every listed ID with the corresponding versioned read. `first_exact_engine_read` gives the first exact result observed live. `first_exact_retained_version` gives the earliest exact version found in the bounded catalog range.
- `release_source_gate` records observer time. The Phase 1 runner acknowledges the source outcome separately, and its barrier records include XIDs, statuses, exact rows and receipt evidence where supplied by the Phase 1 control. Slot and worker telemetry are separate samples.
- `intentional_cross_version_control` reconstructs the item-first signature from two known versions. A versioned read with those same keys is distinguishable by its one explicit snapshot ID across all four scans.

Read `catalog.json`, `resources.txt` and the last publisher and consumer samples for storage, budget and cleanup context. Export selected redacted results and checksums before discarding any guest overlay.
