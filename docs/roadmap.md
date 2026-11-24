# Proposed staged roadmap (not yet GitHub issues)

This is a dependency-aware plan for review, not evidence of implementation.

| Phase | Objective | Key deliverable | Exit gate |
| --- | --- | --- | --- |
| 0 | Research and repo foundation | Specifications, ADRs, issue templates | Scope and upstream versions reviewed |
| 1 | Source simulator | PostgreSQL 16 + deterministic generator + inspection | Reproducible changes and expected-state assertions |
| 2 | Remote CDC | Compatible DuckPipe host + remote source logical replication | Initial snapshot and mutations validated |
| 3 | Shared lake | PostgreSQL catalog + S3-compatible data + DuckDB reader | Independent row-level query correctness |
| 4 | Transformation | Windmill run environment, DuckDB SQL, Flows/Pipelines | Bronze → Silver → Gold measured and validated |
| 5 | Observability | Human-facing runbooks + optional status UI | Each stage inspectable with documented procedure |
| 6 | Reliability | Controlled fault injection and recovery | Behavior explained with artifacts and limitations |

**Observability is introduced in phases 1–4, not postponed until phase 5.**

## Initial candidate issues

1. Verify and document upstream version/compatibility matrix.
2. Prepare minimal Compose baseline, secrets example and documented network.
3. Implement PostgreSQL source schema and deterministic event scenarios.
4. Add source SQL inspection and invariant checks.
5. Bootstrap remote DuckPipe connection and document settings.
6. Test initial snapshot parity and WAL slot observation.
7. Test CDC insert/update/delete and retry after interruption.
8. Establish S3-compatible DuckLake storage and inspect objects.
9. Validate independent DuckDB read of DuckPipe-created Bronze.
10. Install local Windmill and run first simple DuckDB job.
11. Materialise Silver and Gold with a conventional Flow.
12. Evaluate Windmill Pipelines dependency/asset behavior on shared lake.
13. Add observability runbook/dashboard prototype.
14. Run consistency, restart and resource-use experiments.

Tasks should be split further where needed and published **only after review**, with acceptance tests and clear dependencies.

## Deferred tracks

Dedicated reporting SQL service (PostgreSQL pg_ducklake, native DuckDB serving, alternative OLAP engine); asynchronous request store, prepared S3 batches and controlled write-back; real AWS infrastructure, RDS catalog, HA and scale benchmarking.
