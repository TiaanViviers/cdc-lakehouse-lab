# PoC specification — v0.1 (proposed)

## Purpose
Build a small, reproducible local CDC lakehouse that can be interrogated at each boundary, not a production-ready deployment. Every integration must be verified rather than assumed.

## Components in scope
1. PostgreSQL 16 simulator source (separate Docker service), logical WAL enabled.
2. Deterministic Python generator and fixtures for customers/orders/order_items/payments or another generic related schema; insert/update/delete and concurrent commits.
3. Compatible PostgreSQL DuckPipe/pg_ducklake host configured for **remote** source.
4. PostgreSQL-based DuckLake catalog and local S3-compatible Parquet storage, with observed file/object state.
5. Independent DuckDB catalog attachment and query validation.
6. Self-hosted Windmill server, internal PostgreSQL and at least one worker.
7. DuckDB SQL transformations Bronze → Silver → Gold; evaluate manual Flows against managed Pipelines.
8. Browser-based inspection and small, optional research dashboard.
9. Repeatable failure scenarios.

## Out of scope now
A second operational request/write-back database, separate reporting service, real AWS, large-scale throughput guarantees, historical CDC event store, product-specific business processes.

## Functional criteria
**F01 Source simulation:** seed produces repeatable related records and expected states; controlled insert, update, delete and transaction cases can be replayed.

**F02 CDC bootstrap:** demonstrate initial snapshot with correct dataset (primary keys and full row values compared, not counts only).

**F03 CDC streaming:** after subsequent committed mutations, eventual Bronze values match source across inserts/updates/deletes; record observed lag and replication status.

**F04 Lake durability/access:** prove catalog queries and Parquet object inspection; independent DuckDB process can query data without using the DuckPipe PostgreSQL SQL session.

**F05 Transformations:** DuckDB SQL produces cleaned Silver and at least two meaningful Gold outputs (e.g. daily revenue and customer features) with fixture-based expected results.

**F06 Windmill:** a Windmill job can read Bronze and produce a downstream table; compare conventional Flow sequencing with asset-based Pipeline dependencies, document actual behavior and limitations.

**F07 Inspection:** provide human-friendly entry points (SQL UI, object console, Windmill logs, Docker logs) and clear commands/links to understand state at every stage.

**F08 Failure tests:** stop CDC during source writes, restart, prove no lost/duplicated final table rows; interrupt/retry transformation and inspect resulting snapshots.

## Nonfunctional criteria
- Reproducible with documented Ubuntu + Docker Compose instructions; laptop-friendly baseline with low record counts and limited worker concurrency (16 GB RAM target).
- Health checks, isolated Docker network, persistent named volumes, explicit ports, deterministic seeds and pinned compatible image versions.
- Never store committed secrets, customer data or live connection details; include `.env.example`.
- Small automated correctness tests; explicit hypothesis, execution procedure and observed artifacts per research question.
- Test failures must not be hidden by switching stacks.

## Milestone gates

**M0 — Research foundation:** docs reviewed; verified upstream version matrix and image references; backlog approved.

**M1 — Source:** start one PostgreSQL source and generator; manually inspect records and slots.

**M2 — CDC:** remote DuckPipe reads WAL; snapshot and mutations validated (initially simplest supported storage configuration).

**M3 — Shared lake:** S3-compatible objects and catalog usable by independent DuckDB, including snapshot/metadata validation.

**M4 — Windmill:** worker reads Bronze and materialises Silver/Gold; explicit Flow first, Pipeline integration second.

**M5 — Observability/reliability:** dashboard and fault injection with documented outcomes.

**Do not call M2/M3/M4 complete based solely on green container health checks.**

## Data correctness principle
Use deterministic fixtures and row-level comparison with stable identifiers. Validate deleted records, related-table results and rerun behavior. A CDC LSN is an ingestion coordinate, not by itself a proof that a downstream Gold snapshot contains a consistent multi-table state.

## Research reporting
For each milestone: exact component versions, compose commands, known configs (secrets redacted), captured status, test results, duration/resource readings, observations, defects, and follow-up questions.

## Deferred architecture
Operational asynchronous requests may eventually use a durable request database, S3 batch artifacts, workers and idempotent write-back to an authoritative production-like store. It is **not** implemented in this PoC.
