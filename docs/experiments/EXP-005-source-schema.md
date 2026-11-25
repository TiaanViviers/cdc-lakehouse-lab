# EXP-005 — Source schema and guarded cleanup

- **Date** 2026-11-25
- **Research question IDs** R02, R03, R13
- **Status** Runtime acceptance checks passed on the verified ticket 1.2 source
- **Operator** Codex
- **Tested revisions** Ticket 1.3 `0c8e9fabb2a40298cb5516366a1cda0c3e83aaf3` on merged 1.2 base `1dd479ea451e7481642a6082136d14181fc21cb8`, combined Git tree `7877545973f55bbd683270c3a5040a3f4b0fdc7f`
- **Run ID** `20261125T113037Z-p01-03`, Compose project `cdc-source-13-03`, fresh volume `cdc-source-13-03_source-pg`
- **Software** Server and `psql` 16.16 (`16.16-1.pgdg12+1`), Docker Engine 29.1.3, Compose 2.40.3+ds1-0ubuntu1~24.04.1, QEMU 8.2.2 with KVM, guest Ubuntu 24.04.5 LTS amd64 and Linux 6.8.0-147-generic, iptables and ip6tables 1.8.10 (`nf_tables`). Offline checks used Bash 5.2.21, CPython 3.12.3, Git 2.43.0, GNU Make 4.3 and pglast 6.17 (PostgreSQL 16.1 parser).

## Hypothesis

A clean disposable source accepts the v1 schema and grants. A repeat migration leaves schema definitions and all values intact. The constraints and grants reject invalid changes with their expected SQLSTATEs. Cleanup requires matching database identity and reset intent, clears the fixture rows in FK order, and rolls back with its caller.

## Preconditions and verified documentation

Run acceptance on a clean volume in the completed ticket 1.2 environment. This run used a new QCOW2 overlay over the powered-off 1.2 guest, with two vCPUs, 2048 MiB RAM and QEMU `-nic none`. The combined Git tree entered on read-only virtual media. The source image matched index digest `sha256:cd0e9518bda5f2ea667ff84d22795d089720c883f288e215d97ce57437e8ef37` and the `linux/amd64` manifest prefix `d755a91aff87` already verified in 1.2. The suite uses fixed, test-only rows. [Merged ticket 1.2](https://github.com/TiaanViviers/cdc-lakehouse-lab/pull/31) · [Image provenance and startup evidence](EXP-004-source-profile.md)

Reviewed on 2026-11-25 for PostgreSQL 16.16. `psql` documents conditional processing, safely quoted variables and exit code 3 for scripts stopped by `ON_ERROR_STOP`. The server documents the FK restriction, time zone type, function privilege scope and lock lifetime used here. [16.16 release](https://www.postgresql.org/docs/16/release-16-16.html) · [`psql`](https://www.postgresql.org/docs/16/app-psql.html) · [Constraints](https://www.postgresql.org/docs/16/ddl-constraints.html) · [Date/time types](https://www.postgresql.org/docs/16/datatype-datetime.html) · [`GRANT`](https://www.postgresql.org/docs/16/sql-grant.html) · [`CREATE FUNCTION`](https://www.postgresql.org/docs/16/sql-createfunction.html) · [`LOCK`](https://www.postgresql.org/docs/16/sql-lock.html)

The installation compares the database OID and the cluster system identifier initialized by `initdb`. The cleanup function uses a restricted `search_path`, an owning role with no login, and explicit `EXECUTE` grants. The test suite uses session authorization to exercise each role's SQL permissions. [Control data functions](https://www.postgresql.org/docs/16/functions-info.html#FUNCTIONS-CONTROLDATA) · [`SET SESSION AUTHORIZATION`](https://www.postgresql.org/docs/16/sql-set-session-authorization.html) · [SQLSTATE codes](https://www.postgresql.org/docs/16/errcodes-appendix.html)

## Procedure and expected results

1. Follow [the source schema runbook](../source-schema.md#acceptance-checks) to run the migration and the acceptance suite, then verify each provisioned role over loopback SCRAM. Use the suite's 3 s connection and lock deadlines, 10 s SQL and idle-in-transaction deadlines, and the 1.2 disk thresholds.
2. Compare the catalog output to the [workload table specification](../synthetic-workload.md#fixed-requirements) and the role grants to the [role contract](../source-schema.md#bootstrap-and-role-setup). Expect `Fixture schema 1 already installed` and identical catalog and full row outputs on repeat. For each read, compare all five ordered relations, including both timestamps and the receipt digest.
3. Expect invalid references or restricted deletes to return `23503`, duplicate keys or references `23505`, null values `23502`, domain violations `23514`, and unauthorized writes `42501`. Expect false or absent intent to return `22023`, and absent or mismatched database identity `55000`. The reader must see the same complete committed state after each attempt.
4. Observe empty fixture relations inside the writer's cleanup transaction before the forced `22012`; a fresh reader must then see all the original rows and receipt. Committed cleanup must leave the 5 relations empty. The catalog must still match the initial capture.

## Actual observations

### Isolation and source state

The guest began with `lo` and `docker0` and no default route in either address family. The resolved source profile listed a single database on the intended external bridge ID, with no published ports. With bridge firewall rules absent, both gateway probes reached their positive controls and the gate blocked startup. After adding the 1.2 rules, source peer DNS and TCP returned the expected marker, IPv4 and IPv6 gateway probes each timed out in 1.58 s, routed LAN, VPN and IPv6 probes returned `ENETUNREACH`, and delegated DNS returned `ESERVFAIL`. The gate then allowed Compose to start PostgreSQL. The container became healthy with no published ports, matched the captured network ID and mounted the fresh named volume.

Effective settings were `logical|2|2|128MB|0|0` for WAL level, sender cap, slot cap, slot retention, publications and slots. The cgroup reported `805306368` bytes of memory, zero swap and CPU quota `100000 100000`. The WAL directory reported one 16 MiB segment before and after the suite. The database directory grew from 46,952 to 47,336 KiB, with over 4.5 million KiB free. The last sample reported 0.07% CPU and 67.23 MiB memory. The source stopped with exit 0 and no OOM. The guest restored its firewall rules, removed the test bridge, and ended with zero containers. The run ended at `2026-11-25T11:31:11Z`.

### Bootstrap, constraints and role grants

Clean bootstrap yielded the five empty fixture relations. The independent catalog review verified column order, data types, non-null constraints, primary keys, natural keys and all three `ON DELETE RESTRICT` foreign keys. All nine cataloged domain checks on the business tables matched the specification. The catalog showed matching values for UUID, database OID and cluster identifier, with a no-login owner, no fixture role memberships, scoped table and column grants, and cleanup execution restricted to the owner and fixture writer. The suite's first, repeated and post-cleanup captures of the catalog were byte-identical. Each captured file had SHA-256 `4cce7262283acbdaf0eb0b804366107663264af263d16a594ac919d6cbee88a2`. [Observed catalog and ACLs](evidence/EXP-005-source-catalog.txt)

The writer inserted the probe rows, updated the item's quantity and timestamp, and explicitly deleted the extra item. Each independently read committed row matched the expected file. Repeat bootstrap printed `Fixture schema 1 already installed` and the reader returned the same five ordered lines. After password provisioning, actual loopback clients returned `source_fixture_writer|source_lab|0` and `source_fixture_reader|source_lab|0`. PostgreSQL logged `method=scram-sha-256` for both against HBA line 115.

### Rejected operations and cleanup

All 37 negative operations returned the expected SQLSTATE and diagnostic. Each negative probe was followed by a fresh reader transaction that matched the complete baseline, including the receipt. The orphan-payment case first inserted a different receipt within the failing transaction and the reader confirmed its absence afterward.

| SQLSTATE | Cases | Observed rejection |
| --- | ---: | --- |
| `23503` | 5 | Three orphan references and two restricted parent deletes |
| `23505` | 6 | Duplicate business primary key, four natural keys, and duplicate receipt key |
| `23502` | 1 | Missing creation timestamp |
| `23514` | 7 | Invalid ID, status, line, quantity, cents and receipt digest |
| `42501` | 10 | Unauthorized reader and writer operations, including cleanup by the reader and marker mutation by the writer |
| `22023` | 2 | False and null reset intent |
| `55000` | 5 | Wrong or null supplied UUID, missing marker, wrong stored OID, and wrong stored cluster identifier |
| `22012` | 1 | Deliberate error after cleanup had emptied all five relations within the transaction |

The OID control temporarily set `fixture.installation.database_oid` to `0` in an admin transaction, switched to writer authorization, and called cleanup with the correct UUID. It returned `55000: fixture cleanup refused: disposable database identity mismatch`. The error rolled back the temporary marker change. The later successful cleanup with the original identity confirmed the installation was usable.

The complete reader output below was identical before the negative probes, after repeat bootstrap and after the forced cleanup rollback. All three files had SHA-256 `10407a983a30790feecfd3e6ed43ef0e37a8b202b5ab804bdca632ea64cdaac2`.

```text
customers|[{"customer_id":901,"code":"C901","name":"Schema test","created_at":"2026-02-01T00:00:00+00:00","updated_at":"2026-02-01T00:00:00+00:00"}]
orders|[{"order_id":910,"customer_id":901,"order_ref":"O910","status":"open","created_at":"2026-02-01T00:00:00+00:00","updated_at":"2026-02-01T00:00:00+00:00"}]
order_items|[{"item_id":911,"order_id":910,"line_no":1,"sku":"Test","quantity":2,"unit_cents":0,"created_at":"2026-02-01T00:00:00+00:00","updated_at":"2026-02-02T00:00:00+00:00"}]
payments|[{"payment_id":912,"order_id":910,"payment_ref":"P912","amount_cents":0,"created_at":"2026-02-01T00:00:00+00:00","updated_at":"2026-02-01T00:00:00+00:00"}]
scenario_receipts|[{"fixture_version":"v1","seed":0,"scenario_id":"S04","payload_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]
```

After successful cleanup and commit, the reader returned the complete empty state below, identical to the initial post-bootstrap snapshot. The installation and ACLs remained intact.

```text
customers|[]
orders|[]
order_items|[]
payments|[]
scenario_receipts|[]
```

### Offline checks

The following commands passed in the ticket worktree.

```sh
make check BASE=origin/main
sh tests/repository-checks.sh
make test-unit
bash -n tests/integration/source-schema/run.sh
```

The repository checks exercised all five rejection paths. The branch unit suite passed 20 tests and the combined tree passed 23. A static check parsed 34 migration statements, all three verification SQL files, and the 33 statement probes and 5 literal SQL blocks in the Bash harness after removing `psql` directives and substituting a literal UUID. The same check matched every field of the documented S04 inserts to the independent S03-to-S04 fixture delta and reproduced the documented SHA-256 digest. [pglast 6.17](https://github.com/lelit/pglast/releases/tag/v6.17)

## Evidence artifacts

The migration, catalog and ordered row queries, expected probe rows, and acceptance runner retain the commands and expected values. Reviewed catalog output and the complete synthetic before and after rows are above. Raw transcripts, catalog captures, per-probe SQL, error diagnostics, row comparisons, role authentication logs and the exact guest launcher are retained outside Git under `cdc-issue21-vm/evidence-03` and `cdc-issue21-vm/media/run-issue21.sh` on the staging workstation. [Issue #21](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/21) · [Migration](../../sql/source/001_fixture_v1.sql) · [Acceptance runner](../../tests/integration/source-schema/run.sh)

## Interpretation, limitations and follow-up

The first console boot hit its 55 s deadline while the NIC-free guest was waiting for network-online. The next boot was stopped during the same wait to correct a local inspection assertion that compared the entire Compose network JSON object, which also includes an empty `ipam` field. Neither boot reached PostgreSQL. The successful run used a 175 s console deadline and checked the resolved network's name and external flag explicitly.

This run establishes the ticket 1.3 source prerequisites on the verified 1.2 environment. R02, R03 and R13 remain open. S00 reuse and S04 replay are exercised by tickets 1.5 and 1.7. Cross-system parity and visibility require downstream runs.
