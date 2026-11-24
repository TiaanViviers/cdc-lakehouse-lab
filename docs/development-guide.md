# Local development and engineering guidelines

## Host assumptions

Ubuntu/Linux Docker Engine + Docker Compose v2, Python 3, Git. Start with a laptop-sized configuration (~16 GB RAM). Use one Windmill worker initially and small fixtures; don't enable all services before prerequisites are validated.

## Proposed environment profiles

- `source`: PostgreSQL 16, generator, source SQL inspection.
- `cdc`: DuckPipe-compatible PostgreSQL image and extension configuration.
- `storage`: S3-compatible service with a browser object console.
- `windmill`: Windmill server, scheduler/queue/state PostgreSQL, single worker.
- `observe`: optional pgAdmin or equivalent, custom diagnostics/dashboard.

These are **planned service groups**, not implemented commands. Compose file/images/ports must be proven and documented in implementation issues.

## Human-first debugging

1. Query source tables and `pg_replication_slots` on the source.
2. Inspect DuckPipe's version-specific status API or SQL views on CDC host.
3. Inspect catalog metadata, snapshots and Parquet objects through independent interfaces.
4. Query Bronze from independent DuckDB.
5. Open Windmill's run view: inspect input, worker logs, pipeline materialisation and failures.
6. Query final Gold and validate expected fixture results.

Do not confuse a running container, acknowledged WAL position, presence of an S3 file or successful Windmill status with end-to-end correctness.

## Observability design

Start with pgAdmin (source + CDC/catalog), storage object console, Windmill UI and `docker compose logs` / `docker stats`. Later prototype a lightweight Streamlit dashboard aggregating source state, DuckPipe status, record-level parity, source-to-Gold timestamps and job run IDs. Do not imply that a dashboard proves multi-table snapshot consistency.

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
- Integration: source to CDC, catalog to object store, independent DuckDB read, Windmill to lake.
- Invariant: row-level data equality, updates/deletions, expected aggregated results.
- Failure: stopped CDC, replay, delayed flush, killed transformation worker.
- Benchmarks: lag, sizes, memory, CPU, runtime (measurement, not premature acceptance thresholds).

## Development workflow

Use focused issues, branch/PR review, simple lint/test CI once implementation exists. Every implementation PR should link the research question and show actual commands and results.
