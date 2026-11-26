# ADR-002 — Gate Phase 2 on remote DuckPipe with a local DuckLake sink

- **Status** Accepted for the Phase 2 experiment order and disposable runtime design
- **Approval** Maintainer approved [planning PR #37](https://github.com/TiaanViviers/cdc-lakehouse-lab/pull/37) on 2026-11-26. The remote CDC hypothesis awaits runtime evidence.
- **Date** 2026-11-26
- **Scope** Phase 2 experiment order and disposable runtime boundary
- **Related research IDs** R01–R05, R08, R09, R13, R16

## Context

The [Phase 1 closeout](../phase-1-closeout.md) establishes the stock PG16 source and its exact workload. The [candidate review](../experiments/EXP-010-phase-2-candidate-review.md) identifies an immutable PG18 artifact and a documented pgoutput path. The upstream remote regression's scope leaves the important lab behavior unverified. The candidate's source-side DDL, writable catalog format and loopback authentication affect the first experiment directly.

## Decision

Use the May digest-pinned extension build to attempt a bounded one-table remote experiment first. Keep the Phase 1 publisher in its own PG16 container and use a separate consumer PostgreSQL with colocated DuckLake metadata and persistent local data. Inspect exact row values, publication/slot state and actual catalog format before investing in reusable connector infrastructure. Proceed only after a reviewed successful probe or a reviewed, verified replacement candidate. A dedicated isolated source clone permits testing the connector's required metadata ownership while preserving the fixture roles and source-only baseline.

Keep independent verification and publisher observations available for parallel preparation. Apply the same image, source role and disposable network boundaries to subsequent trials unless reviewed evidence warrants a revision. Carry measured catalog and data format to Phase 3 for its S3 and independent reader work.

## Alternatives considered

- Build a complete deployment before testing TCP CDC. It would settle defaults early and create rework if remote decoding, source privileges or DuckLake apply fail.
- Use a current standalone pg_ducklake with the old writer. This would address a downstream format concern only if the writer, bindings and reader work together, which requires a separate experiment.
- Make a pinned same-source rebuild or a PG17 consumer comparison the first experiment. Both can help isolate an artifact or consumer-major failure. The available PG18 digest gives a smaller initial experiment.
- Use the standalone daemon or another connector. That changes the consumer architecture and requires separate approval and a rerun of the remote correctness gate.

## Consequences

The proof uses a small isolated VM and a local DuckLake sink. Source grants, cleanup and resource limits become explicit evidence. A failed probe preserves its diagnostic value and pauses build-specific work. Phase 3 receives a measured writer format and file-path contract. A usable older format may still require a different or specially matched reader and later compatibility work.

## Evidence and links

[Accepted source boundary](ADR-001-phase-1-source-baseline.md) · [Candidate review](../experiments/EXP-010-phase-2-candidate-review.md) · [Phase 2 backlog and decision gates](../../backlog/phase-2.md)

## Follow-up / re-evaluation triggers

Revisit the candidate if image/preload checks, SCRAM/TCP replication, scoped onboarding, exact snapshot or DML checks fail. Re-evaluate the retention budget and a shared lake cutoff using measured restart and multi-table behavior. Any reader migration test uses a disposable copy of the catalog and its data with verified writer compatibility.
