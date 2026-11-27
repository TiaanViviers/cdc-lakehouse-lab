# Research question register

Status vocabulary: **OPEN**, **DOC-VERIFIED**, **EXPERIMENT-VERIFIED**, **BLOCKED**, **DISPROVEN**. All questions below start **OPEN** until independently supported; examples of official features do not prove this exact deployment.

Each experiment must report setup, version, hypothesis, procedure, expected result, *actual* output, artifacts, conclusion and remaining uncertainty. Use [the experiment template](experiments/TEMPLATE.md).

## Phase 0 evidence and status

Ticket 0.1 documented remote-source registration (R01), the catalog and object-store interfaces (R06–R07, R09), worker and Pipeline features (R10–R11), and remote catalog FDW support (R17). R22 has pinned candidate request-store prerequisites. All eight lab questions remain **OPEN** at their stated acceptance conditions. The first remote CDC check is stock PG16 to the digest-pinned DuckPipe PG18 image. A catalog-format mismatch is expected between that image's source dependency and the newest worker and serving candidates. Verify the actual catalog before attaching downstream clients. See the [compatibility matrix](compatibility-matrix.md) and [source and registry evidence](experiments/EXP-001-component-compatibility.md).

Ticket 0.2 specifies proposed local boundaries and validation for R07 and R15 in the [local runtime design](local-runtime-design.md). Both remain **OPEN**: neither S3 client behavior nor the metadata, Parquet and compute paths have been observed in the lab.

[Phase 0 closeout](phase-0-closeout.md) specifies the fixture and verification protocol. **All R01–R28 remain OPEN at their full acceptance conditions after the Phase 1 closeout.** Record partial evidence with the relevant question before changing its status.

| ID | Question | Experiment / evidence | Acceptance condition |
| --- | --- | --- | --- |
| R01 | Does remote DuckPipe successfully capture a PG16 source? | Reproducible container setup and documented replication handshake | Source changes replicated without installing DuckPipe on source |
| R02 | How is initial snapshot taken? | Seed rows before registration; observe state and snapshot result | Row-level source/Bronze parity after snapshot |
| R03 | How are commits, updates and deletes applied? | Controlled multi-transaction fixture | Correct final rows including deleted IDs |
| R04 | How do source slots and DuckPipe LSNs progress? | Capture `pg_replication_slots`, DuckPipe status across commits | Explain observed checkpoint/ack relationships from evidence |
| R05 | What happens during CDC interruption and catch-up? | Stop consumer, generate events, restart | Recovery demonstrated; lag/WAL retention measured |
| R06 | How does object storage interact with catalog? | List Parquet files, inspect metadata/snapshots after writes | Independent client sees consistent table |
| R07 | Does configured S3-compatible backend work with each component? | Verify credentials, paths, multipart/read/write behavior | Files persist; external reads succeed |
| R08 | Can catalog and DuckPipe host be separated? | Compare colocated vs remote supported configuration | Supported integration observed or limitation documented |
| R09 | Can an independent DuckDB reader attach to DuckPipe-created tables? | Attach exact shared catalog, query values | Correct independent read |
| R10 | Can Windmill read the exact same DuckLake? | Worker job using shared catalog | Correct read without copying to another lake |
| R11 | Can Windmill Pipelines materialise safely into shared catalog? | Controlled Bronze → Silver → Gold, rerun, snapshots | Outputs correct; writer conflicts/limitations recorded |
| R12 | How are dependencies detected and triggered? | Change upstream asset externally and via Windmill | Document which downstream steps actually trigger |
| R13 | Can a consistent multi-table cutoff be established? | Cross-table transaction + delayed consumer scenario | Consistency contract demonstrated or unsolved risk stated |
| R14 | What happens during transformation failure/retry? | Controlled worker termination and rerun | No silently corrupt final Gold state |
| R15 | What is the role of catalog, S3 and worker compute? | SQL profiling and resource metrics | Trace metadata and Parquet read paths |
| R16 | Is human observation sufficient? | Reproduce an event across UIs, logs and queries | Documented walkthrough identifies each stage |
| R17 | Can a separate PostgreSQL-compatible SQL endpoint query remote DuckLake Gold? | Query Gold from `psql` via a `pg_ducklake` candidate with external catalog + S3 | Exact results match independent DuckDB |
| R18 | Which SQL dialect/driver features are supported by the reporting interface? | Real PostgreSQL driver queries, error handling, parameterized queries | Supported/unsupported client behaviours recorded |
| R19 | Can query-serving isolation enforce least-privilege read-only access? | Separate SQL roles and scoped S3/catalog credentials | Gold readable, protected schemas/writes rejected |
| R20 | How does serving behave with multiple clients? | Reproducible concurrent queries, p50/p95 + CPU/RAM observations | Correctness and measured capacity, no implied SLA |
| R21 | What happens when reporting, catalog or S3 services fail? | Stop individual service, query/restart | Failure and recovery semantics documented |
| R22 | Can client requests be accepted durably while the source is down? | Source stopped, submit synthetic job, inspect request DB | Request retained with unique ID, no false completion |
| R23 | When should an async worker read Gold, and what if it is stale? | Self-contained vs versioned Gold input and commit-time source validation | Reproducible correctness/rejection rules |
| R24 | Can prepared batches be retained independently in S3? | Write immutable CSV/Parquet object + checksum + request DB reference | Object/references validated, retries safe |
| R25 | Can write-back produce idempotent source-side effects? | Duplicate delivery and crash-after-source-commit test | No duplicate effects; durable source receipts |
| R26 | How do operational jobs recover from worker, request DB, or S3 failures? | Inject failures at acceptance, generation, artifact and commit | Status reconciliation and replay policy documented |
| R27 | Does separate request processing isolate preparation from source workload? | Source unavailable/slow scenarios, bounded source writes | Prep continues where inputs allow; commits wait |
| R28 | Does write-back flow back through one-way CDC without a feedback loop? | Commit test batch, inspect Bronze and source counts | Correct final state, no reverse replication / recursion |

## Phase 1 source evidence

[Phase 1 closeout](phase-1-closeout.md) verifies the technical source gate. The bare-workstation preflight blocked startup and the disconnected guest passed on the actual bridge after both firewall rule families were installed. Stock PostgreSQL 16.16 exposed bounded logical WAL and an empty publication and slot baseline. A scoped peer authenticated via SCRAM and a sentinel survived source container recreation. This is source evidence for R01, R04, R05 and R16. [EXP-002](experiments/EXP-002-source-isolation.md) · [EXP-004](experiments/EXP-004-source-profile.md)

[Ticket 1.4](experiments/EXP-003-fixture-oracle.md) validated the offline expected rows, both customer aggregates and mismatch detection for R02, R03 and R13. The three questions remain **OPEN**. Initial snapshot parity, applied changes and cross-table visibility still require observations of the source and downstream systems.

[Ticket 1.3](experiments/EXP-005-source-schema.md) verified source schema and grants, preservation on repeat bootstrap, and guarded cleanup and rollback on PostgreSQL 16.16 in the isolated ticket 1.2 environment. R02, R03 and R13 remain **OPEN** pending workload execution and downstream comparisons.

[Ticket 1.5](experiments/EXP-006-source-runner.md) exercises S00–S04 against the independent row and report oracle. This provides a verified S00 source baseline for R02 and source-side evidence of inserts, updates and deletion for R03. A separate reader observed the S04 business rows and receipt together after commit and exact S03 before commit and after forced rollback (R13). The same receipt persisted across a clean source restart (R25). All four remain **OPEN** at their full acceptance conditions. The next measurements include downstream parity and cutoff behavior and ambiguous-outcome replay.

Ticket 1.6 verified exact S04, A-only and S05 visibility from an independent source session while two disjoint PostgreSQL transactions followed a bounded A-before-B commit schedule. A pre-commit timeout preserved S04, and a fault after A committed left exact A-only state. Reset and replay from fresh S04 reproduced S05. R03 and R13 remain **OPEN** at their downstream acceptance conditions. [S05 experiment](experiments/EXP-016-source-overlap.md)

[Ticket 1.7](experiments/EXP-008-source-replay.md) verified source-side S04 receipt replay, including runner loss before and after commit, overlapping delivery, payload mismatch and an unavailable receipt lookup. All ordered row, timestamp, report and receipt comparisons matched the independent expectations. R03 and R25 remain **OPEN** at full scope. Phase 6 owns operational write-back evidence.

[Ticket 1.8](experiments/EXP-009-phase-1-source-gate.md) reproduced the complete technical source gate on three fresh isolated PostgreSQL volumes, including a repeat after the preceding guests shut down. R02 gains an exact seeded source baseline. R03 gains independent keyed parity through inserts, updates, deletion, overlap and replay. R04 and R05 gain bounded WAL settings, labeled publisher observations and a confirmed empty replication baseline. R13 gains S04 atomic visibility and the ordered S05 intermediate states. R16 gains a reproducible read-only S04 and receipt walkthrough. R25 gains repeated single-effect fixture replay and explicit unknown outcomes. **All seven research questions remain OPEN** at their full acceptance conditions, including downstream snapshot parity, slot acknowledgement and retention, consumer recovery, lake cutoffs, end-to-end inspection and operational write-back.

## Phase 2 source and artifact review

[EXP-010](experiments/EXP-010-phase-2-candidate-review.md) confirms the pinned transport requests PG16-supported pgoutput protocol 1, and that remote onboarding creates and changes source objects. The upstream loopback coverage skips snapshot and update/delete. R01–R05 remain **OPEN** for TCP/SCRAM capture, snapshot/WAL correctness, applied DML, feedback semantics and bounded restart. R13 remains **OPEN** for actual multi-table snapshots and apply visibility. A pinned initializer expects format 0.4, while actual format, durable local files, external catalog and reader compatibility were unverified for R06, R08 and R09 at planning. R16 remains open for the broader walkthrough, and R25 for operational write-back.

## Phase 2 evidence and status

[EXP-020](experiments/EXP-020-phase-2-cdc-gate.md) reconciles the independent publisher, connector and exact-row evidence. Scope each verification to the pinned stock PG16.16 publisher and separate PG18.4 DuckPipe consumer with local DuckLake.

| Question | Status | Evidence and remaining scope |
| --- | --- | --- |
| R01 | **EXPERIMENT-VERIFIED** | The scoped publisher and separate consumer replicated the fixed fixture over the isolated TCP bridge. Source preloads are empty. |
| R02 | **EXPERIMENT-VERIFIED** for held initial copy | Four serial initial copies and temporary slot release produced exact S00. A separate controlled COPY overlap previously produced exact S01. Three EXP-020 trials missed the S01 insert by the same deadline. Initial COPY with concurrent writes remains blocked at the tested boundary. |
| R03 | **EXPERIMENT-VERIFIED** for held post-copy checkpoints | The held source and Bronze checkpoints match the oracle through S05. Sampled and retained views exclude aborted changes in the tested schedules, and exact S03 excludes deleted item 102. The repeated COPY-overlap miss blocks claims that concurrent onboarding preserves all committed effects. Partial versions also disprove source-transaction atomicity in Bronze. |
| R04 | **EXPERIMENT-VERIFIED** | Feedback, restart span, apply and visibility are traceable separately. The sparse-table control explains the minimum-per-table stall. Operational mitigation of sustained WAL growth remains unresolved and blocks M2. |
| R05 | **EXPERIMENT-VERIFIED** within retained WAL | Graceful restart, preserved-volume replacement and a bounded consumer SIGKILL recovered exact current state on the original slot under their tested schedules. Crossing the retention cap rejected reconnect and required a new snapshot. Buffered-but-not-durable and host/publisher loss remain open. |
| R06 | **OPEN** | Local DuckLake 0.4 metadata and inline rows were observed. A scoped flush produced and verified local Parquet references. Shared object-store consistency remains unverified. |
| R08 | **OPEN** | Colocated catalog and local lake data persist on the consumer volume. Separation of the catalog from the writer remains unverified. |
| R09 | **OPEN** | Consumer-local embedded and PostgreSQL SQL reads verified the same Bronze lake. Independent DuckDB process attachment to that lake remains unverified. |
| R13 | **OPEN** | Explicit partial catalog versions disprove commit-atomic Bronze visibility. The first exact named version at a held, independently verified source checkpoint is usable while retained. Continuous-source cutoffs remain unverified. |
| R16 | **OPEN** | A read-only walkthrough traces an S04 source commit through publication, slot, sender, worker and direct Bronze rows. Downstream stages in the full walkthrough remain open. |

## Research priorities

Ticket 0.4 specifies planned checks for R04, R05, R13, R16, R21 and R25 in the [verification protocol](verification-plan.md#research-traceability). All six were **OPEN** at the Phase 0 checkpoint. Use the protocol to record separate observations of WAL acknowledgement, snapshot parity, job execution and source commitment.

Phase 2 starts with the remote compatibility probe (R01) and continues with snapshot, DML, feedback, recovery and visibility (R02–R05, R13, R16). Phase 3 tests catalog, S3 and independent lake access (R06–R09). Windmill integration follows independent lake access. Reporting follows Gold readiness, and the operational path follows worker and source foundations. Use reviewed evidence and an ADR if findings require a stack change.

## Explicit hypotheses

- **H1:** DuckPipe can consume a logically replicated PG16 source remotely and maintain current-state DuckLake tables.
- **H2:** Its resulting catalog/storage can be read by independent DuckDB clients.
- **H3:** A Windmill DuckDB worker can use the **same** lake for downstream materialisation without conflicting with DuckPipe.
- **H4:** A robust coordinator can define a source-data cutoff and publish internally consistent downstream assets.
- **H5:** Multi-stage execution and CDC recovery remain inspectable by a newcomer without relying solely on raw container logs.
- **H6:** A logically separate `pg_ducklake` reporting server can read the remote DuckLake catalog and S3 Gold through ordinary PostgreSQL clients with manageable latency/isolation.
- **H7:** A durable request PostgreSQL and separate S3 artifact bucket can support delayed, idempotent source write-back without maintaining a bidirectionally replicated operational database.

These are hypotheses, not results.
