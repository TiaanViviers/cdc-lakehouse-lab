# EXP-012 — Scoped PG16 publisher permissions and object lifecycle

- **Date** 2026-11-26
- **Research question IDs** R01, R02, R04, R05
- **Status** Planned. Independent preparation is in place. Runtime observations are pending.
- **Git baseline** `d9de734` on `feature/2.2-publisher-access`
- **Source version** PostgreSQL 16.16, stock Bookworm image at index digest `sha256:cd0e9518bda5f2ea667ff84d22795d089720c883f288e215d97ce57437e8ef37` as pinned in `compose.source.yaml`. [Phase 1 image and runtime evidence](EXP-004-source-profile.md)

## Hypothesis

A dedicated replication role can read the four business tables and connect with SCRAM on the disposable source while preserving the fixture writer, reader and reset privileges. Native PG16 can sustain one persistent slot and one short-lived slot within a cap of two. An operator can remove only the enrolled run's quiescent objects using explicit identities and captured inventory. The connector may require a distinct elevation or object-creation sequence.

## Preconditions

Use a fresh enrolled source clone on the disconnected guest with one verified bridge, no published ports, two slot and sender positions, and a 128 MiB slot WAL limit evaluated at checkpoints. The source checks use a native PostgreSQL client with synthetic keys. Record run identities, deadlines and stop thresholds as specified in the [source procedure](../cdc-source.md).

## Procedure and expected results

1. Run the source schema regression and capture the baseline before role preparation. Verify exact fixture rows and receipts during the regression and baseline catalog equality after cleanup.
2. Evaluate correct and wrong-password SCRAM, allowed and denied database/replication classes, scoped SQL grants and unrelated reader restrictions. Observe the actual matched HBA rule and capture SQLSTATEs with separate authenticated sessions.
3. Exercise temporary ownership and the database CREATE grant for publication construction. Require exact fixture business-table membership, owner, primary-key replica identity, receipt isolation and successful writer/reader operations during elevation. Compare owner, identity and ACL after rollback or restoration.
4. Create one persistent pgoutput slot. Observe its survival after denied publication creation, guarded deletion, repeat setup refusal and collisions. Observe the temporary second position and rejection of a third. Verify active, wrong endpoint and unrelated-object refusals. Confirm both inventories return to baseline after authorized teardown.
5. After a reviewed supported 2.1 outcome, repeat on a fresh four-table clone with the verified connector role and build. Capture its publication owner, actual snapshot-slot and persistent-slot lifetimes, setup and failure ordering, apply and reconnect after attempted privilege reduction, exact source and target state at the required hold points, and stopped-consumer teardown. Run the existing fixture checks again once ownership and grants have been restored.

The [source procedure](../cdc-source.md) contains commands, expected diagnostics and the evidence collection sequence for the independent tests.

## Verified documentation

Reviewed 2026-11-26 against PostgreSQL 16 documentation and the `REL_16_16` source. A logical-replication login needs REPLICATION and HBA access. Initial copy requires table SELECT. Creating a publication requires database CREATE and adding tables requires table ownership. Publication ACLs cannot restrict a replication login to a particular publication. The logical connection matches the named database's HBA entry, whereas physical replication uses the separate `replication` keyword. The PG16 slot view exposes no owner or immutable creation identifier. The SQL drop attempts immediate acquisition and errors if another session holds the slot. [Security](https://www.postgresql.org/docs/16/logical-replication-security.html) · [Publication DDL](https://www.postgresql.org/docs/16/sql-createpublication.html) · [HBA](https://www.postgresql.org/docs/16/auth-pg-hba-conf.html) · [Replication protocol](https://www.postgresql.org/docs/16/protocol-replication.html) · [Slot view](https://www.postgresql.org/docs/16/view-pg-replication-slots.html) · [16.16 drop code](https://github.com/postgres/postgres/blob/REL_16_16/src/backend/replication/slotfuncs.c#L199)

## Actual observations

- `bash -n sql/cdc/source/admin.sh` passed.
- `make check BASE=origin/main` passed.
- `make test-unit` passed all 24 tests.
- `sh tests/repository-checks.sh` passed all five cases.
- The wrong-project shell guard refused before invoking a Docker or PostgreSQL client in an offline invocation.
- Publisher SQL, HBA and fixture regression observations from the scheduled PG16 VM remain pending. The native trial is designed to leave connector findings and connector acceptance open.

## Evidence artifacts

Capture runtime output under `artifacts/EXP-012/<UTC-run-id>/` with a checksummed manifest. Include the before/during/after catalog, roles, ACLs, replica identities, allowed HBA metadata, SQLSTATE and matching audit lines, source data assertions, observed slot state and resource samples. Record local tested SHA, VM overlay, resolved config and image IDs. Keep passwords, verifiers, raw conninfo and unfiltered logs outside evidence.

## Decision, limitations and open questions

Use the Phase 1 enrollment in addition to Engine identity guards. The native test slot fingerprint is based on the exact recorded creation LSNs and source identity. LSNs can advance and do not serve as a permanent ownership proof. A cluster reserved to one experiment, unique names, exclusive lifecycle operations and stopped peers are prerequisites for cleanup. The actual connector lifecycle and maintenance-grant reduction remain open pending the 2.1 result and the later end-to-end trial.

R01, R02, R04 and R05 retain their current research status. Any verified status changes belong in the final EXP-012 observations for 2.9's research-register reconciliation.
