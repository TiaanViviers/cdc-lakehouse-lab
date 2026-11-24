# Phased implementation roadmap — full PoC

This is a **dependency order**, not evidence that any component works. The full logical topology is approved for research. Initial development is local, synthetic and incremental.

| Phase | Title | Implementation slice | Exit proof |
| --- | --- | --- | --- |
| **0** | Research / repository foundation | Docs, ADRs, compatibility matrix, local runtime conventions | Architecture and version assumptions reviewed |
| **1** | Operational source simulator | PG16 + deterministic Python generator + inspection | Reproducible committed events / expected row states |
| **2** | DuckPipe CDC | Remote logical source, CDC worker, initial snapshots / WAL slots | Snapshot and ongoing CDC row-level correctness |
| **3** | DuckLake catalog / object storage | PG metadata, S3-compatible Parquet, independent DuckDB reader | Same catalog/files yield correct independent queries |
| **4** | Windmill transformation engine | Server, queue PG, workers, DuckDB, Flows/Pipelines, Silver/Gold | Complete Bronze → Gold transformation with dependencies |
| **5** | Reporting SQL serving | Independent PG-compatible SQL endpoint using pg_ducklake candidate; catalog + S3 Gold access | SQL clients query correct Gold, with measured concurrency/failures |
| **6** | Asynchronous operational processing | Request API/PG, Windmill ops worker, separate S3 batch bucket, controlled write-back | Request persists through source outage; exactly-once effects on retry |
| **7** | Unified observability / operator UX | Live status views, pgAdmin, S3 console, Windmill UI and optional Streamlit lab dashboard | Guided trace for CDC and async requests with logs and evidence |
| **8** | Integrated resilience and evaluation | Cross-component interruption/replay, consistency, resource measurements, ADRs | Reproducible findings / limitations / feasibility conclusions |

**Cross-cutting rule:** Basic observability and correctness checks must ship with **each** phase. Phase 7 only integrates and polishes what was already inspectable.

## Dependency sketch

```text
0 → 1 → 2 → 3 → 4 → 5
                 ↘    ↘
                   6 → 7 → 8
```

Operational Phase 6 requires the source (phase 1), durable worker orchestration (phase 4), and optionally a Gold snapshot (phase 4); it does **not** require a reporting SQL endpoint, despite following Phase 5 in the preferred learning order. Phase 5 requires the lake and Gold tables. Observability incrementally covers both branches.

## Candidate phase-specific work (NOT published tickets)

- **Phase 0:** verify upstream extension/edition/image matrix; Docker security conventions; agent workflow and ticket registry.
- **Phase 1:** synthetic related schema, deterministic inserts/updates/deletes, independent expectation tests, PostgreSQL inspection.
- **Phase 2:** source WAL configuration, remote DuckPipe, snapshot parity, LSN/slot observation, stop/restart scenario.
- **Phase 3:** local S3-compatible bucket, catalog metadata, independent DuckDB, Parquet objects/snapshots, multi-writer unknowns.
- **Phase 4:** Windmill runtime + one worker, read Bronze, Silver SQL, Gold Reporting/ML, Pipelines dependency experiments, readiness checks.
- **Phase 5:** separate SQL-serving container/PG extension, remote catalog access, S3 Gold read, read-only roles, concurrent query benchmark, restart.
- **Phase 6:** request-store schema/state transitions, client intake, Windmill job claim, artifact write/read, commit receipts, retry/outage experiments.
- **Phase 7:** source/CDC/lake/worker/reporting/request inspection pages and trace IDs, optional consolidated dashboard.
- **Phase 8:** controlled fault matrix, WAL/storage pressures, cross-table consistency, reconciliation, reproducibility report and architecture recommendation.

## GitHub ticket scheme

Every actual ticket title begins with a stable **`<phase>.<number>`** identifier, e.g. **`1.12 Implement Python generator`**. The sequence is per phase; numbers are never recycled or renumbered after publication. GitHub `#123` is a separate global issue number. See [ticket conventions](issue-conventions.md) and [backlog index](../backlog/README.md). Do not publish issues automatically from this roadmap.

## Phase transition is part of every milestone

Each milestone ends with a **mandatory, last-to-complete transition ticket**: reconcile research findings and ADRs, review/update scope, create the **next milestone only**, draft/approve and publish its tickets, reserve IDs and add them to the shared board. Later phases are not pre-ticketed. The transition issue is last in *completion order* even if new phase-specific issues receive higher ticket IDs during research. Phase 8 ends with a final closeout ticket instead of automatically creating Phase 9. See [GitHub project workflow](project-management.md).

## Phase completion discipline

No milestone is complete merely because Docker containers are healthy or an agent reports success. Require reproducible commands, data correctness checks, evidence from UIs/logs, version pins and relevant research-question updates.

## Research gates

A blocker in a proposed integration is a **research finding**, not permission to hide an alternate topology. Capture negative evidence, raise an ADR and update the relevant dependency plan before changing the implementation.
