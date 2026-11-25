# Published Phase 1 tickets — Operational Source Simulator

**Status:** Approved and published under [0.6 (#11)](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/11). See the [Phase 1 milestone](https://github.com/TiaanViviers/cdc-lakehouse-lab/milestone/2), [ticket registry](tickets.yaml) and [project board](https://github.com/users/TiaanViviers/projects/3).

**Phase outcome:** A disposable, isolated PostgreSQL 16 source that a reviewer can reset, drive through the bounded synthetic workload and verify using exact SQL results. This covers F01 and the source portion of F15 in the [PoC specification](../docs/poc-specification.md). Phase 1 configures and inspects source WAL parameters. Publication/slot creation, replication credentials, DuckPipe, lake storage and all other services are outside scope. The source SQL aggregate is a fixture oracle for later use.

**Implementation baseline:** [Local runtime design](../docs/local-runtime-design.md), [compatibility evidence](../docs/compatibility-matrix.md), [fixture v1 / seed 42](../docs/synthetic-workload.md), [verification protocol](../docs/verification-plan.md), [developer tooling](../docs/development-guide.md) and [ADR-001](../docs/decisions/ADR-001-phase-1-source-baseline.md). Use small PRs, `make check`, exact runtime pins and redacted commands and observations. Service tests use verified disposable Compose services only. Use the verification protocol's run IDs and the experiment template for runtime findings. The Phase 1 evidence contributes source-side results to the listed research questions. Their full downstream acceptance conditions remain open.

## Dependencies and parallel work

- **Initially placed in Ready:** 1.1 and 1.4. All other tickets start in Backlog. All tickets inherit the 0.6 handover dependency; immediate Phase 1 dependencies are below.
- **Critical path by dependency depth:** 1.1 → 1.2 → 1.3 → 1.5 → 1.6 or 1.7 → 1.8 → 1.9. S05 concurrency and S06 replay can be reviewed in parallel after 1.5. Each can exercise its own cases from S04. The integrated run joins them in S00–S06 order.
- **Independent workstream:** 1.4 uses only the fixture specification. It can be reviewed while 1.1–1.3 progress and feeds the first runner checks in 1.5. SQL migrations can be authored from the schema spec while 1.2 is in progress; their acceptance runs against the 1.2 runtime.

## 1.1 Verify local network isolation before source startup

**Phase:** 1 · **Type:** `feature`, `priority:high` · **Dependencies:** none within Phase 1 · **Research:** R01, R16 (source setup and inspection prerequisites).

**Objective and scope:** Provide a documented and repeatable host/VM preflight for the internal source network. Use local disposable probes and controlled test endpoints. Exclude production endpoints, public test endpoints, firewall automation for unrelated workloads and future service networks.

**Acceptance criteria**

- [ ] Record tested Engine, Compose, host OS, firewall backend and exact apply, verification and undo commands for the dedicated lab host or VM. Demonstrate that a missing or failed control prevents source bring-up under the documented procedure.
- [ ] On the intended internal network, a known peer succeeds via local service DNS. Probes to a controlled host-side service on the Docker bridge/gateway, controlled routed IPv4 destinations representing LAN/VPN paths, IPv6 destinations and delegated DNS names fail within declared deadlines. Use reachable local test targets or document disabled paths with configuration and independent observations. Confirm service ports are unpublished by default.
- [ ] Document the repeatable commands for checking each actual source-profile network in 1.2. Record per-probe output and relevant routes/rules. Run only against lab-controlled endpoints and restore disposable probe state.

**Validation and evidence:** Record topology, positive and negative controls, sanitized probe output (including timed failures) and startup-stop decision in the source runbook. Cite Docker guidance for the tested versions. If host isolation cannot be demonstrated, preserve the failing path and leave 1.2 runtime testing blocked.

## 1.2 Bring up bounded PostgreSQL source profile

**Phase:** 1 · **Type:** `feature`, `priority:high` · **Dependencies:** 1.1 · **Research:** R01, R04, R05 (publisher baseline only).

**Objective and scope:** Start a stock pinned PG16 service with authenticated checks, a project-scoped volume and bounded WAL settings. Use the Phase 0 PG16.16 Bookworm candidate and recorded digest, or document a reviewed pin change. Exclude workload DDL, generator, publication, slots and a consumer.

**Acceptance criteria**

- [ ] Validate resolved Compose config and repeat the 1.1 probes on every actual source-profile network before starting its workloads. Run PostgreSQL with unpublished host ports, an authenticated readiness check and named persistence. From the intended source-client network, demonstrate successful TCP authentication with valid credentials and rejection with invalid credentials. Record the applicable HBA rule and the client network. A clean stop/start using the same volume preserves a disposable sentinel value.
- [ ] Enforce the proposed source cap of 768 MiB and 1 CPU or record a reviewed change. Document finite connection, logging, local disk and WAL stop thresholds. Verify engine limits and record actual CPU, memory and disk observations.
- [ ] Query effective settings for `wal_level=logical`, finite positive slot/sender counts and finite `max_slot_wal_keep_size`. Confirm zero user publications and replication slots on a fresh source. Document the checkpoint behavior of the retention setting and record physical WAL disk usage separately.

**Validation and evidence:** Save redacted Compose config, image digest/platform and PostgreSQL version, authenticated SQL/log excerpts, resource and volume inspection and restart results. Provide reproducible start/inspect/stop commands and local secret-file guidance.

## 1.3 Apply the source schema and guard fixture cleanup

**Phase:** 1 · **Type:** `feature`, `priority:high` · **Dependencies:** 1.2 · **Research:** R02, R03, R13 (source prerequisites).

**Objective and scope:** Ship versioned SQL bootstrap and fixture cleanup for the four v1 business tables and a separate fixture-receipt table. Define the receipt key and payload identity contract consumed by 1.5 and 1.7. S00 data and the user-facing reset command belong to 1.5. Exclude replication setup and future operational write-back receipts.

**Acceptance criteria**

- [ ] Bootstrap succeeds on a clean volume and a repeat bootstrap preserves data and schema. Inspect constraints and types, including positive IDs/quantities, nonnegative cents, status values, PKs, natural-key uniqueness, restricted FKs and UTC-capable timestamps as specified.
- [ ] Prove invalid FK, duplicate reference, restricted parent delete and representative invalid domain values fail with the expected SQLSTATE and leave the complete committed rows and receipts intact.
- [ ] The fixture writer is non-admin with only scoped fixture/receipt access. Read-only inspection can read evidence and rejects mutation. Guard cleanup with explicit reset intent plus positive disposable target identification. Verify wrong/missing identity refuses before mutation using disposable targets only.
- [ ] Cleanup orders child deletions before parents, clears receipts and can participate in the same transaction as S00. A forced failure rolls it back so original data and receipts remain intact.

**Validation and evidence:** Save schema/catalog and grant queries, migration and cleanup commands, before/after ordered data, negative SQL results and reset guard diagnostics. Document the shared receipt and cleanup interface for 1.5 and 1.7.

## 1.4 Build independent fixture expectations and comparison tests

**Phase:** 1 · **Type:** `feature` · **Dependencies:** none within Phase 1 · **Research:** R02, R03, R13 (source oracle).

**Objective and scope:** Encode the published exact S00–S06 expectations and reusable comparison checks independently of generator inputs, mutation code and live state. Exclude database setup, service-dependent checks and actual Gold materialisation.

**Acceptance criteria**

- [ ] Version small expected fixtures with complete keyed rows, normalized UTC timestamps and both customer report rows at every checkpoint. Preserve S03 deletion and S05/S06 equality, including timestamps. Review expected aggregates independently of generator SQL.
- [ ] Comparator reports duplicate keys before matching and distinguishes missing, extra and unequal values. Unit cases prove wrong values with equal row counts, altered timestamps, duplicates and deleted-key residue fail. A matching fixture succeeds.
- [ ] Provide an offline `make test-unit` target using `tests/unit/`, document its pinned toolchain and run it in the existing pull-request CI alongside the repository checks.

**Validation and evidence:** Record expectations against the specification, a hand calculation covering S02–S04 and S05/S06, example mismatch diagnostics, exact test commands and hosted CI result.

## 1.5 Run S00–S04 as deterministic source transactions

**Phase:** 1 · **Type:** `feature`, `priority:high` · **Dependencies:** 1.3, 1.4 · **Research:** R02, R03, R13 (source behavior), R25 (fixture receipt precursor).

**Objective and scope:** Deliver a bounded one-shot Python runner for the sequential scenarios and a guarded reset to S00. Define step selection, fixture identity, logging and transaction interfaces used by 1.6 and 1.7. Exclude concurrent S05, replay orchestration and downstream replication.

**Acceptance criteria**

- [ ] A pinned Python/driver toolchain runs fixture v1/seed 42 with fixed UTC times, explicit IDs, deterministic order and finite connection/statement deadlines. Invalid scenario/seed or invalid sequence fails clearly and leaves rows intact.
- [ ] Enforce the generator ceiling of 256 MiB and 0.5 CPU or record a reviewed alternative. Verify the effective limits through container and cgroup inspection and retain that output.
- [ ] Guarded reset clears business rows and receipts and restores exact S00. A repeat reset from S04 reproduces S00. A fault between cleanup and seeding leaves the prior state intact.
- [ ] Compare exact rows and report values independently after S00, S01, S02, S03 and S04. Confirm item 102 is present at S01 and absent at S03. Confirm item 101 retains `created_at` on update.
- [ ] From a second connection, observe none of order 30, item 301, payment 302 or the S04 receipt while the transaction is held open. After commit, observe all four. Under forced rollback observe none and compare every business table and receipt to S03.

**Validation and evidence:** Record pinned versions, commands, checkpoint output/diffs, bounded runner logs and the independent pre-commit, commit and rollback reads. A successful exit, elapsed time or LSN alone cannot establish atomicity.

## 1.6 Exercise ordered overlap in S05

**Phase:** 1 · **Type:** `feature` · **Dependencies:** 1.5 · **Research:** R03, R13 (source behavior).

**Objective and scope:** Implement S05 using two source connections and an explicit bounded barrier. Reuse the S00–S04 runner interface. Exclude load generation, conflicting writes and lake cutoff tests.

**Acceptance criteria**

- [ ] From S04, demonstrate two distinct transactions executing their disjoint writes before either commits. Require explicit barrier release and a successful A commit before B can commit.
- [ ] From an independent session with fresh snapshots, record S04 while both are open, the A-only intermediate state while B is held open, and exact S05 after B commits. Check both tables' expected values and fixed T05 timestamps.
- [ ] An injected barrier timeout before commit leaves S04 intact, closes both connections and fails within a declared deadline. A failure after A commits reports partial S05 and preserves the observable A-only state, with a documented disposable reset/replay recovery.

**Validation and evidence:** Capture two backend/transaction identities, barrier and commit trace, canonical A-only and S05 SQL results, timeout and partial-commit diagnostics. Repeat from a fresh S04 and compare logical rows.

## 1.7 Prove replay after an ambiguous S04 outcome

**Phase:** 1 · **Type:** `feature` · **Dependencies:** 1.5 · **Research:** R03, R25 (source fixture rehearsal).

**Objective and scope:** Implement S06 as a replay of S04's original payload and key, using a durable receipt to reconcile ambiguous commits. Exclude Phase 6 request state, batches and write-back.

**Acceptance criteria**

- [ ] When S04 already committed, replay from a fresh runner returns the committed result, leaves its single receipt unchanged, and creates no S06 receipt or mutations. A mismatched payload using the same key is rejected with unchanged state.
- [ ] Reproduce both interruption before commit and runner loss after database commit but before acknowledgement. Reconcile from a new connection and retry the original input within a bounded budget. The first case applies once on retry; the second returns the prior committed result without mutation. Preserve a failure/unknown outcome when reconciliation is unavailable.
- [ ] Overlapping delivery of the same S04 key has one set of effects and one receipt. Use a bounded synchronization test and source-side protection. Check all business rows, timestamps and receipt values after each variant. The full S05→S06 ordered check is part of 1.8.

**Validation and evidence:** Record reproducible failure points, trace attempt IDs distinct from the S04 receipt key, and preserve ordered before/after query results and receipt values. Do not use unique-constraint failures alone as proof of successful replay.

## 1.8 Verify and document the complete source gate

**Phase:** 1 · **Type:** `research` · **Dependencies:** 1.6, 1.7 (transitively 1.1–1.5) · **Research:** R02, R03, R04, R05, R13, R16, R25 (source evidence).

**Objective and scope:** Test that a reviewer can reproduce and inspect the complete source workload and failures within declared limits. Reuse existing checks and ship the explicit source integration entry point. Exclude CDC, downstream integrations, browser tooling deployment and performance claims.

**Acceptance criteria**

- [ ] Document exact setup, `make test-integration` entry point under `tests/integration/`, run/inspect/stop and guarded reset commands. Integration checks run only on a verified disposable source. Keep service-free CI checks usable without Docker.
- [ ] From a clean isolated source run S00–S06 in order, comparing all keyed rows, duplicates, timestamps and both customers' exact aggregates at every checkpoint. Require exact S05/S06 equality, one unchanged S04 receipt and no S06 receipt. Reset after completion and compare to S00, then rerun the complete suite.
- [ ] Reproduce rollback, constraint failures, S05 ordered overlap/timeout and S04 ambiguous-outcome recovery. Show SQL results, source settings, empty slot/publication baseline, labeled source WAL samples and observed resource usage against predeclared limits. Provide a read-only `psql` walkthrough for S04 and receipt inspection.
- [ ] Record observed checks, failures and limitations in an experiment report using the template. Link the results in the research register and keep downstream acceptance conditions open. Mark the source gate unmet if a required result fails or remains unverified.

**Validation and evidence:** Publish redacted commands, exact versions and pin/digest, run IDs, row/aggregate diffs, source logs/settings, resource measurements and failure/recovery results. A reviewer should be able to repeat the experiment from the recorded commit.

## 1.9 Review Phase 1 findings and hand over to Phase 2

**Phase:** 1 · **Type:** `docs` · **Dependencies:** 1.1–1.8 and any other Phase 1 work added later · **Research:** R01–R05, R13, R16, R25.

**Objective and scope:** Complete the mandatory last Phase 1 ticket. Review the actual source baseline and seek approval for Phase 2 planning and publication. Exclude experimental DuckPipe implementation within the handover and tickets for phases beyond Phase 2.

**Acceptance criteria**

- [ ] Review the 1.8 gate and all Phase 1 PRs and experiments. Link exact source version, configuration, known committed fixture checkpoint, commands and inspection evidence and identify blockers to remote CDC. Record a material unmet source requirement before considering transition.
- [ ] Reconcile architecture, ADRs, roadmap and research status against observed source results. Record operational limits and unresolved connector, publication and slot questions without promoting hypotheses.
- [ ] Review and approve a Phase 2-only backlog against the findings, reserve unused IDs, and after explicit human approval publish the next milestone and issues on the same board with correct dependencies and statuses.
- [ ] Verify all other Phase 1 work is complete and Phase 2 publication is correct before closing the Phase 1 milestone and marking this issue Done last. Record the actual closing sequence.

**Validation and evidence:** Closeout report, research and ADR changes, source experiment links, approval record, verified milestone/issue/registry/board links and final state.
