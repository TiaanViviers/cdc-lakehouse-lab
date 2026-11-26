# CDC Lakehouse Lab

A reproducible data-engineering research environment exploring PostgreSQL WAL-based change data capture, DuckPipe, DuckLake, DuckDB, Windmill, SQL query serving, asynchronous operations and end-to-end observability.

> **Status (2026-11-26).** The Phase 1 technical source gate passed on isolated PostgreSQL 16.16 with exact synthetic fixture and fault evidence. The approved Phase 2 backlog is published. Remote DuckPipe compatibility awaits its first runtime experiment. The full reference topology remains the research target. See the [Phase 1 closeout](docs/phase-1-closeout.md).

## What we are building

A staged Docker-based data platform laboratory with **two distinct paths**:

1. **Analytical ingestion and serving:** A synthetic PostgreSQL operational database produces committed changes. A remote DuckPipe consumer maintains DuckLake Bronze. DuckDB on Windmill workers transforms Bronze → Silver → multiple Gold datasets. A separate PostgreSQL-compatible SQL serving process reads Gold using **both** the DuckLake catalog and S3-backed Parquet. Trusted independent DuckDB clients provide a correctness baseline.
2. **Asynchronous operational processing:** An independent request API and durable PostgreSQL request store accept synthetic jobs; Windmill operational workers prepare results (optionally using analytical Gold data) and store large batches as **ordinary S3 objects in a separate bucket**. A controlled write-back service validates and idempotently commits approved batches to the source PostgreSQL, which remains operationally authoritative. Source CDC then reflects committed changes back to Bronze.

See [editable draw.io architecture](docs/Data_System.drawio) and the [annotated architecture spec](docs/architecture.md). The drawing is a **logical AWS/EC2 candidate topology**; the first implementation uses isolated Docker services on one host.

## Work in stages

| Phase | Outcome |
| --- | --- |
| 0 | Specifications, compatible-version research, repository foundations |
| 1 | Synthetic source PostgreSQL and deterministic event generator |
| 2 | Remote DuckPipe WAL ingestion and correctness checks |
| 3 | S3-compatible DuckLake data, metadata catalog and independent DuckDB reads |
| 4 | Windmill runtime, Flows/Pipelines, Bronze → Silver → Gold |
| 5 | Dedicated logical SQL query service for Gold and reporting-client tests |
| 6 | Asynchronous request DB, S3 batch artifacts and idempotent operational write-back |
| 7 | Unified human-facing observability and guided demonstrations |
| 8 | Cross-system fault injection, consistency, scaling and recovery findings |

Every phase has its own exit gate, and **basic inspection is required from phase 1**. See [roadmap](docs/roadmap.md).

## Read before coding

- [Vision and boundaries](docs/vision.md)
- [Architecture and environment placement](docs/architecture.md)
- [Full PoC specification](docs/poc-specification.md)
- [Query-serving research contract](docs/query-serving.md)
- [Asynchronous operational processing contract](docs/async-processing.md)
- [Research questions](docs/research-questions.md)
- [Component compatibility and candidate versions](docs/compatibility-matrix.md)
- [Local runtime design](docs/local-runtime-design.md)
- [Phase 0 closeout and approval gate](docs/phase-0-closeout.md)
- [Phase 1 closeout and Phase 2 handover](docs/phase-1-closeout.md)
- [Development guide](docs/development-guide.md)
- [Roadmap and dependencies](docs/roadmap.md)
- [Ticket naming / issue numbering](docs/issue-conventions.md)
- [GitHub project workflow](docs/project-management.md)
- [Agent rules](AGENTS.md)

## Developer checks

Run `make help` and `make check` from the repository root with Git and GNU Make. The checks cover changed-line whitespace, ignored and tracked paths, and environment placeholders. Run `make test-unit` with CPython 3.12.3 for the offline fixture oracle checks. See the [development guide](docs/development-guide.md#repository-validation) for the reproducible commands and results.

## Run the source profile

Use the [PostgreSQL source profile runbook](docs/source-profile.md) to stage PostgreSQL 16.16 and start it through the isolation gate in a dedicated VM.

## GitHub issues

Ticket IDs use **`phase.sequence`**, for example **`1.12 Implement Python generator`**. This is a project ticket ID in the *title*, not the GitHub-generated issue number (e.g. `#34`). Allocate per-phase sequence values through the backlog registry; never silently renumber existing tickets. Do not create actual implementation issues until backlog review.

## Research principles

- Source of operational truth stays in PostgreSQL; DuckLake is the canonical **analytical** copy, not a second authoritative voucher ledger.
- DuckPipe is one-way CDC; **write-back is a separate controlled business operation**, not reverse CDC.
- Metadata PostgreSQL, query-serving PostgreSQL, Windmill state PostgreSQL, and operational request PostgreSQL are **distinct roles**. Their physical placement can be consolidated during the lab.
- S3-compatible storage is not a compute engine; the DuckLake data bucket and the operational batch bucket have separate data contracts.
- Managerial approval authorises investigating the design, **not** a claim that integration, RDS support, reliability or performance is verified.
- Use synthetic, generic data and no corporate/client identifiers, credentials or production access. This repository is public; check applicable IP/employment rules before distributing further work.

## References

[PostgreSQL logical replication](https://www.postgresql.org/docs/16/logical-replication.html) · [pg_duckpipe](https://github.com/relytcloud/pg_duckpipe) · [pg_ducklake](https://github.com/relytcloud/pg_ducklake) · [DuckLake](https://ducklake.select/docs/stable/) · [Windmill Pipelines](https://www.windmill.dev/docs/core_concepts/pipelines)
