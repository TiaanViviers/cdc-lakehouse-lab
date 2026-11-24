# Vision and research boundaries

## Problem

Operational PostgreSQL supports transactional writes. Analytics, reporting and ML need robust derived datasets without repeatedly scanning operational tables. The research question is whether a WAL-based ingestion path feeding a shared lakehouse can act as a reusable analytical foundation with independent compute and downstream consumers.

## Intended long-term hypothesis

1. **Capture once:** a remote CDC consumer follows PostgreSQL WAL and maintains source-aligned Bronze data.
2. **Shared lake:** DuckLake metadata lives in PostgreSQL; Parquet data lives in S3-compatible object storage.
3. **Transform independently:** DuckDB executes SQL in worker processes, with Windmill Flows/Pipelines potentially managing dependencies, schedules and materialisation.
4. **Serve independently:** clients read Gold via an appropriate query service or DuckDB clients; query-serving technology is a separate future decision.
5. **Potential future operational work:** durable asynchronous requests and controlled idempotent write-back to an authoritative transactional store, *not* reverse DuckPipe replication.

These are architectural hypotheses, not product commitments. A DuckLake current-state replica may not preserve every source change event. CDC consistency and historical guarantees must be established experimentally.

## Non-goals for the initial PoC

- Migration of any existing corporate SSIS/warehouse application.
- Real customer data, real infrastructure, production credentials, actual business logic.
- Dedicated SQL query service, Redshift, BI concurrency benchmarking or a production HA cluster.
- Voucher generation, request database, SQS, operational write-back or bidirectional replication.
- Claiming a production-ready architecture from local correctness tests.
- Assuming that one logical lake implies a single operational source of truth.

## Desired outcomes

A public, generic reproducible lab; small deterministic business-event simulator; independently observable CDC and snapshots; source-to-Gold correctness tests; real compatibility findings; fault-injection reports; a measured path for evaluating cloud deployment.

## Research vs implementation

This project deliberately records failed trials and limitations. A well-understood incompatibility is more valuable than a hidden workaround. The goal is learning and evidence, not showcasing a predetermined product stack.
