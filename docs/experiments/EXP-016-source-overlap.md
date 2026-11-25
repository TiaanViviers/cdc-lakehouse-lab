# EXP-016 — S05 ordered source overlap

- **Date** 2026-11-25
- **Research questions** R03, R13
- **Status** Passed for ticket 1.6 source acceptance
- **Operator** Codex
- **Run ID** `20261125T122652Z-p01-01`, project `cdc-source-16-01`, bridge `cdc-src16`, volume `cdc-source-16-01_source-pg`
- **Tested revision** `7b4c9f65c55c8ee8878647532a17b67eb7575164`, based on `3025ce3`
- **Software** PostgreSQL and `psql` 16.16, CPython 3.12.12, Psycopg binary 3.2.13, libpq 17.6, Docker Engine 29.1.3, Compose 2.40.3+ds1-0ubuntu1~24.04.1, cgroup v2, Ubuntu 24.04.5 LTS amd64, Linux 6.8.0-147-generic and QEMU 8.2.2 with KVM

## Hypothesis

On PostgreSQL 16, both disjoint S05 statements can finish while both transactions remain open. A read-only observer with fresh snapshots should see S04, A-only and S05 in that order. Withholding the first release should abort both writes. Interrupting after A's commit should leave a verifiable A-only state and permit recovery by guarded reset and replay to S04.

## Preconditions and verified documentation

Follow the [Phase 1 runtime baseline](EXP-004-source-profile.md) and [runner baseline](EXP-006-source-runner.md). Use a fresh QCOW2 overlay of the powered-off source VM with two vCPUs, 2048 MiB RAM and `-nic none`. Mount the application tree and runner archive from read-only media. Use a dedicated project name, verified internal bridge and fresh named volume. Run the source gate before bootstrapping the schema and provisioning the scoped fixture roles.

Reviewed on 2026-11-25. The existing PG16.16 image, CPython 3.12.12 digest and Psycopg 3.2.13 wheel hashes are retained. PostgreSQL 16 documents fresh per-transaction repeatable-read snapshots and the recent-XID results from `pg_xact_status(xid8)`. The exact Psycopg version exits the transaction context by committing on success or rolling back on error. CPython 3.12.12 implements timed barriers that break on expiry and can be aborted to wake the other party. A separate `pg_stat_activity` read can check that the fixture writer sessions are gone. [PostgreSQL 16 isolation](https://www.postgresql.org/docs/16/transaction-iso.html) · [XID status](https://www.postgresql.org/docs/16/functions-info.html) · [Session activity](https://www.postgresql.org/docs/16/monitoring-stats.html#MONITORING-PG-STAT-ACTIVITY-VIEW) · [Psycopg 3.2.13 transaction contexts](https://github.com/psycopg/psycopg/blob/3.2.13/docs/basic/transactions.rst) · [CPython 3.12.12 barriers](https://github.com/python/cpython/blob/v3.12.12/Lib/threading.py) · [Compose project names](https://docs.docker.com/compose/how-tos/project-name/)

## Procedure and expected results

1. Follow the [source isolation and startup procedure](../source-profile.md) using a dedicated project and bridge. Confirm the gate refuses the bridge without its IPv4 and IPv6 controls, then apply them and verify the gate, healthy source, named volume and unpublished ports. Use the [schema setup](../source-schema.md#bootstrap-and-role-setup) and [runner setup](../source-runner.md#stage-and-provision).
2. Run the sequential smoke suite and then the [ticket-specific harness](../source-overlap.md#reproduce-ticket-16).

   ```bash
   mkdir -p artifacts
   run_id="$(date -u +%Y%m%dT%H%M%SZ)-p01-01"
   bash tests/integration/source-runner/run.sh "$run_id" "artifacts/$run_id-sequential"
   bash tests/integration/source-overlap/run.sh "$run_id" "artifacts/$run_id-s05"
   ```

3. For each of four attempts the harness resets and reapplies S01–S04. It compares those S04 rows and the S04 receipt across runs. It requires three distinct backend PIDs, two distinct writer XIDs, exact snapshot data and the full event order. The expected source data comes from the [v1 oracle](../../tests/fixtures/v1/expected.json). The intermediate observation uses S05 for everything except payments, which still match S04.
4. The normal schedules, attempts 1 and 4, must both exit 0 with identical final rows, timestamps, report and receipt. The timeout (attempt 2) must exercise the four-second A barrier and exit 1 with exact S04 within 15 seconds including container startup. The partial failure (attempt 3) must exit 1 with status `partial_commit`, A committed, B aborted and exact A-only values. A fresh process inspects each final state. A separate administrative SQL connection checks that no fixture writer backends remain.
5. Sample source WAL and free disk against the [profile thresholds](../source-profile.md#verify-limits-and-storage). Retain the generated traces and stop the dedicated project using the source runbook.

## Actual observations

The gate blocked startup until the IPv4 and IPv6 bridge controls were installed. On the verified bridge, peer DNS/TCP passed, both gateway probes timed out, both routed families returned `ENETUNREACH` and delegated DNS returned `ESERVFAIL`. The source was healthy, bound to the verified bridge, and had no published ports. The loaded PostgreSQL index was `sha256:cd0e9518bda5f2ea667ff84d22795d089720c883f288e215d97ce57437e8ef37` and the runner image ID was `sha256:84329983772e45219e8b890193bfdc3816bf7c0ae3a97c3d01897115f7b194c2` (linux/amd64). Server logs showed both fixture roles authenticating with SCRAM. The existing sequential harness passed exact checkpoints, reset, fault and resource checks before the S05 runs.

Each run began at the same exact S04. The staged events came after the respective mutation statements returned. Attempt 1 produced this schedule, with transaction statuses queried from the independent observer and times in UTC.

| UTC | Observed boundary | PostgreSQL backend PID / XID or observer result |
| --- | --- | --- |
| 12:28:00.542297 | A staged item 101 update | `345 / 764` |
| 12:28:00.544310 | B staged payment 303 insert | `346 / 765` |
| 12:28:00.582150 | Observer 344 read exact S04 | A and B both `in progress` |
| 12:28:00.582396 | A barrier release | A commit requested at `12:28:00.582540` |
| 12:28:00.587520 | A commit acknowledged | `345 / 764` |
| 12:28:00.591246 | Observer 344 read exact S05-A | A `committed`, B `in progress` |
| 12:28:00.591367 | B barrier release | B commit requested at `12:28:00.591572` |
| 12:28:00.593358 | B commit acknowledged | `346 / 765` |
| 12:28:00.596771 | Observer 344 read exact S05 | A and B both `committed` |

These are the canonical SQL results for the affected keys and both report groups. Item values are ordered as `item_id, order_id, line_no, sku, quantity, unit_cents, created_at, updated_at`. Payment values are ordered as `payment_id, order_id, payment_ref, amount_cents, created_at, updated_at`. The report contains `(customer_id, order_count, item_total_cents)`.

| Checkpoint | Item 101 | Payment 303 | Report |
| --- | --- | --- | --- |
| S04, both open | `(101, 10, 1, A, 3, 300, 2026-01-01T00:00:00Z, 2026-01-01T00:02:00Z)` | absent | `(1, 2, 1300), (2, 1, 500)` |
| S05-A, B open | `(101, 10, 1, A, 4, 300, 2026-01-01T00:00:00Z, 2026-01-01T00:05:00Z)` | absent | `(1, 2, 1600), (2, 1, 500)` |
| S05, both committed | `(101, 10, 1, A, 4, 300, 2026-01-01T00:00:00Z, 2026-01-01T00:05:00Z)` | `(303, 10, P303, 200, 2026-01-01T00:05:00Z, 2026-01-01T00:05:00Z)` | `(1, 2, 1600), (2, 1, 500)` |

Every snapshot had zero full-row or report differences. Each contained the same one receipt for `(v1, 42, S04)` with digest `4d2c11bd073069f7a4a9f38ba044d58219fad0c37ab3a2b43b300a97414432f8`. The timeout withheld A's release and logged `S05 A commit barrier broke after 4000 ms (deadline 4 s)`. Neither commit was requested. The post-A fault logged `S05 injected failure after A commit and before B release` and reported `partial_commit`. A fresh inspection process confirmed each resulting checkpoint. The client trace showed both writer connections closed on every attempt, and the separate `pg_stat_activity` check found neither writer backend.

| Attempt | A PID / XID | B PID / XID | Observer PID | Exit / elapsed from Compose start | Final transaction status (A, B) |
| --- | --- | --- | ---: | --- | --- |
| 1, normal | `345 / 764` | `346 / 765` | 344 | 0 / 884 ms | committed, committed |
| 2, timeout | `369 / 771` | `370 / 772` | 368 | 1 / 4,911 ms | aborted, aborted |
| 3, after A | `401 / 778` | `402 / 779` | 400 | 1 / 970 ms | committed, aborted |
| 4, recovered from fresh S04 | `432 / 785` | `433 / 786` | 431 | 0 / 942 ms | committed, committed |

The harness compared the full canonical data directly, then recorded SHA-256 of the canonical JSON pair of rows and receipts. The two normal runs had identical intermediate and final data across distinct transactions. Attempt 4 recovered by guarded reset to S00 and replay to S04 before running S05.

| Canonical checkpoint | Observed SHA-256 |
| --- | --- |
| S04 from all fresh preparations and the timeout result | `4895e5ececd5588e1015ed05a792fd006aefef8a1be79a3813b4f52003d5ba73` |
| S05-A from both normal runs and the partial failure | `6fd61b14331e33fb2e65d942eff5bacd9f41561c2b68f5d28c677d34a2e5a8ff` |
| S05 from both normal runs | `f0707e57aed0c0871caad375f62fd8558f5fd6bbcba88b63192cc1a911c44c5e` |

S05 runner cgroups reported `memory.max=268435456`, zero swap, `cpu.max=50000 100000`, peak memory at most 23,793,664 bytes and no OOM events. The sequential runner Engine check also confirmed `NanoCpus=500000000` and 32 PIDs. The source reported `logical|2|2|128MB|0|0` for WAL level, senders, slot cap, slot retention, publications and slots. It used one 16 MiB WAL segment (16,392 KiB allocated), reached 47,576 KiB including WAL, and retained 4,246,280 KiB free at the end. The source stopped with exit 0 and no OOM. The ticket's two firewall rules per family and its isolated bridge were removed, and the disconnected guest powered off.

Offline checks passed with CPython 3.12.3 and all 24 unit tests. Repository regression checks passed all five negative cases.

```sh
make help check BASE=origin/main
make test-unit
sh tests/repository-checks.sh
bash -n tests/integration/source-runner/run.sh
bash -n tests/integration/source-overlap/run.sh
```

## Evidence artifacts

The review bundle is stored on the staging machine at `~/cdc-issue24-evidence/20261125T122652Z-p01-01.tar.gz`, SHA-256 `ebe23c6bfbc22220881c9766fef058730a8653484d01d537f0b82243aef7d62e`. It contains `overlap/{1,2,3,4}-overlap.jsonl` with the complete canonical query results and schedule, the post-run independent inspections, the backend-catalog probes, the two isolation gate logs and the source log excerpt. The guest command script is alongside the bundle as `run-issue24.sh`. [Issue #24](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/24) · [S05 harness](../../tests/integration/source-overlap/run.sh) · [Snapshot SQL](../../scripts/source/checkpoints.py)

## Interpretation and limitations

R03 and R13 gained PostgreSQL source evidence for the controlled S05 schedule. The barriers fix the staging, observation and commit order while both transactions can hold their writes open. The tested partial result is consistent with a failure between two independent commits. The acceptance conditions for replicated visibility and consistent lake cutoffs remain open. Conflicting writes, connection loss during commit and downstream cutoff behavior require different experiments.
