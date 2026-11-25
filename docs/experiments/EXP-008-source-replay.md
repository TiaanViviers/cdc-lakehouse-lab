# EXP-008 — S04 receipt replay and ambiguous outcome recovery

- **Date:** 2026-11-25 UTC
- **Status:** Passed
- **Research questions:** R03 and R25, source fixture rehearsal
- **Operator:** Codex on a disposable local VM
- **Branch:** `feature/1.7-s06-replay`, based on `3025ce3` from `origin/main`
- **Software:** PostgreSQL 16.16 Bookworm, CPython 3.12.12, Psycopg 3.2.13 binary wheel, Docker Engine 29.1.3, Compose 2.40.3+ds1-0ubuntu1~24.04.1

## Hypothesis

A transactional source receipt can identify a committed S04 across retries and concurrent deliveries. Every successful S06 resolution returns the original S04 receipt. Only the claimant that inserts that receipt can commit the three S04 business rows. A caller unable to read the receipt after an interrupted delivery receives an unknown outcome.

## Preconditions and verified documentation

Fixture v1/seed 42 uses the [unchanged S04 payload, digest and receipt schema](../source-schema.md#receipt-contract-for-tickets-15-and-17). Use the pinned amd64 PostgreSQL [source image](../compatibility-matrix.md#image-provenance) and the hash-locked [runner build](../../scripts/source/runner.Dockerfile). The existing exclusive advisory guard continues to cover sequential writes and reset. The new S06 write path takes a shared transaction lock on the same key, which admits competing S06 claims. The operator pauses reset across the experiment, including between processes.

Reviewed on 2026-11-25 for PostgreSQL 16.16 and Psycopg 3.2.13. Under `READ COMMITTED`, `INSERT ... ON CONFLICT DO NOTHING RETURNING` may decline an insert due to a row committed by a concurrent transaction, and the next statement reads a new snapshot. Psycopg's transaction context sends `COMMIT` upon normal exit. PostgreSQL's `pg_blocking_pids` identifies blockers, and `xmin` identifies the inserting transaction for a visible tuple version in this short-lived database. A nonzero `pg_terminate_backend` timeout waits for actual backend exit. [PostgreSQL 16 `INSERT`](https://www.postgresql.org/docs/16/sql-insert.html) · [Isolation](https://www.postgresql.org/docs/16/transaction-iso.html) · [Backend and lock functions](https://www.postgresql.org/docs/16/functions-info.html) · [`pg_terminate_backend`](https://www.postgresql.org/docs/16/functions-admin.html) · [System columns](https://www.postgresql.org/docs/16/ddl-system-columns.html) · [Psycopg 3.2.13 transaction implementation](https://github.com/psycopg/psycopg/blob/3.2.13/psycopg/psycopg/transaction.py)

## Procedure and expected results

1. Follow [runner staging](../source-runner.md#stage-and-provision) and [source startup](../source-profile.md#stage-and-start) with a fresh Compose project and volume in a VM with no NIC. Run the negative gate before installing the bridge rules, then apply them and rerun the gate. Verify health, the full registered bridge ID, zero port bindings, authenticated fixture roles and disk thresholds.
2. Bootstrap and enroll the volume as described in [schema setup](../source-schema.md#bootstrap-and-role-setup). Run the ticket 1.5 regression harness on empty tables first. Run the replay harness below. It takes an independent read-only repeatable-read snapshot before and after each variant, compares all four tables and both aggregate rows to the literal oracle, and compares the entire ordered receipt table to the independently recorded receipt. It also compares tuple versions when state should be unchanged and checks that the three new rows and receipt share the winning transaction ID.
3. Use the staged runner's trace immediately before transaction context exit for the pre-commit fault. The independent reader should see S03 while the writer is paused and after the runner is killed. A fresh runner first reads an absent receipt, then applies S04 once. For the post-commit case, block the runner immediately after the context returns and before it can emit its result. Independently observe S04 before killing that process. A fresh runner should return the receipt without a claim or changes.
4. For overlap, hold the first process before commit and start the second. Poll for the second `INSERT` to be blocked by the first PID before releasing the first. The second should read the winning receipt after the conflict, and the only changes should be the intended S04 rows and receipt.
5. For the recovery error path, inject a client error after PostgreSQL commits and make the child's next reader connection target an unused loopback port. Expect exit 1 and `unknown`, zero additional claims, and independently visible S04. Run a fresh normal attempt afterward to reconcile. Also terminate the writer backend before commit to test retry after a receipt miss and termination of both deliveries to test exhaustion.

```bash
make help check BASE=origin/main
make test-unit
sh tests/repository-checks.sh
bash -n tests/integration/source-replay/run.sh
mkdir -p artifacts
run_id="$(date -u +%Y%m%dT%H%M%SZ)-p01-01"
bash tests/integration/source-runner/run.sh "$run_id" "artifacts/$run_id-runner"
bash tests/integration/source-replay/run.sh "$run_id" "artifacts/$run_id-replay"
```

The per-connection limits are 3 s connect, 5 s statement, 2 s lock and 15 s idle in transaction. A normal runner invocation has a 45 s process deadline and 2 s kill grace. The experiment uses at most 8 s per barrier and 12 s per child exit wait. It polls at 20 ms and requires evidence of the claim block within a 1.5 s observation window. Its outer timeout is 120 s with a 2 s kill grace. Application retry permits at most two write deliveries with a receipt read after each interruption. The [source thresholds](../source-profile.md#verify-limits-and-storage) apply before and after the run.

## Actual observations

Run `20261125T122741Z-p01-01` used implementation commit `b69e5dc293dc0ac507dec726bc66abefbf2382d1`, new Compose project `cdc-source-17-01`, bridge `cdc-src17`, and volume `cdc-source-17-01_source-pg`. QEMU 8.2.2 used KVM, two vCPUs, 2 GiB RAM and `-nic none` with a dedicated disk overlay on the completed 1.2 VM base. The guest booted Ubuntu 24.04.5 on kernel 6.8.0-147-generic with no IPv4 or IPv6 default route. Docker used the iptables backend and cgroup v2. The negative gate blocked startup when both test listeners were reachable. After installing the documented bridge rules in both families, peer DNS and TCP passed, host IPv4 and IPv6 probes timed out in 1.59 s, routed probes got `ENETUNREACH`, and delegated DNS returned `ESERVFAIL`. The source became healthy on the verified bridge with no published ports and both fixture roles authenticated using SCRAM.

The PostgreSQL Engine image ID was `sha256:cd0e9518bda5f2ea667ff84d22795d089720c883f288e215d97ce57437e8ef37`. The loaded amd64 runner image ID was `sha256:c15f7be14f70ea146bd8994b4e4bf46e00eeafb0a336471454c26432a659b426`, with Psycopg's binary implementation and libpq 17.6. PostgreSQL reported `logical|2|2|128MB|0|0` for WAL level, sender limit, slot limit, slot WAL retention, publication count and slot count. The source ended at 47,576 KiB allocated including 16,392 KiB of WAL, with 4,246,804 KiB free. The sampled source memory was 69.24 MiB of its 768 MiB limit. The replay container showed `memory.max=268435456`, `memory.swap.max=0`, `cpu.max=50000 100000`, a sampled peak of 71,917,568 bytes, and zero OOM events. The source stopped with exit 0 and no OOM. Cleanup removed this run's containers, volume and bridge and undid its four rules by 12:29:13 UTC.

### Receipt and row comparisons

The experiment completed 41 runner invocations in 24.020 s and all 21 complete snapshots had zero differences. The values below are ordered by fixture primary key. Both customer rows, every existing business row and the T02 update to item 101 were preserved across each S03→S04 transition. Item 102 remained absent. In each unchanged pair the entire ordered dataset and receipt list also matched directly, including the recorded `xmin` for every row.

| Checkpoint | Customer IDs | Order IDs | Item IDs | Payment IDs | Report `(customer, orders, cents)` | Receipt keys |
| --- | --- | --- | --- | --- | --- | --- |
| S03 | 1, 2 | 10, 20 | 101, 201 | 301 | `(1, 1, 900)`, `(2, 1, 500)` | empty |
| S04 | 1, 2 | 10, 20, 30 | 101, 201, 301 | 301, 302 | `(1, 2, 1300)`, `(2, 1, 500)` | `(v1, 42, S04)` |

The entire S04 delta was order `(30, 1, O30, paid)`, item `(301, 30, 1, C, 2, 200)`, payment `(302, 30, P302, 400)` and the receipt `(v1, 42, S04, 4d2c11bd073069f7a4a9f38ba044d58219fad0c37ab3a2b43b300a97414432f8)`. Both timestamps on each new business row were `2026-01-01T00:04:00Z`. Item 101 kept `created_at` at `2026-01-01T00:00:00Z` and `updated_at` at `2026-01-01T00:02:00Z`. Across committed variants, each new tuple and its receipt shared the winning writer XID.

Canonical compact JSON of `rows` (all four business tables and the report) plus `receipts`, with sorted object keys and the ordered SQL result arrays, produced SHA-256 `08d527b63853e9a19dc9acac54649265616434315d0c75b7c29bd4991eea4932` for every S03 sample and `194fa3977a7db46d8a8d332d8dfc73747a75b4e453ea1e8b38118c76483566e8` for every S04 sample. The tuple versions are recorded alongside these fields and compared within each variant.

### Attempt trace

The IDs below are attempt numbers within this one run. Each S06 attempt used the same receipt key. Where one attempt tried again internally, `delivery` identified its write transaction.

| Variant | Attempt and boundary | Observed outcome and exact compare |
| --- | --- | --- |
| Committed replay | S04 attempt 5 committed XID `763` on PID `333` at 12:28:49.831436 UTC. S06 attempt 6 read on PID `335`. | Returned the S04 receipt with `resolution=receipt` and no claim. `existing-committed` and `existing-after` were equal. |
| Payload mismatch | Attempt 7 kept the key and changed payment 302 from 400 to 401 cents. Its submitted digest was `a01e11c7cc6c23eec7b04ed9fccabf7423877c024b1cd280baec139b21dbac80`. | Exit 1 with `receipt_mismatch`. The stored digest was the original, with no claim. `mismatch-after` equaled `existing-committed`. |
| Runner killed before commit | Attempt 12 paused after staging all inserts on PID `358`/XID `768` at 12:28:53.872313 UTC. The parent observed S03 and sent `SIGKILL` before transaction exit. | The held and interrupted snapshots equaled the S03 baseline, with no receipt. Attempt 13 looked up the miss on PID `361` and committed once on PID `362`/XID `769`, producing exact S04. |
| Runner killed after commit | Attempt 18's commit returned at 12:28:57.360193 UTC on PID `375`/XID `774`. An independent reader saw S04 before the parent sent `SIGKILL`. The child had not emitted its outcome. | Attempt 19 read the matching receipt from PID `377` and did not claim. `postcommit-recovered` equaled `postcommit-before-ack`, including all four new tuples at XID `774`. |
| Overlap on the receipt | Both initial lookups missed. At 12:29:01.347369 UTC PostgreSQL showed the receipt `INSERT` from attempt 25/PID `401` waiting on a `transactionid` lock held by attempt 24/PID `398`. | Releasing attempt 24 committed XID `779`. Attempt 25 read the matching receipt in a separate statement after its claim returned no row, and returned `resolution=receipt`. The final S04 delta had one tuple of each expected kind, all at XID `779`. |
| Automatic retry and exhaustion | Attempt 30 delivery 1 was terminated at `commit_requested` on PID `414`/XID `784`. Attempt 35 lost both staged deliveries on XIDs `790` and `791`. | Both tests received SQLSTATE `57P01`. Attempt 30 looked up the miss on fresh PID `416` and delivery 2 committed exact S04 at XID `785`. Attempt 35 used its two deliveries and three receipt lookups, exited 1 with `unknown`, and its final S03 equaled its baseline. |
| Reconciliation unavailable | Attempt 40 committed at 12:29:10.457626 UTC on PID `446`/XID `796`. The injected client failure forced its next reader connection to unused container loopback port `1`, which refused the connection. | Exit 1 with `receipt_lookup_failed` and `status=unknown`, after one claim. Independent SQL confirmed exact S04. Attempt 41 read the matching receipt on PID `457` without a claim. `unavailable-after` equaled `unavailable-committed`. |

The [ticket 1.5 harness](../../tests/integration/source-runner/run.sh) also passed its checkpoint, reset, rejection, visibility and resource assertions in this disposable project before the replay experiment. The offline suite passed all 24 tests on CPython 3.12.3. `make check BASE=origin/main`, the five repository check regression cases, and `bash -n tests/integration/source-replay/run.sh` passed.

## Evidence artifacts

The staging machine retains `cdc-issue25-vm.6ONOd65V/review-01/evidence-01` and the archive `cdc-issue25-vm.6ONOd65V/evidence-01.tar.gz` under the operator's home directory. The archive SHA-256 is `3c1b8b8002d55fb20022353d41e1f7618b44af51bc22b59bb969f38f1f6b4a33`. `replay/*.json` holds the ordered row, report, receipt and tuple-version snapshots. `replay/*.jsonl` holds receipt lookups and run, attempt, delivery and backend IDs. `replay/overlap-source-wait.json` holds the blocker observation. `observations.log`, `gate-*.log` and the resolved Compose files contain the local setup and teardown observations. The VM launcher and its guest procedure were retained in the same staging directory. [Issue #25](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/25) · [Replay harness](../../tests/integration/source-replay/run.sh) · [Independent fixture expectations](../../tests/fixtures/v1/expected.json)

## Interpretation and limitations

**Passed.** A matching receipt provided positive evidence of the original committed S04. Before-commit loss left no business effects or receipt, and the next delivery committed one transaction. After-commit loss and concurrent duplicate delivery preserved the same S04 effects, receipt and tuple versions. A failed lookup preserved an explicit unknown outcome. The two kill windows were after staging and after Psycopg's successful `COMMIT` returned to the runner, before its application acknowledgement. Wire-level interruption during `COMMIT`, continuous traffic and server failover remain open experiments.

The shared interfaces added by 1.7 are the `run S06` selection, runner image packaging and the named constant for the existing sequential advisory lock key. Existing transaction and checkpoint function signatures, schema and fixture expectations remain compatible with the 1.5 harness. R03 and R25 remain open at full scope. The ordered S05→S06 check belongs to ticket 1.8. Phase 6 exercises operational write-back with its own receipt contract.

## Recheck after merging ticket 1.6

Run `20261125T130525Z-p01-02` used merge commit `e298763`, fresh project `cdc-source-17-02` and bridge `cdc-src17m` in a separate VM overlay. The staged `v1-1.7-merge` image included both S05 and S06 modules with the same dependency pins. Its guest image ID was `sha256:4943252833777c83625c654bebe643a0e4a58ff351f22fbc177810da8890b9dc` on amd64. The isolation gate and teardown both passed.

The existing S00–S04 harness and all four attempts of the [S05 overlap harness](../../tests/integration/source-overlap/run.sh) passed. The [S06 harness](../../tests/integration/source-replay/run.sh) passed again in 22.788 s across 41 runner invocations, with zero differences in all 21 snapshots and the same S03 and S04 digests above. All 24 offline unit tests and local repository checks passed.

After the S05 harness left exact S05, separate CLI invocations ran `inspect S05`, `run S06` and `inspect S05` as attempts `42`, `43` and `44`. Attempt `43` looked up the receipt from backend `574` and returned `committed` with `resolution=receipt` and no claim. The before and after inspectors had zero differences and identical ordered rows and receipts. Both reports had `(1, 2, 1600)` and `(2, 1, 500)`. Canonical `rows` plus `receipts` had SHA-256 `66a72149e4879265a030ae3abe0f23897d1244409f4bd2f4c92e08a0466e7339` before and after. Raw evidence is under `cdc-issue25-merge-vm.35rLw2JH/review-02/evidence-02` on the staging host, with the three CLI traces in `merged-*.jsonl`. This smoke check verifies that the two ticket branches work together through the merged CLI. The repeatable full source gate belongs to 1.8.
