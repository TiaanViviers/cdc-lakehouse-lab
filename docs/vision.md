# Vision, scope and project status

## Mission

Build a reproducible, observable and fault-testable data platform lab in which a source PostgreSQL database is read **once through a CDC ingestion path** and its data is reused for analytics, reporting and optional downstream operational preparation. Demonstrate both the strengths and the limits of the proposed architecture.

A project stakeholder has **approved the full logical reference architecture as the PoC direction**, including separate query serving and asynchronous request processing. This is **scope approval**, not experimental verification or permission to use proprietary data or actual environments.

## Target architecture

### Path A — analytical plane

Synthetic PostgreSQL → remote `pg_duckpipe` (logical WAL) → DuckLake Bronze, catalogued in PostgreSQL with Parquet files in an S3-compatible bucket → Windmill-managed DuckDB transformations → Silver and domain-specific Gold → independent SQL query service for reporting and independent DuckDB clients for validation/ML.

### Path B — operational work plane

Synthetic client request → API + durable request PostgreSQL → Windmill operational workers → optional reads from a **declared, versioned** lake snapshot → candidate batch output in a **different S3 bucket** → controlled, scheduled or event-driven, idempotent production write-back → source PostgreSQL commit → ordinary one-way CDC captures the resulting operational records.

**Authority rules:** production-like PostgreSQL decides final operational validity; the request store owns pending work/status, not redeemable business state; the lake is the canonical analytical copy, not an independent writer of source-of-truth rows. If business rules require activation while source PostgreSQL is unavailable, that is an explicitly out-of-scope redesign of operational authority.

## Why this is transformational

- Single upstream CDC path rather than repeated downstream extraction.
- Reusable Bronze/Silver/Gold datasets, including separate Gold Reporting, Gold ML and Gold Analytics.
- Independent, scalable compute and query-serving roles.
- Non-blocking request generation and durable delayed write-back.
- Transparent consistency contracts, replay, snapshots, failure/recovery and observability.

## Initial PoC scope (all phases)

**Included:** source simulator, DuckPipe, DuckLake + catalog + S3-compatible storage, Windmill/worker transformations, *logical independent reporting query service*, synthetic asynchronous request DB/API, separate operational S3 artifacts, controlled source write-back, monitoring and fault injection. These may run as containers on one laptop rather than five real EC2 instances.

**Excluded:** actual company data/infrastructure, branded domain models, existing ETL migrations, public network APIs, real voucher value/redemption, full enterprise identity management, hard production SLAs, multi-region disaster recovery, real AWS billing/provisioning, unbounded scale, and claims of operational independence during an outage.

## Decisions vs research hypotheses

Selected architectural **roles** are accepted for PoC exploration. Specific products, deployment topology, protocol support, shared-catalog multi-writer semantics, query concurrency, and recovery guarantees remain to be established through documented experiments. Retain failure evidence; use ADRs before changing a key design.

## Research philosophy

The foundation phase delivers a reviewed research plan and repository checks. Each implementation phase calls for a working demonstration, deterministic validation, an inspection runbook and an experiment report. A well-characterized incompatibility is a useful result; silently replacing the requested stack is not.

The editable [architecture drawing](Data_System.drawio) is a communication aid, not proof of a functioning deployment.
