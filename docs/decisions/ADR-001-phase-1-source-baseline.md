# ADR-001 — Phase 1 source and WAL boundary

- **Status:** Proposed
- **Date:** 2026-11-25
- **Scope:** Disposable Phase 1 PostgreSQL simulator and the source boundary it will hand to Phase 2
- **Related research IDs:** R01–R05, R13, R16, R25

## Context

The approved logical architecture uses a separate operational PostgreSQL source and DuckPipe consumer. [M1](../poc-specification.md#phase-by-phase-exit-gates) requires inspecting source WAL settings. The prior roadmap assigned source WAL configuration to Phase 2, and the local runtime design called for checking slot configuration during Phase 1. The source phase can inspect a reproducible configuration before testing any retention or consumer behavior. The Phase 0 runtime design also requires proof of host egress controls, and the fixture specifies a durable S04 receipt for S06.

## Decision

Use the [Phase 0 PostgreSQL 16.16 Bookworm candidate and registry digest](../compatibility-matrix.md#image-provenance) as the first Phase 1 source pin. Use only the source profile on a disposable host or VM with verified egress denial and unpublished database ports. Use source-local `psql` for inspection, with a read-only identity for fixture observations. Record actual Engine, Compose, image, database and runner versions with the validation evidence.

Set and inspect `wal_level=logical`, finite sender/slot counts and finite slot retention in Phase 1, with zero lab publications or slots. Measure WAL disk use separately. Defer connector-dependent publication, replication privileges, slots, decoding, retention under active/inactive slots and catch-up to Phase 2. Keep S04's fixture receipt transactionally coupled to its business rows and outside the four-table data parity contract. The Phase 6 write-back receipt remains a separate contract.

## Alternatives considered

- Defer all WAL configuration until Phase 2. This reduces Phase 1 setup but leaves M1 without an inspected publisher baseline and bundles publisher and consumer changes into the first integration.
- Create a logical slot in Phase 1. This provides an earlier metadata signal, introduces WAL retention, and lacks the real connector behavior needed to size slots and validate recovery.
- Require a browser UI in Phase 1. This adds a network and service to the first gate. The recorded source SQL checks and read-only walkthrough satisfy initial inspection with the published database port disabled.

## Consequences

The source gate remains testable without DuckPipe and exposes a single known baseline for the first remote replication experiment. The retention parameter limits slot retention at checkpoints and does not bound all disk growth. A safe local host/VM, explicit stop thresholds and measured disk use are prerequisites. Exact WAL/resource limits, runner pins, receipt storage, reset identity and failure hooks are implementation decisions with validation criteria in the [draft backlog](../../backlog/phase-1.md).

## Evidence and links

The [Phase 0 closeout](../phase-0-closeout.md) records the scope approval and documentation-only compatibility findings. Reviewed on 2026-11-25 against [PostgreSQL 16.16 release notes](https://www.postgresql.org/docs/16/release-16-16.html), [PostgreSQL 16 replication settings](https://www.postgresql.org/docs/16/runtime-config-replication.html), [Docker Compose networks](https://docs.docker.com/reference/compose-file/networks/) and [Docker Engine firewall behavior](https://docs.docker.com/engine/network/packet-filtering-firewalls/). The Docker documentation describes the current interfaces. Exact versions, effective controls and runtime outcomes remain to be recorded in Phase 1.

## Follow-up / re-evaluation triggers

Revisit the pin or isolation procedure if the image, resource limits or network controls fail on the selected host. Keep the source gate open until reproduced with reviewed changes. Revisit the WAL limits in Phase 2 using measured slot activity, WAL consumption, disk and invalidation behavior. Revisit the fixture contract if reset, concurrent S05 or ambiguous S04 outcomes fail to preserve the expected state.
