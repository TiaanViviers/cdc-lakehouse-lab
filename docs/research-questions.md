# Research question register

Status vocabulary: **OPEN**, **DOC-VERIFIED**, **EXPERIMENT-VERIFIED**, **BLOCKED**, **DISPROVEN**. All questions below start **OPEN** until independently supported; examples of official features do not prove this exact deployment.

Each experiment must report setup, version, hypothesis, procedure, expected result, *actual* output, artifacts, conclusion and remaining uncertainty. Use [the experiment template](experiments/TEMPLATE.md).

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

## Research priorities

First gate: R01–R05. Then R06–R09. Windmill integration R10–R12 only after independent lake access. Later R13–R16. Findings may force a change of stack; write an ADR rather than hiding it.

## Explicit hypotheses

- **H1:** DuckPipe can consume a logically replicated PG16 source remotely and maintain current-state DuckLake tables.
- **H2:** Its resulting catalog/storage can be read by independent DuckDB clients.
- **H3:** A Windmill DuckDB worker can use the **same** lake for downstream materialisation without conflicting with DuckPipe.
- **H4:** A robust coordinator can define a source-data cutoff and publish internally consistent downstream assets.
- **H5:** Multi-stage execution and CDC recovery remain inspectable by a newcomer without relying solely on raw container logs.

These are hypotheses, not results.
