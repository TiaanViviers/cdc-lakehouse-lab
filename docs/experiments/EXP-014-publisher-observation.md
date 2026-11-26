# EXP-014 — Independent publisher replication and WAL observation

- **Date** 2026-11-26
- **Research question IDs** R04, R05, R16
- **Status** Passed offline, source-only and accepted active-consumer checks.
- **Operator** Ticket 2.4 ([issue #41](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/41))
- **Git branch** `feature/2.4-publisher-observation`, rebased onto `500c213` after the 2.1 merge
- **Software / images** CPython 3.12.3 observed offline. Observed PostgreSQL and psql 16.16 (Debian 16.16-1.pgdg12+1) on the pinned Bookworm source. The active guest used the accepted pinned PG18.4 DuckPipe build. Image index, platform member and config identities matched [EXP-011](EXP-011-remote-pg16-probe.md#image-provenance).

## Hypothesis

An independent source-local observer can identify the expected publication and slot, track publisher positions and attributable feedback, and report WAL retention and disk use within an explicit observation budget. The same interface can represent the absence of replication objects and an inactive slot.

## Preconditions

Run offline checks on the workstation. Schedule the disconnected VM with the maintainer after ticket 2.1 has priority. For the source-only run, use a unique project, bridge, source volume and credentials. Stage this checkout, the pinned images and the isolation probe on read-only media. Follow the [EXP-011 guest procedure](../../tests/integration/remote-probe/README.md#run-in-the-guest) and verify both firewall families, Compose and volume identity, healthy PG16.16 and the source limits before provisioning the synthetic fixture. Use a separate fresh environment for the active trial. The merged [EXP-011 result](EXP-011-remote-pg16-probe.md) accepts the pinned PG18.4 DuckPipe build and its DuckLake 0.4 catalog for this one-table sequence.

Record the owner, run ID, tested SHA, VM overlay, Compose/volume/bridge IDs, image IDs, resolved configuration, database and selected group/publication/slot in a fresh private `artifacts/EXP-014/<UTC-run-id>/`. Record the existing source cgroup, WAL settings and disk checks from the [source profile](../source-profile.md#verify-limits-and-storage). Stop workload generation on sampler error, threshold breach, lost isolation or OOM. The experiment owner controls teardown.

**Decision.** Use the existing authorized disposable `source_admin` connection over source-local loopback and SCRAM, as in the Phase 1 source gate. The observer uses a read-only transaction with a restricted search path. Docker access and the admin role are privileged lab access. This experiment grants no new roles or privileges. Keep credentials in the guest-local secret file. Preserve only allow-listed client output and record generic error codes for failures.

## Procedure

1. Run `make check` and `make test-unit`. The publisher unit tests use synthetic responses with no Docker or PostgreSQL dependency.
2. Stage the pinned images and committed checkout as in the [EXP-011 reproduction](../../tests/integration/remote-probe/README.md#stage-the-images-and-revision). Use the same single-runtime lock, two-vCPU / 2 GiB no-NIC guest and read-only ISO. Use fresh overlays for `source` and `active`, in that order. The trial generates a scratch script from the merged reproducer, checks that its insertion points match, and keeps its pin, firewall, resource and cleanup guards. It uses the reproducer's deterministic `probe.items` values for both trials. The source trial stops before consumer startup.
3. For each guest, mount the media, verify its checksum manifest, extract the checkout and start the local daemon as in EXP-011. From the extracted repository root, run:

   ```bash
   export PROBE_SHA="$(cat /mnt/exp011/revision)"
   export PROBE_OVERLAY=guest-source.qcow2
   trial=source   # Use active on the separate guest, with its actual overlay name.
   python3 -m scripts.cdc.wal.trial instrument "$trial" >/tmp/exp014-run.sh
   bash -n /tmp/exp014-run.sh
   timeout --foreground -k 35s 480s bash /tmp/exp014-run.sh /mnt/exp011 </dev/null
   ```

4. The source trial captures empty inventory, then creates an explicit publication for `probe.items` and an inactive persistent `pgoutput` slot. It verifies exact source rows before and after the independent insert of `(2, 'inserted')`, samples both positions with one observer, and compares native catalog output. It checks rejection of an unexpected name and of an additional inactive slot under the two-slot cap, and checks a one-microsecond observation deadline. Guarded teardown verifies zero remaining slots and publications and unchanged Phase 1 fixture privileges.
5. The active trial uses the accepted snapshot and three DML checkpoints. It checks that the temporary snapshot slot has cleared before starting the observation timeline. At each hold, the merged reproducer checks exact independently read source and target rows. The observation process keeps one monotonic origin for all four live samples. After guarded connector teardown, it captures the empty baseline again.
6. For independent consumption, invoke `python3 -m scripts.cdc.wal.observe --help`. Supply the full container and bridge IDs, Compose project and enrolled PostgreSQL system ID from the recorded run. Request an empty baseline without slot, publication or member arguments. To sample the active hold points, supply the approved names and one `--member schema.table` per expected table. A caller with its own checkpoint driver can reuse `Observer.sample(phase, checkpoint)` on one observer object.

## Expected results

- Empty inventory has null slot, publication, feedback and slot-related spans, plus an empty membership array. Current source LSNs and disk counters are present.
- The inactive baseline identifies the exact logical `pgoutput` slot and `probe.items` membership. It has `active: false`, null PID and null feedback. After the insert, source key 2 has value `inserted` and key 1 still has value `seed`, and the slot's confirmed flush and restart positions remain unchanged with no consumer. The insertion position increases across the committed write and the insert-to-restart span grows. Disk allocation may stay unchanged.
- Independently recompute each populated slot span by converting the hexadecimal halves of the two LSNs to one integer each and subtracting. Compare same-history samples and check increasing monotonic observation boundaries. Use scoped source SQL to corroborate membership and slot state. In the active trial, verify the expected slot is active and any feedback PID matches that slot. Compare before/after feedback with the source commits and corroborate data visibility using exact target keys and values.
- The unexpected-name and extra-slot cases return `slot_identity` and null telemetry. An exhausted wall budget returns a trace row and nonzero status, with `deadline_exhausted` or `capture_timeout` depending on whether a command began.

## Actual observations

**Observed offline.** `python3 -m scripts.cdc.wal.observe --help` exposed the publisher invocation. `make test-unit` passed 32 tests, including eight publisher tests for empty/inactive samples, synthetic feedback, membership and slot identity, bounded attempts, deadline exhaustion, timeout redaction and an observation timeline with a backwards UTC clock. The inactive synthetic fixture retained null feedback and reported a 16-byte between-sample span. The mock deadline invoked no Docker command. A CLI smoke check with synthetic identities and `--budget-seconds 0.000001` exited 1 and emitted one JSONL row with `deadline_exhausted` and null SQL/disk data. `make check` passed.

**Attempt 01, source only.** Run `20261126t082520z` on `8c8a0084d2b7419225c1bea69833974826846f3a` reached the observer checks and exited 1 at a verifier assertion that compared the entire slot JSON. The actual restart and confirmed positions matched before and after. The headroom field `safe_wal_size` decreased by 184 bytes as WAL advanced. The rerun checks the two expected stable positions and keeps headroom as its own measurement. Teardown removed the run's resources and reported an empty slot/publication inventory.

**Attempts 02 and 03.** The source-only run `20261126t082603z` and active run `20261126t082647z` both tested `2a2c48535d6d39d2b37bf99998ce61212a1e0942` and exited 0 on separate fresh no-NIC overlays. Ubuntu 24.04.5 ran Linux 6.8.0-147, Engine 29.1.3 and Compose 2.40.3 on cgroup v2. The empty-bridge preflight verified the firewall controls in both families before each source startup. The active project used separate single-homed source and consumer containers, separate named volumes and no published ports.

**Source-only result.** Empty inventory returned nulls for slot, publication, feedback and all slot spans. Native SQL independently matched the sampled `probe.items` membership and inactive slot positions. Exact rows changed from `(1, 'seed')` to `(1, 'seed'), (2, 'inserted')`. At 0.170 s and 0.458 s on the same observer clock, publisher insert/write/flush moved from `0/19A90B0` to `0/19A9168`. Restart stayed at `0/19A9078` and confirmed flush at `0/19A90B0`. The insert-to-restart span grew from 56 to 240 bytes while allocated WAL stayed at 16,392 KiB. Safe WAL size moved from 140,865,360 to 140,865,176 bytes. Both slot-identity failures exited 1 with null SQL and disk data. The one-microsecond observation returned `deadline_exhausted` with the same nulls.

**Active result.** The publication contained only `probe.items`. One persistent `pgoutput` slot remained after initial copy. Every active sample attributed its sender by the slot PID, 267 in this run. The slot was `reserved` throughout. The verifier independently recomputed the three WAL spans from the hexadecimal LSNs and confirmed monotonic sample windows. Source and direct target reads matched at each hold. The target had no key 2 and no duplicate keys after delete.

| Hold | Exact source and target rows | Sample elapsed (s) | Publisher insert LSN | Restart LSN | Confirmed flush LSN | Insert to restart (bytes) |
| --- | --- | ---: | --- | --- | --- | ---: |
| Initial | `(1, 'seed')` | 0.173 | `0/19A9318` | `0/19A92A0` | `0/19A92D8` | 120 |
| Insert | `(1, 'seed'), (2, 'inserted')` | 6.932 | `0/19A9408` | `0/19A92A0` | `0/19A9318` | 360 |
| Update | `(1, 'updated'), (2, 'inserted')` | 11.894 | `0/19A9498` | `0/19A92A0` | `0/19A9318` | 504 |
| Delete | `(1, 'updated')` | 16.787 | `0/19A9518` | `0/19A93D0` | `0/19A9408` | 328 |

Sender write/flush/replay feedback matched sampled confirmed flush in these reads. The initial lag fields were null. At update parity, confirmed flush remained at its preceding value and PostgreSQL reported a replay lag of about 11.44 s. The target poll had already passed after 4 whole seconds on the reproducer's checkpoint timer. These different clocks and fields describe distinct boundaries. No transaction commit/end LSN was attributed. The independent target reads demonstrate visibility at the holds. Durable application and restart recovery remain open.

**Resources and teardown.** Active PGDATA peaked at 47,352 KiB in the sampler, with 16,392 KiB of allocated WAL and at least 3,668,908 KiB of free space. Source and consumer memory peaks at the active hold points were about 129 and 144 MiB, and OOM counters stayed zero. The 768 MiB source and 512 MiB consumer had zero container swap. Both PostgreSQL processes exited 0 in the active trial. Each passing run verified `after|0|0|t|t`, preserved the Phase 1 fixture ACL inventory and disposed of the owned volumes and bridge. On the active run, the post-group sampler also returned the empty baseline.

## Evidence artifacts

The ignored worktree directory `artifacts/EXP-014/` contains exported trial bundles and `SHA256SUMS`. From that directory, `sha256sum -c SHA256SUMS` verified all three exports. The bundles include exact sampled JSONL, redacted SQL and log evidence, source/target rows, resource counters, identity and teardown checks. The commands above reproduce them from the tested source revision.

| Archive | SHA-256 |
| --- | --- |
| `attempt-01-source.tar.gz` | `77112b9e515412898960068974c4930d94dbd8fc73e5c4653130326f628c955d` |
| `attempt-02-source.tar.gz` | `a2ff4beb2c172f926b849f996ceb22e4e59023546d2a0ab5c832a1ce6989863f` |
| `attempt-03-active.tar.gz` | `cca0082d34267d3d524b6a481bd0741c84cb11df8afa1aa53ea8810252c9ea26` |

## Interpretation

Each JSONL row carries `run_id`, `phase`, `checkpoint`, UTC finishing time, start and finish elapsed nanoseconds from the observer's monotonic clock, sample ordinal, publisher role, configured ownership and an error code or null. Only rows from the same observer instance share an elapsed-time origin. The SQL inventory validates the configured publication and slot independently. PG16's catalogs do not expose a persistent slot-to-publication binding. `postgresql.feedback` is attributed through the sampled active slot PID. A missing sender match remains null. The query omits connection details, unrelated sessions, row filter text and credentials.

**Verified documentation** (PG16, consulted 2026-11-26). [Slot view](https://www.postgresql.org/docs/16/view-pg-replication-slots.html) describes `restart_lsn` as the oldest WAL the slot may need and `confirmed_flush_lsn` as the consumer-confirmed receive position. `wal_status` can shift from reserved or extended to unreserved, and then lost when required WAL can no longer be retained. The Phase 1 profile's `max_slot_wal_keep_size=128MB` applies at checkpoint time. `safe_wal_size` can be null for a lost slot or an unlimited retention setting. Check both status and the actual allocation. [Replication settings](https://www.postgresql.org/docs/16/runtime-config-replication.html) · [PG16.16 release](https://www.postgresql.org/docs/16/release-16-16.html)

The [administration functions](https://www.postgresql.org/docs/16/functions-admin.html) provide the source insert, write and flush LSNs and signed `pg_wal_lsn_diff` byte spans. The first between-sample span is null. A changed checkpoint timeline or postmaster start also yields null. Spans describe cluster-wide WAL ranges, including unrelated records. Disk counters report allocated KiB and filesystem availability. These can diverge from spans due to WAL segment rounding, preallocation and recycling.

The [WAL sender statistics](https://www.postgresql.org/docs/16/monitoring-stats.html#MONITORING-PG-STAT-REPLICATION-VIEW) describe reported feedback and lag for recent WAL, and allow null lag during idle periods or when tracking data is unavailable. Write, flush and replay fields describe feedback reported over the protocol. Durable DuckLake application requires separate persistence evidence. Query visibility requires an independent exact target read. Commit-to-visibility latency requires attributable timed checkpoints and is bounded by the observation cadence. This SQL observer leaves `commit_lsn` and `end_lsn` null.

## Limitations / confounders

Source SQL and disk captures have distinct instants within one observation window. Slots and WAL senders can change while sampling. An active slot may have no matching sender row during a transition. A source crash can rewind slot positions. The sampler rejects extra slots, so take identity-checked samples at steady-state hold points; temporary-slot lifecycle evidence belongs to ticket 2.2. An empty publication and slot baseline represents catalog absence. No sender inventory from outside the expected slot is included. The outer deadline covers Docker inspection and both captures. SQL and disk commands also have in-container limits. A disk threshold emits the measured values and an error for the operator to act on.

## Follow-up action

R04, R05 and R16 remain **OPEN** at their full acceptance conditions. Preserve independent publisher observations for the checkpoint, interruption and walkthrough experiments. Ticket 2.9 owns reconciliation of the shared research register. [Phase 2 ownership and runtime plan](../../backlog/phase-2.md#parallel-development-and-runtime-conventions)
