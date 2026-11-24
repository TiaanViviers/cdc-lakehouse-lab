# Full PoC specification — v0.2

**Scope:** The full logical reference architecture is accepted for the research PoC; the component integrations and suitability are **unverified** until demonstrated. Build each dependency milestone independently. No corporate credentials, internal records or actual production access.

## Intended demonstration

A deterministic synthetic operational transaction → PostgreSQL 16 commit → remote DuckPipe WAL consumption → PostgreSQL-catalogued DuckLake Bronze with S3-compatible Parquet → Windmill worker/DuckDB Silver and domain-specific Gold materialisation → separate SQL query endpoint answering client SQL from catalog metadata **and** Gold files.

Additionally: an independent synthetic client requests a large token batch → request API + durable request PostgreSQL → Windmill operational workers (optional named Gold input) → immutable *separate S3 bucket* artifact → controlled, idempotent PostgreSQL write-back → already-established one-way CDC into Bronze.

## Functional requirements

| ID | Required feature / proof |
| --- | --- |
| F01 | Source PG16 with deterministic related synthetic tables and insert/update/delete/multi-table commits |
| F02 | Remote DuckPipe initial snapshot with row-level parity, correct keys |
| F03 | Subsequent CDC updates/deletes and recovery, with inspected WAL positions and lag |
| F04 | DuckLake PostgreSQL metadata catalog + S3-compatible Parquet; independent DuckDB client sees correct rows/snapshots |
| F05 | Bronze/Silver/Gold transformations produce verified reporting and ML-like outputs; SQL compute occurs in worker, not object store |
| F06 | Windmill server, scheduler, own PostgreSQL and workers; compare explicit Flows and asset-based Pipelines |
| F07 | Named and documented ingestion-ready boundary before dependent transformations; record unsolved cross-table consistency limits |
| F08 | Independent **logical** PostgreSQL-compatible reporting SQL endpoint accesses catalog **and** S3 Gold; external `psql`/driver client reads correct data |
| F09 | Basic concurrent reporting query measurements, read-only controls, restart/error tests (not an enterprise SLA) |
| F10 | Asynchronous API persistently accepts generic requests even when source is unavailable, with request ID/idempotency |
| F11 | Request PostgreSQL tracks job lifecycle, retries, immutable S3 object ref/version/checksum/progress |
| F12 | Windmill operational worker generates synthetic batch into a separate S3 bucket; no need for reverse CDC or direct Bronze mutation |
| F13 | Controlled write-back validates and commits batches into source with source-side transactional receipts; retries produce no duplicate effects |
| F14 | Observe source commit flowing through existing CDC to analytical Bronze without feedback loops |
| F15 | Human-inspectable source, CDC, catalog, S3 objects, Windmill job history, query endpoint and request states |
| F16 | Controlled fault experiments: CDC interruption, broken catalog/S3, worker crash, source outage during write-back, duplicate requests |

## Acceptance strategy

Every phase requires (1) observable running components, (2) actual row/aggregate correctness checks using deterministic fixtures, (3) exact reproducible commands and version pins, (4) recorded experiment evidence, and (5) explicit limitations. A green Docker status, a WAL LSN, or a successful workflow badge **does not** prove correctness.

### Phase-by-phase exit gates

- **M0:** Documentation reviewed; upstream version/edition matrix, licence constraints and safe Docker baseline agreed.
- **M1:** Deterministic source scenarios reproduce exact intended states; inspect SQL and WAL settings.
- **M2:** DuckPipe remote source snapshot + insert/update/delete reliably converge in a simplest supported local sink.
- **M3:** Catalog + S3-compatible Parquet representation independently queryable by DuckDB, with snapshots and recovery documented.
- **M4:** Windmill transformation chain works on exact DuckPipe-maintained lake; compare Pipelines/Flows and document external asset triggers.
- **M5:** Dedicated logical query service gives correct Gold results to ordinary PostgreSQL client, with basic auth/isolation and measured concurrency.
- **M6:** Synthetic request accepted, prepared, persisted, committed *exactly once in effect* despite retries/source outage; result appears downstream via CDC.
- **M7:** Guided dashboard/runbooks expose all boundaries, failures, and source-to-Gold and request-to-commit state.
- **M8:** Repeatable integrated failure/recovery and resource results; open integration risks and suitability conclusions documented.

## Deployment and scope constraints

- One Docker Compose lab on Ubuntu/16GB-class laptop with isolated services/volumes; phase-specific profiles and bounded record volumes.
- Source PG, DuckPipe/catalog PG, Windmill PG, query-serving PG and request PG are **distinct logical roles**; may share a physical Docker host. No obligation to provision five real EC2 machines.
- Two distinct S3-compatible buckets/namespace+policy: DuckLake-managed files and operational batch artifacts. They may share a local object-store service.
- A dedicated reporting service is part of the **full target**, but early debugging may query the CDC PG host as an interim check. Phase 5 still validates an independently hosted query endpoint.
- Operational processing is part of full target **after** analytical path/reporting; source remains final authority. Source writes from write-back are explicitly separate from the one-way CDC extraction.
- Not building real AWS, commercial data, massive scale, voucher redemption, a general distributed ledger, business failover, or an HA/DR platform.
- Do not substitute a different technology silently when DuckPipe, Windmill Pipelines, or pg_ducklake prove incompatible. Log the experiment and produce an ADR.

## Data contracts and risks

- Bronze primarily current-state; full CDC event history/time-travel retention require explicit tests.
- Multi-table readiness and consistent snapshots must be tested rather than inferred from `STREAMING` or empty queues.
- Reporting clients do not run arbitrary SQL on catalog metadata PostgreSQL; query service has its own engine and separate S3 access.
- SQL-serving interoperability with RDS cannot be assumed; an external catalog on RDS is a distinct question from installing a custom extension on RDS.
- Pending output file is not a valid operational object; source-side unique batch receipts and transactional writes make replay safe.
- Durable API acceptance must not be lost because a queue publication failed; worker polling or outbox-style repair is required.
- Stale lake-backed eligibility cannot override operational source constraints at commit.

## Research evidence and references

Use [research register](research-questions.md), [experiment template](experiments/TEMPLATE.md), [query-serving plan](query-serving.md) and [async processing plan](async-processing.md). Record versions, commands, data checks, observed metrics and failures. See [roadmap](roadmap.md) for staged tasks and [ticket conventions](issue-conventions.md) for stable IDs.
