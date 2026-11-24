# Asynchronous operational processing — Phase 6

## Purpose

Prove that delay-tolerant, synthetic operational requests can be **accepted and prepared outside the operational source**, persisted independently, and later committed in a controlled way while PostgreSQL remains authoritative for final business state.

This is not a second writable replica or a bidirectional DuckPipe deployment.

## Components and boundaries

| Component | Where (logical) | Responsibility |
| --- | --- | --- |
| Request API | Async processing service/container | Authenticated synthetic intake, validation, deduplication and request-ID assignment |
| Request PostgreSQL | Separate DB role/container | Durable request parameters, state, attempts, approvals, artifact references, progress |
| Windmill operational workers | Windmill runtime | Claim jobs/execute generation Flow; do not hold results only in process memory |
| S3-compatible operational bucket | Separate from DuckLake data bucket | Immutable versioned candidate batch files (CSV or Parquet) and checksums |
| Controlled write-back service | Async processing service/container | Authorise, validate, batch safely, retry and reconcile with source |
| Operational source PostgreSQL | Source container | Final commit / uniqueness / business constraints and idempotency receipts |
| DuckPipe | Existing CDC path | Observes committed operational changes and updates Bronze; never reverse-writes |

For a simple synthetic request, generator input can be self-contained. For an eligibility-dependent request, an **optional** read from a declared, stable Gold snapshot may supply candidates. Source-side rules must be rechecked at commit if freshness matters.

## Example synthetic workflow

A client submits `Generate 1,000 promotional tokens` with campaign, quantity, value and expiration parameters. Treat tokens as **non-redeemable test data** with no real-world value.

1. **ACCEPTED:** API validates syntax, deduplicates a client request key, atomically stores request in durable PostgreSQL and returns the ID. Durable triggering via worker poll or outbox-style queue publication must avoid losing a stored-but-untriggered request.
2. **GENERATING:** Worker claims using a lease/lock and bounded retry policy; deterministic test mode generates candidate tokens without requiring source PostgreSQL.
3. **READY_TO_COMMIT:** Worker writes the output as an immutable versioned object in the operational S3 bucket. DB stores object key/version, checksum, count, status and generation attempt. The object alone is **not** an operationally valid record.
4. **COMMITTING:** Write-back service checks approval/readiness, checksum, request ownership, schema and business constraints, then applies bounded batches to source. Record a unique request/batch receipt in the *same source transaction* as each batch of business writes.
5. **COMPLETED:** Reconcile source receipts with request DB, commit counts and errors; acknowledge only after confirming all intended batches committed.
6. **CDC observation:** The existing one-way DuckPipe link eventually synchronises source changes into Bronze, providing an analytical audit, not the primary write-back acknowledgement.

States also include `RETRY_PENDING`, `FAILED`, `REJECTED`, `CANCELLED` where legally reversible; specify allowed transitions before implementation.

## Fault / safety contract

- Simulate source outage after acceptance: preparation and S3 persistence can succeed, request stays `READY_TO_COMMIT`; tokens are not valid/active.
- Simulate crash **after source commit but before request DB acknowledgement**: retry must find the source-side receipt and avoid duplicate effects.
- Simulate duplicate submissions, overlapping workers, expired leases, partial batches, unavailable S3, corrupt files, schema mismatch, stale Gold eligibility, and conflicting source constraints.
- Exactly-once *delivery* is not assumed. Target **idempotent business effects** despite at-least-once retries.
- Use deterministic unique IDs, transactional constraints and a monotonic per-request batch index where needed. A timestamp watermark by itself is insufficient.
- Set limits for request size, worker memory, rate of writes into source, backoff and poison-job handling; don't overload the source merely because preparation was offloaded.
- Restrict source write-back identity to minimum required operations; test no unintended source tables modified.
- Source recovery from outage and S3 availability are separate concerns; S3 durability does not imply zero downtime for the request service.
- Separately record accepted-but-uncommitted vs committed-but-not-yet-captured-in-lake results.

## Completion gate

A synthetic client can submit a job, watch states in a database/UI, inspect the S3 artifact, deliberately stop the source, then restore it and observe **one and only one** committed effect per approved batch. All failure modes are documented. Any architecture that makes tokens operationally valid during source downtime requires a separate ADR and is excluded.

## Out of scope

Real vouchers, payments, customer records, production APIs, secrets, real-world authorisation/business acceptance, ledger transfer, and reverse CDC.
