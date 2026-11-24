# Agent instructions — CDC Lakehouse Lab

This repository is an **engineering research project**. A passing test is necessary but not sufficient: preserve evidence and explain behavior.

## Before changing anything
1. Read `README.md`, `docs/architecture.md`, `docs/poc-specification.md`, `docs/research-questions.md` and relevant ADRs/experiments.
2. Work only on an approved issue or clearly defined user instruction. State what is in and out of scope.
3. Verify upstream tool syntax, version compatibility, images and limitations from authoritative documentation. Pin exact compatible versions when implementing; record date, URL and version in findings.
4. Distinguish **verified documentation**, **observed behavior**, **hypothesis**, **decision**, and **open question**. Never state a proposed integration works before testing it.

## Engineering constraints
- Use synthetic deterministic data; never add real operational data, client identifiers, connection strings, keys, screenshots from private systems, or other confidential material.
- Never connect to production networks or external company services. Local Docker service networking only unless explicitly approved.
- Do not commit `.env`, passwords, tokens, DB volume contents, generated objects, or large test data. Provide `.env.example` with placeholders.
- Source database logical replication must be isolated from the DuckPipe/PostgreSQL host.
- Keep DuckLake catalog metadata separate conceptually from Parquet object storage and compute. Do not portray S3 as a database server.
- Keep Windmill's internal job-state PostgreSQL separate conceptually from the DuckLake catalog.
- Never substitute technology silently (e.g. skip DuckPipe, create a different lake, write direct rows to Bronze) to manufacture a working demonstration. Document blockers and seek a decision.
- Avoid unbounded memory loads, unbounded source WAL retention and unspecified resource limits. Keep local workloads small.
- Use Docker Compose profiles or incremental service groups, health checks, named volumes, clear ports and reproducible bootstrap steps. Do not use floating `latest` tags for validated deployments.
- Prefer ordinary SQL/DuckDB transformations; Python for simulation, orchestration glue, instrumentation and tests when useful.
- Do not activate destructive resets against anything except documented disposable local services.

## Required evidence for each completed task
- Commands used and expected/observed outputs (redact credentials).
- Versions, configuration and repeatable test procedure.
- Explicit correctness check, not solely successful exit status or matching row counts.
- Operational observation: logs, SQL views, status, object listings, snapshots, metrics as appropriate.
- Failure/edge cases considered; any unresolved issues.
- Updated research question status and an experiment record when relevant.

## Development workflow
1. Branch from `main`; make small changes tied to one issue.
2. Document tests, run them, record actual result.
3. Open a PR describing hypotheses, changes, evidence, risks and reproduction instructions.
4. Do **not** auto-merge; humans review architecture and experimental interpretations.
5. If blocked, record the exact failed interface and preserve evidence rather than bypassing it.

## Documentation discipline
Use [experiment template](docs/experiments/TEMPLATE.md) and [ADR template](docs/decisions/TEMPLATE.md). The roadmap is provisional. A negative experimental result is valid completion when reproduced and explained.

## Full approved PoC and environment boundaries
The full PoC now includes an **independent query-serving service** (phase 5) and a **synthetic asynchronous request / S3 batch / controlled write-back system** (phase 6). Neither is optional for the complete demonstration, though both come after analytical ingestion and transformation are proved. The exact tools and interfaces remain research hypotheses. Read [query-serving](docs/query-serving.md) and [async-processing](docs/async-processing.md) before related work.

- Query serving must access **both** PostgreSQL DuckLake metadata and actual Gold Parquet data. Do not assume the catalog alone is a client SQL engine or silently install custom extensions on managed RDS.
- Keep pending operational request state in a separate durable PostgreSQL role. Prepared batch objects belong in a **separate S3 bucket/namespace**, not as provisional DuckPipe-maintained Bronze.
- Source PostgreSQL remains authoritative for committed operations. Use source-side idempotency receipts in the same transaction as business writes; a request-DB timestamp watermark is insufficient. Never implement reverse DuckPipe CDC as a write-back workaround.
- A manager's approval of a proposed system means permission to investigate it, **not evidence of compatibility, security or production performance**.

## Ticket identity (mandatory)
Issue titles use the stable **`<phase>.<sequence> Verb outcome`** scheme, e.g. **`1.12 Implement Python generator`**. Ticket IDs are strings and distinct from GitHub `#NN`. Phases 0–8 are defined in [roadmap](docs/roadmap.md). Read [issue conventions](docs/issue-conventions.md); check `backlog/tickets.yaml` and existing issues to avoid ID collisions. Do not automatically publish tickets or merge PRs.
