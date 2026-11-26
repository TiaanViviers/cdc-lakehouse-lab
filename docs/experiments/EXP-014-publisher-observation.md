# EXP-014 — Independent publisher replication and WAL observation

- **Date** 2026-11-26
- **Research question IDs** R04, R05, R16
- **Status** Offline checks passed. Source-only and active-consumer validation pending.
- **Operator** Ticket 2.4 ([issue #41](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/41))
- **Git branch** `feature/2.4-publisher-observation`, initially based on `d9de734`
- **Software / images** CPython 3.12.3 observed offline. Runtime target PostgreSQL and psql 16.16 on the pinned Bookworm image in [compose.source.yaml](../../compose.source.yaml). Record the actual client/server versions and image config ID in each runtime trial.

## Hypothesis

An independent source-local observer can identify the expected publication and slot, track publisher positions and attributable feedback, and report WAL retention and disk use within an explicit observation budget. The same interface can represent the absence of replication objects and an inactive slot.

## Preconditions

Run offline checks on the workstation. Schedule the disconnected VM with the maintainer after ticket 2.1 has priority. For the source-only run, use a unique project, bridge, source volume and credentials. Stage this checkout and the existing pinned source image, isolation probe and runner on read-only media. Follow the [source gate setup](../source-gate.md#set-up-a-fresh-disposable-source) and verify both firewall families, Compose and volume identity, healthy PG16.16 and the source limits before provisioning the synthetic fixture. For the active trial, use a new isolated environment or a shared controlled session agreed by the owners in advance, with the build and onboarding sequence accepted in [issue #38](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/38).

Record the owner, run ID, tested SHA, VM overlay, Compose/volume/bridge IDs, image IDs, resolved configuration, database and selected group/publication/slot in a fresh private `artifacts/EXP-014/<UTC-run-id>/`. Record the existing source cgroup, WAL settings and disk checks from the [source profile](../source-profile.md#verify-limits-and-storage). Use a runner only within the scheduled guest budget. Stop workload generation on sampler error, threshold breach, lost isolation or OOM. The experiment owner controls teardown.

**Decision.** Use the existing authorized disposable `source_admin` connection over source-local loopback and SCRAM, as in the Phase 1 source gate. The observer uses a read-only transaction with a restricted search path. Docker access and the admin role are privileged lab access. This experiment grants no new roles or privileges. Keep credentials in the guest-local secret file. Preserve only allow-listed client output and record generic error codes for failures.

## Procedure

1. Run `make check` and `make test-unit`. The publisher tests use synthetic responses with no Docker or PostgreSQL dependency.
2. In the verified guest, take ownership inputs from the recorded enrollment. Derive the full source container ID from the verified source Compose project. Independently record `SELECT system_identifier FROM pg_control_system()` during source enrollment and use that value for `system_id` below. Check the container and volume before doing any test DDL. From the repository root, with a fresh evidence directory `evidence` and your recorded `run_id`, set up the source-only invocation:

   ```bash
   base=(--project "$COMPOSE_PROJECT_NAME" --container "$source_id"
         --bridge "$SOURCE_INPUT_ID" --system-identifier "$system_id"
         --run-id "$run_id" --phase 2.4)
   observe() { python3 -m scripts.cdc.wal.observe "${base[@]}" "$@"; }
   observe --checkpoint empty >"$evidence/empty.jsonl"
   ```

3. On the fresh source-only clone, use the [Phase 1 runner](../source-runner.md) to run S00 and record `inspect S00`. With no consumer running, use the authorized lab administrator in a separate, bounded psql session to create a named publication for `fixture.order_items` and a persistent `pgoutput` slot. Use names derived from the per-run identifier. Record the exact SQL and initial slot positions. Creating a slot generates its own WAL boundary. Take the first inactive sample after setup, before fixture S01. Run S01 using the same run ID and verify exact `inspect S01`. Take the second inactive sample after that independent hold-point check.
4. Use a single `Observer` for paired measurements. In a Python driver, construct `Source(project, container, bridge, system_identifier, slot, publication, ("fixture.order_items",))` and `Observer(source, run_id, budget_seconds=120, max_samples=2)`. Call `sample("2.4", "S00")` and `sample("2.4", "S01")` at the two hold points. Append each result as one JSON line and stop on an error. Use the existing runner's process deadline and the declared overall run deadline for the fixture operations. For a static hold point, the CLI also supports consecutive samples.

   ```bash
   expected=(--slot "$slot" --publication "$publication" --member fixture.order_items)
   observe "${expected[@]}" --checkpoint inactive --samples 2 \
       --interval-seconds 0.5 --budget-seconds 15 >"$evidence/inactive.jsonl"
   if observe "${expected[@]}" --slot "$unused_slot" --checkpoint wrong-slot \
       >"$evidence/wrong-slot.jsonl"; then exit 1; fi
   if observe "${expected[@]}" --checkpoint deadline --budget-seconds 0.000001 \
       >"$evidence/deadline.jsonl"; then exit 1; fi
   ```

   Choose `unused_slot` as a valid, absent name distinct from the actual slot. On this source-only clone, also create a second disposable slot under the two-slot cap and repeat the correct-name invocation to verify rejection of an extra slot. Check exact slot names and inactivity with authorized SQL before dropping the test objects. Verify the empty replication baseline again and follow the [guarded stop and disposal](../source-gate.md#guarded-reset-and-stop).
5. After the 2.1 decision, repeat with the accepted consumer. Wait for temporary onboarding slots to clear before collecting telemetry with the exact persistent slot and expected publication members. Capture idle and post-commit samples on one clock while the accepted repro performs a bounded commit, pausing unrelated writes. Retain source and independent target reads at each hold point with the exact expected keys and values. Save the last passing pre-commit and first post-commit observations along with missing feedback or timeout evidence. If the selected build exposes attributable transaction LSNs, correlate them in the experiment record. Keep connector status and durable apply evidence in their owning experiment.

## Expected results

- Empty inventory has null slot, publication, feedback and slot-related spans, plus an empty membership array. Current source LSNs and disk counters are present.
- The inactive baseline identifies the exact logical `pgoutput` slot and `fixture.order_items` membership. It has `active: false`, null PID and null feedback. After S01, item 102 has the v1/42 fixture values, unrelated rows match the independent S01 oracle, and the slot's confirmed flush and restart positions remain unchanged with no consumer. The insertion position increases across the committed write and the insert-to-restart span grows. Disk allocation may stay unchanged.
- Independently recompute each populated slot span by converting the hexadecimal halves of the two LSNs to one integer each and subtracting. Compare same-history samples and check increasing monotonic observation boundaries. Use scoped source SQL to corroborate membership and slot state. In the active trial, verify the expected slot is active and any feedback PID matches that slot. Compare before/after feedback with the source commits and corroborate data visibility using exact target keys and values.
- The unexpected-name and extra-slot cases return `slot_identity` and null telemetry. An exhausted wall budget returns a trace row and nonzero status, with `deadline_exhausted` or `capture_timeout` depending on whether a command began.

## Actual observations

**Observed offline.** `python3 -m scripts.cdc.wal.observe --help` exposed the publisher invocation. `make test-unit` passed 32 tests, including eight publisher tests for empty/inactive samples, synthetic feedback, membership and slot identity, bounded attempts, deadline exhaustion, timeout redaction and an observation timeline with a backwards UTC clock. The inactive synthetic fixture retained null feedback and reported a 16-byte between-sample span. The mock deadline invoked no Docker command. A CLI smoke check with synthetic identities and `--budget-seconds 0.000001` exited 1 and emitted one JSONL row with `deadline_exhausted` and null SQL/disk data. `make check` passed.

**Open.** PG16.16 query execution, source-only before/after checks and live DuckPipe observations have no EXP-014 runtime evidence yet. Issue #38 was open when offline preparation began.

## Evidence artifacts

Capture JSONL, exact source/target correctness outputs, configuration and version evidence, filtered logs, cgroup counters and teardown results in the ignored per-run directory. Include a checksum manifest and a reviewer-accessible evidence location in the report for each runtime trial. Record the actual tested SHA after integrating current main and merged prerequisites.

## Interpretation

Each JSONL row carries `run_id`, `phase`, `checkpoint`, UTC finishing time, start and finish elapsed nanoseconds from the observer's monotonic clock, sample ordinal, publisher role, configured ownership and an error code or null. Only rows from the same observer instance share an elapsed-time origin. The SQL inventory validates the configured publication and slot independently. PG16's catalogs do not expose a persistent slot-to-publication binding. `postgresql.feedback` is attributed through the sampled active slot PID. A missing sender match remains null. The query omits connection details, unrelated sessions, row filter text and credentials.

**Verified documentation** (PG16, consulted 2026-11-26). [Slot view](https://www.postgresql.org/docs/16/view-pg-replication-slots.html) describes `restart_lsn` as the oldest WAL the slot may need and `confirmed_flush_lsn` as the consumer-confirmed receive position. `wal_status` can shift from reserved or extended to unreserved, and then lost when required WAL can no longer be retained. The Phase 1 profile's `max_slot_wal_keep_size=128MB` applies at checkpoint time. `safe_wal_size` can be null for a lost slot or an unlimited retention setting. Check both status and the actual allocation. [Replication settings](https://www.postgresql.org/docs/16/runtime-config-replication.html) · [PG16.16 release](https://www.postgresql.org/docs/16/release-16-16.html)

The [administration functions](https://www.postgresql.org/docs/16/functions-admin.html) provide the source insert, write and flush LSNs and signed `pg_wal_lsn_diff` byte spans. The first between-sample span is null. A changed checkpoint timeline or postmaster start also yields null. Spans describe cluster-wide WAL ranges, including unrelated records. Disk counters report allocated KiB and filesystem availability. These can diverge from spans due to WAL segment rounding, preallocation and recycling.

The [WAL sender statistics](https://www.postgresql.org/docs/16/monitoring-stats.html#MONITORING-PG-STAT-REPLICATION-VIEW) describe reported feedback and lag for recent WAL, and allow null lag during idle periods or when tracking data is unavailable. Write, flush and replay fields describe feedback reported over the protocol. Durable DuckLake application requires separate persistence evidence. Query visibility requires an independent exact target read. Commit-to-visibility latency requires attributable timed checkpoints and is bounded by the observation cadence. This SQL observer leaves `commit_lsn` and `end_lsn` null.

## Limitations / confounders

Source SQL and disk captures have distinct instants within one observation window. Slots and WAL senders can change while sampling. An active slot may have no matching sender row during a transition. A source crash can rewind slot positions. The sampler rejects extra slots, so take identity-checked samples at steady-state hold points; temporary-slot lifecycle evidence belongs to ticket 2.2. An empty publication and slot baseline represents catalog absence. No sender inventory from outside the expected slot is included. The outer deadline covers Docker inspection and both captures. SQL and disk commands also have in-container limits. A disk threshold emits the measured values and an error for the operator to act on.

## Follow-up action

R04, R05 and R16 remain **OPEN** at their full acceptance conditions. Preserve independent publisher observations for the checkpoint, interruption and walkthrough experiments. Ticket 2.9 owns reconciliation of the shared research register. [Phase 2 ownership and runtime plan](../../backlog/phase-2.md#parallel-development-and-runtime-conventions)
