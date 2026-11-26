# Verify Phase 2 CDC

[Ticket 2.9 (#46)](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/46) tests the pinned PostgreSQL 16.16 publisher and DuckPipe consumer with the local DuckLake sink. The paired subgate uses the synthetic v1/42 fixture and independently checks both databases. See the [M2 decision and observations](experiments/EXP-020-phase-2-cdc-gate.md).

## Schedule and stage

Reserve the existing 2-vCPU, 2-GiB disposable guest and hold `flock -x /tmp/cdc-lab-vm-runtime.lock` on the host throughout its lifetime. Boot a fresh overlay with KVM, `-nic none` and read-only transfer media. Start the rootful guest Docker Engine with the containerd store and both iptables families. Keep all trials serial. [Approved runtime conventions](../backlog/phase-2.md#parallel-development-and-runtime-conventions)

From the ticket checkout based on current merged main, stage the source, consumer, probe and fixture-runner artifacts using the [pinned staging recipe](../tests/integration/cdc-baseline/README.md#stage). Include GNU Make 4.3 if the guest lacks it and add the binary to the media checksum manifest. Archive the exact tested revision as `repo.tar` with the `repo/` prefix.

```bash
mkdir /mnt/exp020 /root/exp020
mount -o ro /dev/sr0 /mnt/exp020
(cd /mnt/exp020 && sha256sum -c SHA256SUMS)
tar -xf /mnt/exp020/repo.tar -C /root/exp020
cd /root/exp020/repo
export CDC_REVISION="$(cat /mnt/exp020/revision)"
export CDC_OVERLAY=guest-020.qcow2  # Use the actual overlay identity.
make test-cdc MEDIA=/mnt/exp020
```

The command verifies staging and isolation before either project starts. Each project gets new credentials, source and consumer clusters, volumes and a dual-stack internal bridge. The second project starts after the first has removed replication objects, both containers and volumes, the bridge and its firewall rules. If the launcher reports incomplete teardown, preserve the recorded project and protections and inspect the failed identity or stop step. Use a fresh overlay after a failed experiment or uncertain disposal.

Each project has a 480-second limit and a 60-second target parity limit per checkpoint. The two database memory ceilings are 768 and 512 MiB, with a 256 MiB one-shot runner. CPU quotas are 1, 0.75 and 0.5, respectively. Database swap is disabled and each database has a 128-PID cap. Require less than 512 MiB per volume, less than 256 MiB allocated source WAL, a 64 MiB consumer tmpfs, and at least 1 GiB free. The ordinary restart uses the existing sub-16-MiB retained span and 35-second offline write limit. The active sparse-table control allows three 16-MiB segment switches and checkpoints, a retained address span under 64 MiB, and requires positive slot headroom. The 128-MiB PostgreSQL slot setting remains in force.

## Read the results

Start in `artifacts/EXP-020/pair-*/`. A completed pair writes `verdict.json` with `scope: paired-subgate`, a `pass` or `fail` result, canonical hashes, both retention results and `requires_m2_review: true`. Exit zero is a pass for the paired subgate. A negative retention result returns a failing Make status. A startup, runtime, parity or teardown error can stop before the summary is written. Use the stage and project in `run.txt` to distinguish an incomplete run from a reproduced product failure. The paired initial copy holds source writes.

The full M2 decision requires an explicit review of the paired and auxiliary results. Follow the [review criteria](#review-the-full-m2-decision) with every paired result.

- **Keyed correctness.** Each `S00`–`S05` directory contains full normalized source and Bronze rows, both report rows and independent oracle comparisons. The pair verifier hashes the canonical row payloads. Item 102 must be absent on both sides after S03. Rollback checks include exact S03 at each sampled read and at every retained version in range. S05 includes the both-open and A-committed/B-open barriers and the independently checked terminal state.
- **Recovery and authentication.** Follow S02 durability before the restarted worker runs, the inactive slot during the offline S03 delete, exact S03 after catch-up, and the preserved S04 catalog and rows after replacing the consumer. Check the container changed and the cluster, volume, group and mapping identities persisted. Both fresh TCP peers require SCRAM and a specific rejection for wrong passwords. The source rejects the scoped publisher in the wrong database. After replacement the consumer cannot reach either positive guest gateway listener.
- **WAL and disk.** Match the sender and slot samples to the group and per-table positions. Compare `safe_wal_size`, the insert-to-restart address span and allocated WAL. After S05 the active sparse control commits noncustomer updates that preserve fixture values, checks their table apply positions and measures retention headroom. Inspect `resources.txt` for memory peaks, swap and OOM counters, CPU use and throttling, disk allocation and free space.
- **Local sink.** Compare `before-replacement-catalog.json` and the recreation event to the pre-worker row read. `inline-catalog.json` documents ordinary writes. `file-catalog.json` records the scoped quiescent order-items flush, checked physical size, Parquet magic and digests for data and delete references. The catalog can retain history alongside the live rows. The gate also checks exact target rows with the worker stopped. Use the separate consumer acceptance to reproduce physical-file persistence across replacement.

Run `make help check BASE=origin/main`, `make test-unit`, and `sh tests/repository-checks.sh`. Then run the existing [source-only `make test-integration`](source-gate.md) on its own fresh source project. Exercise the associated fault and scope controls using their existing commands on separate fresh overlays. Review the logged observations since some exploratory controls can return success while recording an inconclusive window. [Consumer profile](cdc-consumer.md#reproduce-exp-015) · [Baseline and COPY hold](../tests/integration/cdc-baseline/README.md) · [Abrupt and retention-loss trials](../tests/integration/cdc-recovery/README.md) · [Rollback and ordered overlap](../tests/integration/cdc-visibility/README.md)

## Review the full M2 decision

Record the authoritative M2 decision in the experiment report after reviewing all mandatory evidence. For positive acceptance, require the same tested runtime revision and effective configuration across the paired and auxiliary runs, with the same selected image pins wherever each component is used. Record the revisions and artifact identities in the review. [Issue #46](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/46) · [Approved gate](../backlog/phase-2.md#29-verify-the-complete-phase-2-cdc-gate)

1. Require a passing paired subgate with the exact S00–S05 rows and hashes, rollback exclusion, deleted-key absence, same-slot catch-up, continued apply after replacement, and verified teardown from both fresh projects. Inspect the measured retention and resource bounds alongside the keyed results.
2. Require a separate positive [controlled COPY-overlap trial](../tests/integration/cdc-baseline/README.md#inspect). Match the same blocked COPY backend and temporary slot before and after the independently verified S01 source commit. After release, require exact source and target S01 within the deadline, the full item 102 update and subsequent delete back to exact S00, and clean teardown. A failed, missing or unwitnessed COPY result leaves M2 unmet.
3. Review the source-only checks, scoped publisher lifecycle, authentication and isolation, consumer catalog and file persistence, and the separate abrupt interruption, WAL-loss and visibility trials. Use each at its documented boundary. An expected lost-slot rejection and clean resnapshot demonstrate the loss boundary. An unobserved exploratory crash or visibility window limits the claims from that trial. Missing, failed or inconclusive evidence for any mandatory outcome leaves M2 unmet.

A positive result across the subgate and auxiliary checks is evidence for the review. Only the explicit full decision records M2 as met.

## Read-only operator walkthrough

For a completed run, open `walkthrough.json` and find `read-only-S04` in `timeline.jsonl`. The capture runs after independently verified S04 and before consumer replacement, with later writes held. For live inspection, take the container IDs, source system identifier, group, slot and publication from `runtime.json`. Read the Compose project name and full bridge ID from `run.txt`, and set `run_id` to the run directory name. Use the isolated guest with the source held at the same checkpoint.

1. Run the [walkthrough SQL](../tests/integration/cdc-gate/walkthrough.sql) against the publisher. It should show read-only mode, values for order 30, item 301 and payment 302, and absence of item 102. Use the S04 runner record to locate the committed XID.

   ```bash
   docker --host unix:///var/run/docker.sock exec -i --user postgres "$source_id" sh -ec '
       PGPASSWORD=$(cat "$POSTGRES_PASSWORD_FILE")
       export PGPASSWORD PGREQUIREAUTH=scram-sha-256 PGCONNECT_TIMEOUT=2
       export PGOPTIONS="-c statement_timeout=5000 -c lock_timeout=2000"
       exec psql -XwqAt -v ON_ERROR_STOP=1 -v schema=fixture \
           -h 127.0.0.1 -U source_admin -d source_lab
   ' < tests/integration/cdc-gate/walkthrough.sql
   ```

2. Run the publisher observer. It selects the exact publication members from `pg_publication_tables` and joins the tracked slot’s `active_pid` to the sender in `pg_stat_replication`. Use the plugin, database, restart and confirmed LSNs, WAL status, headroom and sender position from its read-only JSON. The source acknowledgement and these WAL observations have no attributed COMMIT or END LSN.

   ```bash
   python3 -m scripts.cdc.wal.observe \
       --project "$project" --container "$source_id" --bridge "$bridge_id" \
       --system-identifier "$source_system" --run-id "$run_id" \
       --phase gate --checkpoint read-only-S04 --slot "$slot" --publication "$publication" \
       --member fixture.customers --member fixture.orders \
       --member fixture.order_items --member fixture.payments
   ```

3. On the consumer run `bash scripts/cdc/consumer/status.sh "$consumer_id" "$group" "$run_id" read-only-S04 0`. Match the group to the publication and slot, then inspect the worker PID, four table states, snapshot and applied positions, and queues. The consumer worker and the publisher sender run on different servers.
4. Run the same keyed SQL on the actual target and compare it to the publisher.

   ```bash
   bash scripts/cdc/consumer/psql.sh "$consumer_id" -v schema=bronze \
       < tests/integration/cdc-gate/walkthrough.sql
   python3 scripts/cdc/consumer/catalog.py "$consumer_id"
   ```

The full S04 proof checks all four row sets and both reports, and separately reads the same explicit DuckLake version across all four tables. The earliest demonstrated safe boundary is an exact named Bronze snapshot at the held, independently confirmed source checkpoint. Pin that verified version for later reads while it remains retained. Slot feedback, worker status and report totals alone cannot locate it. [Versioned proof and partial states](experiments/EXP-019-cdc-visibility.md)
