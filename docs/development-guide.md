# Local development and engineering guidelines

## Host assumptions

Ubuntu/Linux Docker Engine + Docker Compose v2, Python 3, Git. Start with a laptop-sized configuration (~16 GB RAM). Use one Windmill worker initially and small fixtures; don't enable all services before prerequisites are validated.

## Proposed environment profiles

- `source`: PostgreSQL 16, generator, source SQL inspection.
- `cdc`: DuckPipe-compatible PostgreSQL image and extension configuration.
- `storage`: S3-compatible service with a browser object console.
- `windmill`: Windmill server, scheduler/queue/state PostgreSQL, single worker.
- `reporting`: logically independent PostgreSQL-compatible SQL serving process, catalog/S3 connectivity, synthetic SQL clients.
- `requests`: request API, independent request PostgreSQL, controlled write-back service.
- `batches`: separate S3-compatible operational bucket/namespace, storing prepared CSV/Parquet results.
- `observe`: optional pgAdmin or equivalent, custom diagnostics/dashboard.

These are **planned service groups**, not implemented commands. Compose file/images/ports must be proven and documented in implementation issues.

## Human-first debugging

1. Query source tables and `pg_replication_slots` on the source.
2. Inspect DuckPipe's version-specific status API or SQL views on CDC host.
3. Inspect catalog metadata, snapshots and Parquet objects through independent interfaces.
4. Query Bronze from independent DuckDB.
5. Open Windmill's run view: inspect input, worker logs, pipeline materialisation and failures.
6. Query Gold from an **independent PostgreSQL-compatible reporting endpoint**, verifying both catalog metadata and object-store reads.
7. Inspect durable request statuses, immutable operational S3 artifacts, write-back receipts and the corresponding source records.
8. Query final Gold and validate expected fixture results.

Do not confuse a running container, acknowledged WAL position, presence of an S3 file or successful Windmill status with end-to-end correctness.

## Observability design

Start with pgAdmin (source + CDC/catalog + request DB), storage object console (both buckets), SQL-service client logs, Windmill UI and `docker compose logs` / `docker stats`. Later prototype a lightweight Streamlit dashboard aggregating source state, DuckPipe status, record-level parity, source-to-Gold timestamps and job run IDs. Do not imply that a dashboard proves multi-table snapshot consistency.

## Reproducibility

- Pin compatible images and Python dependencies; record upstream URLs/dates.
- Use fixed random seed and fixture scenario IDs; keep input and expected outputs versioned as small synthetic files.
- Avoid unbounded concurrency or generating millions of rows on a laptop.
- Test idempotent reset and cleanup using explicitly named disposable volumes; warn before data destruction.
- Use `.env.example`; never commit a live `.env`.
- Prefer versioned SQL initialization scripts and documented migration paths rather than hand-edited databases.

## Version compatibility checkpoint

Before coding, independently verify: PG source WAL settings; DuckPipe PG host supported version and remote source support; pg_ducklake required extension dependencies; S3-compatible service compatibility; DuckDB DuckLake extension catalog URI syntax; Windmill release/edition and Pipeline feature availability. Record versions in an ADR or experiment, and do not copy untested snippets from old chat discussions.

## Test hierarchy

- Unit: generator input/output, deterministic event sequence.
- Integration: source to CDC, catalog to object store, independent DuckDB read, Windmill to lake, remote SQL endpoint to catalog/S3, request API to request DB to S3 to write-back.
- Invariant: row-level data equality, updates/deletions, expected aggregated results.
- Failure: stopped CDC, replay, delayed flush, killed transformation worker, reporting service/catalog/S3 outage, source outage during write-back, crash after commit before acknowledgement.
- Benchmarks: lag, sizes, memory, CPU, runtime (measurement, not premature acceptance thresholds).

## Development workflow

Use focused issues, branch/PR review, simple lint/test CI once implementation exists. Every implementation PR should link the research question and show actual commands and results.

## Logical deployment vs physical AWS

Docker services simulate independent EC2 runtime/trust boundaries. A separate reporting SQL service and asynchronous processing system are **required logical PoC components**, but they do **not** require actual separate AWS EC2 instances on the local host. Windmill analytical and operational workers may be different groups on the same Windmill runtime. Document any intentional physical colocation.

A single local S3-compatible storage server can host **two distinct buckets** (DuckLake Parquet vs operational batch artifacts). Keep permissions/paths distinct. Database roles are separate: source, DuckPipe/catalog, Windmill state, query-serving, and operational requests. Do not mix operational pending-job writes into catalog metadata.

## Synthetic end-to-end scenarios

- Source order mutation → DuckPipe → Bronze → Silver/Gold → PostgreSQL reporting SQL endpoint.
- A client submits a synthetic token-generation request while the source is offline; worker persists prepared output and request status; source returns; write-back commits once; source CDC reflects the commit to Bronze.
- Crash after source commits but before request DB acknowledgement; retry verifies source-side batch receipt and does not duplicate output.
- Query-serving service restarted without modifying the lake or catalog; clients reconnect and obtain correct Gold values.

Follow [phase definitions](roadmap.md), [issue numbering](issue-conventions.md), [query-serving](query-serving.md), and [asynchronous processing](async-processing.md).
