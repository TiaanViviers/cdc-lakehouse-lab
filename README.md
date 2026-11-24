# CDC Lakehouse Lab

A reproducible data-engineering research lab exploring PostgreSQL change data capture (CDC), DuckPipe, DuckLake, DuckDB, Windmill orchestration, and end-to-end observability.

> **Status:** Architecture and research specification. No live end-to-end integration has been demonstrated. This repository is a hypothesis-driven lab, not a production blueprint.

## Goal

Build a small, fully synthetic, Docker-based environment in which we can inspect an operational database, observe its WAL-based replication into an S3-compatible DuckLake, transform data with DuckDB/Windmill, and independently verify results. The lab values reproducibility and understanding over assembling a large stack as quickly as possible.

## Proposed data journey

```text
Synthetic Python generator -> PostgreSQL 16 source
                                  |
                          logical WAL / CDC
                                  v
                    PostgreSQL host + pg_duckpipe
                                  |
                    DuckLake catalog + Parquet objects
                                  |
                DuckDB reader / Windmill workers
                                  |
                   Silver -> Gold analytical assets
                                  |
                     independent DuckDB consumer
```

The DuckPipe/DuckLake/Windmill shared-catalog integration is **unverified** and is a core experiment. A DuckLake catalog is metadata, not an OLAP SQL server. S3-compatible storage holds objects; computation happens in external processes.

## Read first

- [Project vision](docs/vision.md) — scope, principles, eventual possibilities.
- [Architecture](docs/architecture.md) — environments, data paths, contracts, uncertainties.
- [PoC specification](docs/poc-specification.md) — first demonstrable scope and acceptance criteria.
- [Research register](docs/research-questions.md) — testable questions and evidence.
- [Development guide](docs/development-guide.md) — local Docker and observability approach.
- [Roadmap](docs/roadmap.md) — proposed implementation order, not published GitHub issues.
- [Agent instructions](AGENTS.md) — mandatory engineering/research conventions.

## Milestone zero

Review this specification, verify current upstream docs and available compatible versions, then create a small issue backlog. **Do not assume the integrations are already working.** Initial milestone: synthetic PostgreSQL source and observable DuckPipe replication to a lake that an independent DuckDB client can read.

## Boundaries and safety

No proprietary data, credentials, internal names, customer information, actual company architecture, or production connections. Synthetic examples only. Code is independent research; review applicable employer/IP obligations before further public publication. The repository was created with an MIT licence.

## Reference documentation

- [PostgreSQL 16 logical replication](https://www.postgresql.org/docs/16/logical-replication.html)
- [pg_duckpipe](https://github.com/relytcloud/pg_duckpipe)
- [pg_ducklake](https://github.com/relytcloud/pg_ducklake)
- [DuckLake](https://ducklake.select/docs/stable/)
- [Windmill documentation](https://www.windmill.dev/docs/)
