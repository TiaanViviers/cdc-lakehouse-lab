# EXP-005 — Source schema and guarded cleanup

- **Date** 2026-11-25
- **Research question IDs** R02, R03, R13
- **Status** Offline checks passed. PostgreSQL acceptance pending ticket 1.2 integration.
- **Operator** Codex
- **Branch** `feature/1.3-source-schema`
- **Software** Runtime target is PostgreSQL 16.16 Bookworm with the [ADR-001 image pin](../decisions/ADR-001-phase-1-source-baseline.md). Offline checks used Bash 5.2.21, CPython 3.12.3, Git 2.43.0, GNU Make 4.3 and pglast 6.17 (PostgreSQL 16.1 parser).

## Hypothesis

A clean disposable source accepts the v1 schema and grants. A repeat migration leaves schema definitions and all values intact. The constraints and grants reject invalid changes with their expected SQLSTATEs. Cleanup requires matching database identity and reset intent, clears the fixture rows in FK order, and rolls back with its caller.

## Preconditions and verified documentation

Run acceptance on a clean volume in the completed [ticket 1.2 environment](https://github.com/TiaanViviers/cdc-lakehouse-lab/pull/31) in the dedicated disconnected VM. The source runbook and profile establish the isolation, health, disk and resource checks. Record the actual runtime versions and image digest with the run ID. The suite uses fixed, test-only rows.

Reviewed on 2026-11-25 for PostgreSQL 16.16. `psql` documents conditional processing, safely quoted variables and exit code 3 for scripts stopped by `ON_ERROR_STOP`. The server documents the FK restriction, time zone type, function privilege scope and lock lifetime used here. [16.16 release](https://www.postgresql.org/docs/16/release-16-16.html) · [`psql`](https://www.postgresql.org/docs/16/app-psql.html) · [Constraints](https://www.postgresql.org/docs/16/ddl-constraints.html) · [Date/time types](https://www.postgresql.org/docs/16/datatype-datetime.html) · [`GRANT`](https://www.postgresql.org/docs/16/sql-grant.html) · [`CREATE FUNCTION`](https://www.postgresql.org/docs/16/sql-createfunction.html) · [`LOCK`](https://www.postgresql.org/docs/16/sql-lock.html)

The installation compares the database OID and the cluster system identifier initialized by `initdb`. The cleanup function uses a restricted `search_path`, an owning role with no login, and explicit `EXECUTE` grants. The test suite uses session authorization to exercise each role's SQL permissions. [Control data functions](https://www.postgresql.org/docs/16/functions-info.html#FUNCTIONS-CONTROLDATA) · [`SET SESSION AUTHORIZATION`](https://www.postgresql.org/docs/16/sql-set-session-authorization.html) · [SQLSTATE codes](https://www.postgresql.org/docs/16/errcodes-appendix.html)

## Procedure and expected results

1. Follow [the source schema runbook](../source-schema.md#acceptance-checks) to run the migration and the acceptance suite, then verify each provisioned role over loopback SCRAM. Use the suite's 3 s connection and lock deadlines, 10 s SQL and idle-in-transaction deadlines, and the 1.2 disk thresholds.
2. Compare the catalog output to the [workload table specification](../synthetic-workload.md#fixed-requirements) and the role grants to the [role contract](../source-schema.md#bootstrap-and-role-setup). Expect `Fixture schema 1 already installed` and identical catalog and full row outputs on repeat. For each read, compare all five ordered relations, including both timestamps and the receipt digest.
3. Expect invalid references or restricted deletes to return `23503`, duplicate keys or references `23505`, null values `23502`, domain violations `23514`, and unauthorized writes `42501`. Expect false or absent intent to return `22023`, and absent or mismatched database identity `55000`. The reader must see the same complete committed state after each attempt.
4. Observe empty fixture relations inside the writer's cleanup transaction before the forced `22012`; a fresh reader must then see all the original rows and receipt. Committed cleanup must leave the 5 relations empty. The catalog must still match the initial capture.

## Actual observations

The following offline commands passed in the ticket worktree.

```sh
make check BASE=origin/main
sh tests/repository-checks.sh
make test-unit
bash -n tests/integration/source-schema/run.sh
```

The repository checks exercised all five rejection paths and the offline unit suite reported `Ran 20 tests` and `OK`. A separate static check used the pinned [pglast 6.17 parser](https://github.com/lelit/pglast/releases/tag/v6.17) to parse SQL and PL/pgSQL after removing `psql` directives and substituting a literal UUID. It parsed 34 migration statements, all three verification SQL files, and the 33 statement probes and 4 literal SQL blocks in the Bash harness. The same check independently matched every field of the three documented S04 inserts to the S03-to-S04 delta in the fixture oracle and reproduced the documented SHA-256 digest.

## Evidence artifacts

The [migration](../../sql/source/001_fixture_v1.sql), [catalog queries](../../tests/integration/source-schema/catalog.sql), [ordered row queries](../../tests/integration/source-schema/rows.sql), [expected probe rows](../../tests/integration/source-schema/expected-probe-rows.txt) and [acceptance runner](../../tests/integration/source-schema/run.sh) retain the commands and expected values. Save the runtime command transcript, catalog snapshots, negative SQL and diagnostics, before/after rows, role authentication evidence and 1.2 environment observations outside Git under the run ID. [Issue #21](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/21)

## Interpretation, limitations and follow-up

The offline observations establish the parsed syntax and agreement of the receipt contract with the fixture oracle. PostgreSQL execution, catalog and grant behavior, and committed before/after observations remain pending. After ticket 1.2 merges, run the procedure on that verified source and add observed evidence under a fresh run ID. R02, R03 and R13 remain open. S00 reuse and S04 replay are exercised by tickets 1.5 and 1.7.
