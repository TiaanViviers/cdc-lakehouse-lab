# Research question register

Status vocabulary: **OPEN**, **DOC-VERIFIED**, **EXPERIMENT-VERIFIED**, **BLOCKED**, **DISPROVEN**. All questions below start **OPEN** until independently supported; examples of official features do not prove this exact deployment.

Each experiment must report setup, version, hypothesis, procedure, expected result, *actual* output, artifacts, conclusion and remaining uncertainty. Use [the experiment template](experiments/TEMPLATE.md).

## Phase 0 evidence and status

Ticket 0.1 documented remote-source registration (R01), the catalog and object-store interfaces (R06–R07, R09), worker and Pipeline features (R10–R11), and remote catalog FDW support (R17). R22 has pinned candidate request-store prerequisites. All eight lab questions remain **OPEN** at their stated acceptance conditions. The first remote CDC check is stock PG16 to the digest-pinned DuckPipe PG18 image. A catalog-format mismatch is expected between that image's source dependency and the newest worker and serving candidates. Verify the actual catalog before attaching downstream clients. See the [compatibility matrix](compatibility-matrix.md) and [source and registry evidence](experiments/EXP-001-component-compatibility.md).

Ticket 0.2 specifies proposed local boundaries and validation for R07 and R15 in the [local runtime design](local-runtime-design.md). Both remain **OPEN**: neither S3 client behavior nor the metadata, Parquet and compute paths have been observed in the lab.

[Phase 0 closeout](phase-0-closeout.md) confirms that the fixture (R02, R03, R13) and verification protocol are specified. Phase 1 can add source-side observations of commits, overlap, replay and inspectability, and record effective WAL configuration. The downstream claims in R01–R05, R13, R16 and R25 require evidence beyond the source. **All R01–R28 remain OPEN at their full acceptance conditions.** Record partial evidence with the relevant question before changing its status.

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

## Research priorities

Ticket 0.4 specifies planned checks for R04, R05, R13, R16, R21 and R25 in the [verification protocol](verification-plan.md#research-traceability). All six remain **OPEN**. Use the protocol to record separate observations of WAL acknowledgement, snapshot parity, job execution and source commitment.

First gate: R01–R05. Then R06–R09. Windmill integration R10–R12 only after independent lake access. Later R13–R16; reporting R17–R21 follows Gold readiness; operational R22–R28 follows worker/source foundations. Findings may force a change of stack; write an ADR rather than hiding it.

## Explicit hypotheses

- **H1:** DuckPipe can consume a logically replicated PG16 source remotely and maintain current-state DuckLake tables.
- **H2:** Its resulting catalog/storage can be read by independent DuckDB clients.
- **H3:** A Windmill DuckDB worker can use the **same** lake for downstream materialisation without conflicting with DuckPipe.
- **H4:** A robust coordinator can define a source-data cutoff and publish internally consistent downstream assets.
- **H5:** Multi-stage execution and CDC recovery remain inspectable by a newcomer without relying solely on raw container logs.
- **H6:** A logically separate `pg_ducklake` reporting server can read the remote DuckLake catalog and S3 Gold through ordinary PostgreSQL clients with manageable latency/isolation.
- **H7:** A durable request PostgreSQL and separate S3 artifact bucket can support delayed, idempotent source write-back without maintaining a bidirectionally replicated operational database.

These are hypotheses, not results.

R01 and R16 remain **OPEN**. The [source preflight](experiments/EXP-002-source-isolation.md) blocked startup on the bare workstation and passed on the dedicated VM with verified guest rules. Withholding one IPv6 forwarding rule blocked the startup sentinel. The actual source-profile networks require a fresh gate in 1.2.
