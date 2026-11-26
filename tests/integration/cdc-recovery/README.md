# Same-slot restart and WAL retention experiments

Run [EXP-018](../../../docs/experiments/EXP-018-cdc-recovery.md) in the disconnected lab guest. Use a fresh overlay, checkout, project, bridge, source, and consumer for each of the three cases. The launcher consumes the merged 2.6 isolation and teardown script through explicitly checked substitutions. The recovery driver reuses 2.6 enrollment, onboarding and checkpoint methods, the existing fixture oracle and both telemetry adapters.

## Reproduce

Use the [EXP-017 staging commands](../cdc-baseline/README.md#stage) with this revision. Keep the approved PostgreSQL, DuckPipe and Phase 1 runner archives and their reviewed digests. Reserve the guest and hold `flock -x /tmp/cdc-lab-vm-runtime.lock` for the full guest session. Boot the lab's fresh 2-vCPU, 2-GiB KVM overlay with no NIC, the read-only ISO, the local Docker containerd store and both iptables families. In the guest root console:

```bash
mkdir /mnt/exp018 /root/exp018
mount -o ro /dev/sr0 /mnt/exp018
(cd /mnt/exp018 && sha256sum -c SHA256SUMS)
tar -xf /mnt/exp018/repo.tar -C /root/exp018
cd /root/exp018/repo
export CDC_REVISION="$(cat /mnt/exp018/revision)"
export CDC_OVERLAY=guest-01.qcow2  # Use the actual overlay name.
timeout --foreground -k 60s 480s bash tests/integration/cdc-recovery/run.sh /mnt/exp018 graceful
```

Repeat in separate fresh overlays with `abrupt` and `retention`. Do not run against a retained experiment project or any external source. Use a different overlay name and separate evidence export for each trial.

## Cases and bounds

| Trial | Fault and recovery |
| --- | --- |
| `graceful` | After exact S02 and an active-slot sample, use `docker stop --time=12 <exact-consumer-id>`. While the same slot is inactive, commit S03 and S04 through the Phase 1 runner, with independent source parity after each. Start the same container and use `duckpipe.start_worker` for the existing group. Confirm exact S04, continued S05 and a fresh read. |
| `abrupt` | With source and target at S02, update one existing row to its current value on each of three tables, then issue a no-op customer update. Compare group and source slot positions across those distinct stages. Try to bracket S03 with queued order-items work and a stale exact S02 target. Send SIGKILL to the exact consumer container. Commit S04 while offline, verify the durable pre-worker state when observable, then resume the same slot and verify S04/S05. An unobserved buffered or acknowledgement boundary is reported explicitly. |
| `retention` | Stop the consumer at exact S02 in a separate clone, commit S03/S04, then generate one small nontransactional logical marker per forced 16 MiB segment switch and checkpoint. Stop at observed slot loss or the first limit. Try normal reconnect first. If the slot is invalidated and the old catalog must be retired, quiesce and remove only the tracked mappings and group, confirm an empty publisher inventory, retire the old consumer volume and initialize an empty one. Use a fresh connector snapshot against unchanged exact source S04, then run S05. |

The pinned profile uses a 128 MiB slot limit with no archive or explicit WAL keep floor. The ordinary source outage permits only the specified fixture writes, a 35-second write deadline and a 16 MiB insert-to-restart span. The retention trial uses the existing 128 MiB limit and at most 11 explicit segment switches, 176 MiB insert-to-restart allowance and a 50-second forcing window. Both retain the original 256 MiB allocated source WAL stop threshold, 512 MiB per database volume, 1 GiB available disk floor, and database and runner cgroup limits. The retention span measures WAL addresses after forced switches and can exceed physical WAL allocation after recycling. The outer timeout bounds the guest run. Target parity has a 60-second deadline and polls after a 500 ms delay. Guest SQL health is separate from the recovery verdict.

The undo for a graceful or abrupt interruption is `docker start <exact-consumer-id>` followed by `SELECT duckpipe.start_worker('<tracked-group>');` in the restarted consumer once authenticated health returns. The retention experiment's resnapshot branch deliberately replaces the old disposable consumer volume only after the slot is verified lost and the exact old group and publisher objects are retired. It preserves the enrolled source and its S04 receipt.

## Evidence

Start with `artifacts/EXP-018/<run>/run.txt` and `timeline.jsonl`. Compare the runner's commit records, independently normalized source and target rows and keyed diffs, publisher LSNs and allocated WAL, consumer group/mapping progress, and redacted log excerpts. The `resnapshot/` subdirectory preserves fresh-catalog evidence alongside the lost-slot evidence in the original directory. The observer records source insertion LSN brackets with no attributable transaction COMMIT or END LSN. A request to stream from an earlier position allows replay without establishing which messages were delivered twice.
