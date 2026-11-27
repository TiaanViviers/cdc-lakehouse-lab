# ADR-003 — Keep M2 open and qualify the shared-lake research

- **Status:** Proposed, maintainer decision pending
- **Date:** 2026-11-27
- **Scope:** Phase 2 gate disposition, Phase 3 starting boundary and downstream consistency
- **Related research IDs:** R01–R09, R13, R15, R16

## Context

Remote CDC showed exact held current-state convergence, same-slot recovery inside retained WAL and clean resnapshot after slot loss. EXP-020 reproduced sustained sparse-table WAL growth and a concurrent COPY checkpoint miss. EXP-019 showed partial effects of one committed source transaction inside two explicit catalog versions. The deployed writer uses a colocated PostgreSQL DuckLake 0.4 catalog and routinely inlines small writes. [Closeout](../phase-2-closeout.md) · [EXP-020](../experiments/EXP-020-phase-2-cdc-gate.md) · [EXP-019](../experiments/EXP-019-cdc-visibility.md)

## Proposed decision

1. Keep M2 unmet and Phase 2 open. Authorize focused WAL and COPY work, then require clean, compatible evidence through the existing full M2 review.
2. Approve the Phase 3 draft for later publication. Keep PG metadata with the writer initially. Test SeaweedFS and a version-matched, least-privilege independent DuckDB client against actual writer data, with a held source checkpoint and explicit version. Start with a fresh, disposable writer catalog using an S3 target table path. Preserve the original local catalog.
3. Decide separately whether to authorize early compatibility research within the three bounded scopes in the closeout while Phase 2 is open. Keep one exclusive, isolated VM lease for all runtime trials.
4. Use exact held/versioned inputs for a later Windmill lab baseline. Evaluate a transaction-aware publication mechanism separately before promising continuous-source consistent Gold. Lack of an eligible boundary fails closed for that mode.

## Alternatives considered

- Continue only after full M2 acceptance. This is the default for implementation and integrated runtime work, with minimal risk of retesting a changed writer. A separately authorized early compatibility probe could catch an independent catalog or extension mismatch sooner.
- Review a restricted continuation with M2 unmet. This would require a documented maintainer decision, a bounded operating contract and a clear statement of the ingestion guarantees missing from later demonstration. It cannot serve as a positive M2 verdict.
- Change the connector or writer/catalog build. Compare on disposable resources with the existing fixture and gate evidence. A format change invalidates the assumed downstream pins until reverified. A live migration needs a separate decision with rehearsed matched catalog/data backup and recovery.
- Derive a cutoff by polling current connector telemetry. The pinned implementation and actual partial versions leave the necessary evidence missing. A transaction-aware writer or constrained ingestion contract would need separate experiments.

## Consequences

The regular Phase 3 transition remains blocked until the maintainer decides. Some compatibility questions can be isolated without depending on faulty concurrent COPY or long sparse operation. Same-slot recovery, fresh resnapshot, stable historical versions and complete committed-source prefixes are different contracts and must keep separate evidence. Keep the current component boundaries and local-only runtime resource controls.

## Evidence and re-evaluation triggers

Revisit after repeatable sparse feedback and COPY results, an upstream fix or a supported replacement, an independent 0.4 attach and object-backed read, or a verified transaction boundary tied to a retained snapshot. A migration, a connector substitution, a changed gate and a second runtime slot each require independent approval and evidence. [Corrective work](../../backlog/phase-2-corrections.md) · [Phase 3 backlog](../../backlog/phase-3.md) · [R13 analysis](../bronze-snapshot-cutoffs.md)
