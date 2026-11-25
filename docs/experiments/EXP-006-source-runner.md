# EXP-006 — Deterministic sequential source transactions

- **Date** 2026-11-25
- **Research question IDs** R02, R03, R13, R25
- **Status** Passed for ticket 1.5 source acceptance
- **Operator** Codex
- **Run ID** `20261125T115926Z-p01-04`, project `cdc-source-15-04`, volume `cdc-source-15-04_source-pg`
- **Tested revision** `4a743b1b15ce30ab8b3b58d49f82de1c66cd7b32`, based on `782c0a9983cf011683c7fc2ff2138fa4938521d1`
- **Software** PostgreSQL server and `psql` 16.16, CPython 3.12.12, Psycopg binary 3.2.13 with libpq 17.6, Docker Engine 29.1.3, Compose 2.40.3+ds1-0ubuntu1~24.04.1, cgroup v2, Ubuntu 24.04.5 LTS amd64, Linux 6.8.0-147-generic, and QEMU 8.2.2 with KVM

## Hypothesis

The sequential runner reproduces every v1/42 checkpoint against the independent 1.4 oracle. A new source snapshot sees all four S04 effects together after commit and sees exact S03 before commit or after failure. The guarded reset returns exact S00 and preserves the previous state on a fault after cleanup. Rejected input and predecessor mismatches leave rows intact. The generator stays within its 256 MiB and 0.5 CPU ceilings.

## Preconditions and verified documentation

Use a fresh QCOW2 overlay over the powered-off [ticket 1.2 VM](EXP-004-source-profile.md), booted with two vCPUs, 2048 MiB RAM and `-nic none`. Stage the Git tree and runner image on read-only media. Use the existing PostgreSQL image index `sha256:cd0e9518bda5f2ea667ff84d22795d089720c883f288e215d97ce57437e8ef37`, source bridge gate and schema migration. Enroll the fresh named volume during bootstrap and provision the scoped reader and writer roles over SCRAM.

Reviewed on 2026-11-25. The official Python image index digest is `sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c`, with linux/amd64 manifest `sha256:2986c55feb36e6cae00fa1fefb454283e4b33f35e75ff8bdd123b134130be301`. The pinned wheels cover CPython 3.12 on linux/amd64. Psycopg's transaction context commits on normal exit and rolls back on an exception. PostgreSQL provides both READ COMMITTED and per-transaction read-only REPEATABLE READ snapshots. The runner uses libpq connect timeouts, server-side statement and lock timeouts, and a GNU timeout around the process. [CPython 3.12.12](https://www.python.org/downloads/release/python-31212/) · [Official Python image](https://hub.docker.com/_/python) · [Psycopg 3.2.13](https://pypi.org/project/psycopg/3.2.13/) · [Binary wheels](https://pypi.org/project/psycopg-binary/3.2.13/) · [Transaction contexts](https://www.psycopg.org/psycopg3/docs/basic/transactions.html) · [PostgreSQL 16 isolation](https://www.postgresql.org/docs/16/transaction-iso.html) · [Client settings](https://www.postgresql.org/docs/16/runtime-config-client.html) · [libpq connection parameters](https://www.postgresql.org/docs/16/libpq-connect.html) · [GNU timeout](https://www.gnu.org/software/coreutils/manual/html_node/timeout-invocation.html)

Compose `run --no-deps` starts a one-shot container from the generator profile with the declared memory and CPU settings. The source uses the preflight and profile from tickets 1.1 and 1.2. Slot and publication counts are expected to stay zero. [Compose run](https://docs.docker.com/reference/cli/docker/compose/run/) · [Compose container settings](https://docs.docker.com/reference/compose-file/container-spec/) · [Linux cgroup v2](https://www.kernel.org/doc/html/v6.8/admin-guide/cgroup-v2.html)

## Procedure and expected results

1. Follow the [runner startup and staging procedure](../source-runner.md#stage-and-provision). Before applying the VM firewall rules, source startup must fail and leave the project without containers. Apply both address families' rules, rerun the gate and confirm health, the captured bridge ID, the fresh named volume and zero published ports. Sample WAL and available storage using the [1.2 stop thresholds](../source-profile.md#verify-limits-and-storage).
2. Run the [acceptance harness](../source-runner.md#reproduce-the-acceptance-suite) with both fixture roles. Expect empty checkpoint differences throughout S00–S04. Compare both customers' aggregates to the oracle and confirm item 102's addition and removal and both timestamps on item 101. For S04, read after staging and before writer exit, then take a fresh reader snapshot after commit or rollback. On failure, check all four business tables, both report rows and exact receipt contents.
3. Use a real SQL session to hold the sequential runner lock without writing. Confirm that the query of `pg_locks` shows one holder before timing the runner. Expect `55P03` within 10 s including Compose startup and the original S00 state afterward. Use the `admin_psql` array from [schema setup](../source-schema.md#bootstrap-and-role-setup) and the `fixture_runner` helper from the runner guide.

   ```bash
   "${admin_psql[@]}" -XqAt --set=ON_ERROR_STOP=1 \
     -c 'BEGIN; SELECT pg_advisory_xact_lock(1348076337, 15); SELECT pg_sleep(8); COMMIT;' &
   holder=$!
   lock_query="SELECT count(*) FROM pg_locks
     WHERE locktype='advisory' AND classid=1348076337 AND objid=15 AND granted;"
   for attempt in $(seq 1 25); do
       [ "$("${admin_psql[@]}" -XAtc "$lock_query")" = 1 ] && break
       sleep 0.2
   done
   test "$("${admin_psql[@]}" -XAtc "$lock_query")" = 1
   status=0
   time fixture_runner run S01 || status=$?
   wait "$holder"
   test "$status" = 1
   fixture_runner inspect S00
   ```

4. From the S00 left by the harness, run S01 through S04 again. Record the reader's S04 inspection JSON, cleanly stop the source and run `source_compose down` without volume deletion. Rerun the gate on the empty bridge and wait for health. Capture a new inspection through `fixture_runner inspect S04`. Compare its `rows`, `receipts` and `differences` fields to the pre-restart inspection. Expect byte-identical field values after canonical JSON serialization.
5. Record Docker and cgroup measurements for the S00 container. Expect Docker memory and memory-plus-swap both `268435456`, `NanoCpus=500000000`, `memory.swap.max=0`, CPU quota `50000 100000`, and no OOM events. Sample source storage again and stop the source using the runbook.

## Actual observations

### Source isolation and checkpoints

The disconnected guest began with loopback and Docker's default bridge and no default route. Without the bridge controls, the IPv4 and IPv6 host probes reached their test listeners and the gate blocked startup. With both firewall families installed, peer DNS/TCP passed, gateway requests timed out, routed probes returned `ENETUNREACH` and delegated DNS returned `ESERVFAIL`. The healthy source used the verified external bridge and had no published ports. PostgreSQL reported `logical|2|2|128MB|0|0` for WAL level, senders, slot cap, slot retention, publications and slots. Both fixture roles authenticated using SCRAM.

The fresh post-commit snapshots had zero differences against the literal oracle for every row and the report. The report values below are ordered as count and item cents. Item 101 kept `2026-01-01T00:00:00Z` as `created_at` throughout and carried `2026-01-01T00:02:00Z` as `updated_at` from S02. Item 102 first appeared with both timestamps at `2026-01-01T00:01:00Z` and was absent after S03.

| Snapshot | Item keys | Customer 1 | Customer 2 | Receipt count | Differences |
| --- | --- | --- | --- | --- | --- |
| S00 | 101, 201 | 1, 600 | 1, 500 | 0 | 0 |
| S01 | 101, 102, 201 | 1, 1100 | 1, 500 | 0 | 0 |
| S02 | 101, 102, 201 | 1, 1400 | 1, 500 | 0 | 0 |
| S03 | 101, 201 | 1, 900 | 1, 500 | 0 | 0 |
| S04 | 101, 201, 301 | 2, 1300 | 1, 500 | 1 | 0 |

### S04 and reset

The independent reader began a fresh read-only transaction for each observation. The flags are ordered as order 30, item 301, payment 302 and the S04 receipt. Both variants checked every observed value in addition to the flags.

| Variant / writer XID | Snapshot | Backend PID | Observed UTC | Visibility | Exact checkpoint |
| --- | --- | ---: | --- | --- | --- |
| Rollback / 750 | Writer staged | 286 | 12:00:16.512789Z | 1 1 1 1 | S04 |
| Rollback / 750 | Reader before rollback | 285 | 12:00:16.514574Z | 0 0 0 0 | S03 |
| Rollback / 750 | Reader after rollback | 285 | 12:00:16.516127Z | 0 0 0 0 | S03 |
| Commit / 751 | Writer staged | 289 | 12:00:19.631281Z | 1 1 1 1 | S04 |
| Commit / 751 | Reader before commit | 288 | 12:00:19.632859Z | 0 0 0 0 | S03 |
| Commit / 751 | Reader after commit | 288 | 12:00:19.642808Z | 1 1 1 1 | S04 |

The receipt key was `(v1, 42, S04)` and its digest was `4d2c11bd073069f7a4a9f38ba044d58219fad0c37ab3a2b43b300a97414432f8`. Both complete S04 reruns matched the initial S04. A separate read after forced rollback equaled S03, including all business columns, both report groups and the empty receipt table.

The forced reset fault saw the empty tables and empty receipt list inside the writer transaction. The independent reader then saw the original S04 values and receipt. Both successful resets started from exact S04 and reproduced exact S00, including the empty receipt list. The wrong UUID returned `55000` and left S04 unchanged. The checks rejected an unsupported scenario, seed, version, invalid rollback option and missing reset intent with exit 2. Skipped predecessors and repeated S01 or S04 failed with the expected checkpoint diagnostic and preserved the prior rows. The live lock probe returned `55P03` with `canceling statement due to lock timeout` in 2,840 ms, including container startup. A new inspection confirmed exact S00 afterward.

### Resource and durability measurements

The guest loaded runner image ID `sha256:6c7482d5572b3ac16a3530c2a7f5f0e3d058870b297fc965f26abcd2e68b2414` (linux/amd64). The S00 run's Engine inspection and in-process cgroup sample returned the following values.

```text
memory_bytes memory_swap_bytes nano_cpus pids oom_killed exit
268435456 268435456 500000000 32 false 0

memory.max       268435456
memory.swap.max  0
memory.peak      23379968
memory.events    low 0, high 0, max 0, oom 0, oom_kill 0, oom_group_kill 0
cpu.max          50000 100000
cpu.stat         usage_usec 253929, nr_periods 6, nr_throttled 3, throttled_usec 145769
ru_maxrss        39540 KiB
```

The source's WAL directory stayed at one 16 MiB segment (16,392 KiB allocated). The sampled data directory reached 47,576 KiB including WAL, with over 4.2 million KiB free. After a clean stop and container recreation with the same volume, the reader again matched exact S04, including the one S04 receipt. Canonical JSON of the ordered rows, receipt and differences had SHA-256 `78dd2a049b3868b030fbb4966bb7746e0372b67e496b4244ff4caa7ecfc90254` before and after recreation. The final source container exited 0 with no OOM. The guest removed its test firewall rules and bridge and ended with zero containers at `2026-11-25T12:01:09Z`.

### Other attempts and offline checks

The first launcher invocation pointed at the previous ticket's ISO filename and stopped before guest boot. Runs `20261125T115520Z-p01-02` and `20261125T115733Z-p01-03` reached the source checkpoints but the acceptance parser stopped on a Docker Compose warning about the retained one-shot container. Separating stdout from stderr and removing that container immediately after inspection corrected the harness. The accepted run used a fresh overlay and project.

```sh
make help check BASE=origin/main
sh tests/repository-checks.sh
make test-unit
bash -n tests/integration/source-runner/run.sh
```

The repository and shell regression checks passed, including all five negative regression cases. The offline unit suite passed 24 tests on CPython 3.12.3. These include the published digest assertion for the mutation payload. The four business-table and report fixtures are byte-identical to ticket 1.4.

## Evidence artifacts

The acceptance harness retains each source inspection, expectation diff, rejection and visibility trace. The successful raw outputs are in `cdc-issue23-vm-verified/review-04/evidence-04` on the staging machine, with the guest commands in `cdc-issue23-vm-verified/media/run-issue23.sh`. Prior transcripts are retained in `cdc-issue23-vm/review-02` and `cdc-issue23-vm-final/review-03`. [Issue #23](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/23) · [Acceptance harness](../../tests/integration/source-runner/run.sh) · [Independent v1 expectations](../../tests/fixtures/v1/expected.json)

## Interpretation and limitations

The independently visible S04 changes measure PostgreSQL source atomicity on the tested schedule. The wider R02, R03, R13 and R25 acceptance gates remain open for downstream visibility, concurrent source writers, ambiguous commit recovery and operational write-back. The local resource sample covers the bounded fixture and tested host. The clean restart tests source receipt persistence across recreation with the same volume.
