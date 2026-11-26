# EXP-009 — Complete Phase 1 source gate

- **Date:** 2026-11-25 (UTC)
- **Research question IDs:** R02, R03, R04, R05, R13, R16, R25
- **Status:** passed. The Phase 1 technical source gate is met.
- **Operator:** Codex in the dedicated local lab VM for ticket 1.8
- **Git commit / branch:** `efea9f3b24f51570a6d13d6b7a3a9edbcde3f827` on `research/1.8-source-gate`, based on `f31d3ccef58e06f88427acffdd864be37117163f` from `origin/main`
- **Software / image versions:** PostgreSQL and `psql` 16.16, PostgreSQL Bookworm index `sha256:cd0e9518bda5f2ea667ff84d22795d089720c883f288e215d97ce57437e8ef37`, with linux/amd64 manifest `sha256:d755a91aff87574a57060f86ecc0d55f83ccb51ceec6ec6f904c1210d018d998`. The runner uses CPython 3.12.12 on Bookworm, base index `sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c`, and Psycopg binary 3.2.13 from the [hash-locked requirement file](../../scripts/source/runner.requirements.txt).

## Hypothesis

The integrated v1 / seed 42 workload and fault cases reproduce their prescribed committed source states on two freshly enrolled, isolated sources. Both customers' reports and every business row match at each checkpoint. S04's receipt records one application and survives S06 unchanged. Guarded reset returns exact S00. Source isolation, authentication and resource use meet the previously declared bounds.

## Preconditions

The [ADR-001 controls](../decisions/ADR-001-phase-1-source-baseline.md) apply. The guest runs from a fresh QCOW2 overlay over the powered-off [ticket 1.2 VM](EXP-004-source-profile.md). QEMU has two vCPUs, 2 GiB RAM and `-nic none`. Stage the pinned source and runner images and the checked-out repository by read-only media. Use a separate project, bridge, volume, schema enrollment and local credentials for each run. Fixture expectations are the [unchanged v1 file](../../tests/fixtures/v1/expected.json).

**Verified documentation, 2026-11-25.** PostgreSQL 16 provides read-only repeatable-read transactions, separate insert/write/flush WAL positions and SCRAM-required client connections. Slot retention is evaluated at checkpoints and the WAL size setting is a soft target. Docker documents port publication, rules for forwarded traffic, and memory accounting for container statistics. The cgroup files used here distinguish enforced quotas, peaks and total usage. [PostgreSQL transaction modes](https://www.postgresql.org/docs/16/sql-set-transaction.html) · [WAL functions](https://www.postgresql.org/docs/16/functions-admin.html) · [WAL settings](https://www.postgresql.org/docs/16/runtime-config-wal.html) · [Replication settings](https://www.postgresql.org/docs/16/runtime-config-replication.html) · [libpq authentication](https://www.postgresql.org/docs/16/libpq-connect.html) · [Docker ports](https://docs.docker.com/engine/network/port-publishing/) · [Docker iptables](https://docs.docker.com/engine/network/firewall-iptables/) · [Docker stats](https://docs.docker.com/reference/cli/docker/container/stats/) · [Linux 6.8 cgroup v2](https://www.kernel.org/doc/html/v6.8/admin-guide/cgroup-v2.html)

## Procedure

1. Follow the [source gate setup and teardown](../source-gate.md). Try `python3 scripts/isolation/preflight.py --start-compose compose.source.yaml` on each actual bridge before its firewall rules and again once both families' rules are active. Inspect the resolved configuration, running network ID, volume and health. Use a disposable empty schema with the two enrolled roles.
2. Run `RUN_ID="$run_id" EVIDENCE_DIR="artifacts/$run_id" make test-integration`. The target compares independent `psql` snapshots, records WAL and storage samples, and invokes the original schema, sequential, overlap and replay fault suites. Read the emitted evidence, stop the source, record the exit state, and repeat in a fresh disposable VM overlay and project. Compare the canonical hashes across runs.
3. Follow the [read-only S04 walkthrough](../source-gate.md#read-only-s04-inspection-in-psql) and inspect the receipt. Run the offline checks independently.

   ```sh
   make help check BASE=origin/main
   make test-unit
   sh tests/repository-checks.sh
   find tests/integration -name '*.sh' -exec bash -n {} \;
   ```

## Expected results

The missing-rule control prevents startup. With both firewall families installed, peer DNS/TCP succeeds and host, routed and delegated DNS probes are denied. The source is healthy without published ports, role authentication succeeds over the approved bridge, and bad passwords and reader writes fail. Effective SQL and container limits match the runbook. Every publisher sample has zero publications and slots.

Every keyed checkpoint and report comparison returns zero differences, with item 102 absent from S03 onward. S04 changes order 30, item 301, payment 302 and the receipt atomically. Constraint and rollback faults preserve the expected committed checkpoint. The S05 fault paths preserve the exact S04 or A-only state as specified. S06 replay reconciles committed effects once, with an explicit unknown outcome on unrecoverable receipt lookup or exhausted retry budget. Full S05 and S06 SQL snapshots match, including the S04 receipt's tuple version. Both resets recover exact S00, and the second complete suite succeeds independently.

## Actual observations

| Run ID | Fresh Compose project and volume | Source bridge ID prefix | Integration UTC | Result |
| --- | --- | --- | --- | --- |
| `20261125T155531Z-p01-02` | `cdc-source-18-02`, `cdc-source-18-02_source-pg` | `378535cfa21c` | 15:55:57–15:58:11 | Exit 0, 11 independent comparisons, all fault suites passed |
| `20261125T155701Z-p01-03` | `cdc-source-18-03`, `cdc-source-18-03_source-pg` | `ab5223775a99` | 15:57:27–15:59:32 | Exit 0, 11 independent comparisons, all fault suites and the read-only walkthrough passed |
| `20261125T160439Z-p01-04` | `cdc-source-18-04`, `cdc-source-18-04_source-pg` | `a47d6195ca37` | 16:05:03–16:07:07 | Exit 0, 11 independent comparisons, all fault suites and the read-only walkthrough passed |

The 11 independent snapshots in each run cover baseline, after schema checks, S00–S06 and both resets. All 33 comparison arrays were empty. Runs 02 and 03 overlapped in wall-clock time on separate guests. Run 04 started after both had finished and their guests had powered off. Direct comparisons between runs matched all business rows, timestamps, both report rows and receipt keys/digests at corresponding checkpoints. Each source stopped with exit 0 and no OOM. Teardown removed that run's container, volume, bridge and four per-bridge rules. All three guests ended with only the default Docker networks and no containers.

### Tooling and initial attempt

The first isolated VM attempt, `20261125T155344Z-p01-01`, completed the network gate, database startup and schema enrollment. Its minimal guest lacked GNU Make. The launcher returned 127 before the integration entry point ran. The source stopped cleanly and the project volume and bridge were removed. For the subsequent attempts, GNU Make 4.3 was staged on the read-only ISO from the Ubuntu 24.04 staging host. The tested repository commit and all fixture expectations stayed the same.

The local offline check ran under CPython 3.12.3, Git 2.43.0 and GNU Make 4.3. All 24 unit tests and the repository checks passed, including all five negative regression cases and shell syntax checks for the integration runners. With no project variables, the integration entry point refused to run before contacting Docker. Separate synthetic edits to in-memory copies of expected snapshots confirmed the integration comparator reported a duplicate order key, residual item 102, a one-microsecond timestamp change and an incorrect total for customer 2. The expected fixture on disk was preserved.

### Isolation and authentication

The guests used Ubuntu 24.04.5 LTS amd64, kernel 6.8.0-147-generic, QEMU 8.2.2 with KVM, Docker Engine 29.1.3 with the containerd store and cgroup v2, Compose 2.40.3+ds1-0ubuntu1~24.04.1, Bash 5.2.21, and iptables and ip6tables 1.8.10 using the nf_tables frontend. Only loopback and the default Docker bridge were present before local provisioning. Neither address family had a default route. The three successful tests used loaded runner image ID `sha256:4943252833777c83625c654bebe643a0e4a58ff351f22fbc177810da8890b9dc` on linux/amd64 with libpq 17.6.

Before adding the IPv4 and IPv6 rules, both controlled gateway listeners returned their marker and the startup gate refused to create the source container. After the rules, peer Docker DNS and TCP returned the marker in 0.08–0.12 s, and the controlled host IPv4 and IPv6 probes returned `ETIMEDOUT` in 1.58–1.59 s. The LAN, VPN and off-bridge IPv6 probes returned `ENETUNREACH`. Delegated DNS returned `ESERVFAIL` while a direct query to the local DNS fixture returned `172.19.0.2`. The running source was healthy on only the verified internal bridge and the project-labeled volume. Docker reported no published ports.

TCP clients using both fixture roles returned their expected identity, `source_lab` and a non-null client address over the source bridge. The server logged `method=scram-sha-256` against HBA line 124. Both deliberately incorrect passwords returned `password authentication failed`. The ordered HBA view showed seven entries, all SCRAM with zero parse errors. Loopback used HBA line 115. The live role attempts complement the SQL grant checks run under session authorization.

### Full keyed checkpoints

A separately authenticated reader took one read-only snapshot per checkpoint. Its SQL counted orders and summed item values separately for each customer. The comparator checked both directions by primary key and compared every field to the fixture, including UTC timestamps. The hashes below represent ordered business rows, both report rows and receipt values. Tuple XIDs are recorded separately.

| Checkpoint | Customer 1 (orders, cents) | Customer 2 (orders, cents) | Canonical SHA-256 |
| --- | ---: | ---: | --- |
| S00 and reset | (1, 600) | (1, 500) | `6098d01caf7396260dbc477734866772007ea3310382776c3fd0c689c4e6c692` |
| S01 | (1, 1100) | (1, 500) | `b64bdd2273984d0698e58c4b7d8b3b4c79d45dbba6caa6d9cb37ed15859750fe` |
| S02 | (1, 1400) | (1, 500) | `5e43cbdb4a5ed8565da58c88ce4f9b5066b85c48fa9158a8e3ddbb60683f8c34` |
| S03 | (1, 900) | (1, 500) | `08d527b63853e9a19dc9acac54649265616434315d0c75b7c29bd4991eea4932` |
| S04 | (2, 1300) | (1, 500) | `194fa3977a7db46d8a8d332d8dfc73747a75b4e453ea1e8b38118c76483566e8` |
| S05 and S06 | (2, 1600) | (1, 500) | `66a72149e4879265a030ae3abe0f23897d1244409f4bd2f4c92e08a0466e7339` |

Item 102 was present at S01 and S02 and absent from S03 through S06. Item 101 retained `created_at=2026-01-01T00:00:00Z` when its quantity changed to 3 at T02 and 4 at T05. At S06 the key sets were customers {1, 2}, orders {10, 20, 30}, items {101, 201, 301} and payments {301, 302, 303}. S04, S05 and S06 held the receipt `(v1, 42, S04, 4d2c11bd073069f7a4a9f38ba044d58219fad0c37ab3a2b43b300a97414432f8)` with the same tuple XID within each run. A direct comparison of the complete S05 and S06 snapshots matched. The receipt relation held zero S06 rows.

### Failure and recovery

The unchanged schema harness made 37 negative probes per run. It compared the complete ordered rows and receipts to the pre-fault snapshot after each one. Foreign key and restricted-delete failures returned `23503`, duplicate business and receipt keys `23505`, null timestamps `23502`, and other invalid values `23514`. The reader's attempted updates, receipt inserts and cleanup returned `42501`, as did the tested prohibited writer operations. False or null reset intent returned `22023`. A wrong or null UUID, missing installation marker, or mismatched stored database OID or cluster identity returned `55000`. The orphan-payment transaction's staged receipt rolled back with the violation. Explicit cleanup followed by division by zero returned `22012` and preserved the original rows and receipt. Repeat bootstrap preserved catalog/grants and committed cleanup returned to empty.

| Case | Observed outcome |
| --- | --- |
| S04 atomic commit and rollback | The writer observed all three business rows and the receipt staged. A separate backend saw none and exact S03 while open. It saw all four and exact S04 after commit. For the rollback case it again saw exact S03 and no receipt afterward. In run 02 the ordered S04 committed with XID 767 on PID 1155, and the rollback case aborted XID 776 on PID 1336. |
| Guarded CLI reset | Omitted `--confirm` returned exit 2. A wrong UUID returned `55000`. Failure after cleanup returned exit 1 and fully restored S04, including its receipt. Both successful integration resets produced exact S00 with no receipts. |
| S05 normal overlap | In run 02 observer PID 1187 saw writer XIDs 768 and 769 both in progress, then 768 committed and 769 still in progress, then both committed. Exact SQL state moved through S04, A-only and S05. At A-only, item 101 was quantity 4 at T05, payment 303 was absent, and both reports were (2, 1600) and (1, 500). B's commit made payment 303 visible at T05. |
| S05 barrier timeout and partial commit | With A held until the four-second barrier expired, both transactions aborted and a separate read matched S04. The partial fault left A committed, B aborted and exact A-only rows. Both faults exited 1. The timeout took 4,935, 4,855 and 4,885 ms from Compose startup, below the 15 s harness deadline. The partial fault took 998, 910 and 923 ms. The independent catalog checks found zero writer backends. Guarded reset and forward replay produced the same S05 again. |
| S04 loss before commit and after commit | Attempts 12 and 18 were killed before and after database commit, respectively. The first left exact S03 and no receipt, then attempt 13 applied S04 once. The second left exact S04 before the application acknowledgement, then attempt 19 used the original receipt and preserved all rows and tuple versions. |
| S04 overlap and mismatched input | Attempts 24 and 25 initially missed the receipt. In run 02 PostgreSQL showed PID 1644 waiting on PID 1641 at a `transactionid` lock during its claim. The first writer committed. The second resolved the matching receipt without applying writes. Different payload at the same key was rejected with the original state intact. |
| Automatic retry and explicit unknown | Terminating the writer returned `57P01`. A fresh receipt miss let attempt 30 commit on delivery 2. Terminating both deliveries exhausted attempt 35 and returned exit 1 with `unknown` and exact S03. For attempt 40 the commit succeeded, then the receipt reader's connection to an unused container loopback port failed. It returned exit 1 with `unknown` after one claim. The independent reader still observed exact S04. Attempt 41 recovered from the existing receipt without changing rows or tuple versions. |

The replay suite ran 41 runner invocations per run, in 24.339, 23.236 and 23.476 s. Each produced 21 matching complete snapshots and retained row and receipt tuple IDs. In the ordered S05→S06 run, attempt 907 resolved the receipt from a new reader backend without a write claim. Receipt `xmin` was 767 at S04, S05 and S06 in all three freshly initialized clusters.

### WAL and resource observations

The effective source configuration was `wal_level=logical`, `max_wal_senders=2`, `max_replication_slots=2`, `max_slot_wal_keep_size=128MB`, `wal_keep_size=0`, `min_wal_size=32MB`, `max_wal_size=128MB`, `checkpoint_timeout=300s` and `archive_mode=off`. PostgreSQL used 16 MiB WAL segments, 20 connections, 128 MiB shared buffers and connection logging to Docker. Each run had zero publications and zero replication slots at all 14 samples.

| Run | Source label / UTC | Insert LSN | Write LSN | Flush LSN |
| --- | --- | --- | --- | --- |
| 02 | baseline / 15:56:00.196154 | `0/19A1B28` | `0/19A1AE8` | `0/19A1AE8` |
| 02 | after-S04 / 15:56:23.482232 | `0/19E3D98` | `0/19E3D98` | `0/19E3D98` |
| 02 | after-S05 / 15:56:25.226672 | `0/19E3F80` | `0/19E3F80` | `0/19E3F80` |
| 02 | after-S06 / 15:56:26.869975 | `0/19E3F80` | `0/19E3F80` | `0/19E3F80` |
| 02 | final / 15:58:10.068554 | `0/1A02CD8` | `0/1A02CD8` | `0/1A02CD8` |
| 03 | final / 15:59:31.901158 | `0/19FEDC8` | `0/19FEDC8` | `0/19FEDC8` |
| 04 | final / 16:07:06.703001 | `0/19FEDC8` | `0/19FEDC8` | `0/19FEDC8` |

These are publisher observations made around checkpoint reads. The SQL row/receipt comparisons establish fixture behavior. Physical WAL stayed at one segment (16,777,216 logical bytes from `pg_ls_waldir()`, 16,392 allocated KiB from `du`) across all three runs.

| Metric | Approved limit or threshold | Run 02 | Run 03 | Run 04 |
| --- | --- | ---: | ---: | ---: |
| Source memory peak, cgroup bytes | 805,306,368 (768 MiB) | 134,725,632 | 135,118,848 | 135,536,640 |
| Source CPU usage, cumulative | 1 CPU, quota `100000 100000` | 12,644,857 µs, 2 throttled periods | 11,747,590 µs, 4 throttled periods | 10,806,002 µs, 2 throttled periods |
| Source final Docker stats | 128 PID limit, 768 MiB | 6 PIDs, 69.86 MiB, 6.07% CPU, 51.1/55.7 MB block I/O | 6 PIDs, 69.86 MiB, 0.03% CPU, 51.1/55.7 MB block I/O | 6 PIDs, 70.09 MiB, 0.02% CPU, 51.3/55.7 MB block I/O |
| One-shot runner maximum sampled cgroup peak | 268,435,456 bytes (256 MiB) | 23,719,936 bytes | 23,674,880 bytes | 23,732,224 bytes |
| Replay test container maximum sampled peak | 268,435,456 bytes (256 MiB) | 72,376,320 bytes | 72,400,896 bytes | 72,396,800 bytes |
| Runner sample CPU usage, cumulative | 0.5 CPU, quota `50000 100000` | 0.321211 s max one-shot, 12.263 s replay container | 0.290707 s max one-shot, 11.714 s replay container | 0.302656 s max one-shot, 11.815 s replay container |
| Allocated PGDATA including WAL, peak | Stop at 524,288 KiB | 47,576 KiB | 47,576 KiB | 47,576 KiB |
| Allocated WAL, peak | Stop at 262,144 KiB | 16,392 KiB | 16,392 KiB | 16,392 KiB |
| Free volume filesystem space, minimum | Stop below 1,048,576 KiB | 4,244,640 KiB | 4,244,640 KiB | 4,244,636 KiB |

The one-shot maxima use all resource events from the integrated runner, sequential and overlap harnesses, and the separate walkthrough where present. That gives 75, 81 and 81 samples for runs 02, 03 and 04. Replay invocations share a cgroup and use its separate cumulative counter. Docker inspection and cgroup files confirmed the source memory and CPU limits, 128 PIDs, zero swap, 128 MiB shared memory and the `local` log driver capped at three 5 MB files. The retained S00 runner's Docker inspection showed a 256 MiB memory-plus-swap limit, 0.5 CPU and 32 PIDs. All sampled runner and source cgroups showed zero OOM and OOM kills. PostgreSQL logged a shutdown checkpoint and clean exit from its temporary bootstrap instance. Final teardown of the healthy workload container independently returned exit 0.

### Read-only walkthrough

Runs 03 and 04 advanced from the final exact S00 to S04 and ran the documented SQL as the reader over loopback. The query returned `on` for `transaction_read_only` and the following rows. Item 102 was absent. The additional reset and independent runner inspection again matched S00 in each run.

```text
on
30|1|O30|paid|2026-01-01 00:04:00+00|2026-01-01 00:04:00+00
301|30|1|C|2|200|2026-01-01 00:04:00+00|2026-01-01 00:04:00+00
302|30|P302|400|2026-01-01 00:04:00+00|2026-01-01 00:04:00+00
v1|42|S04|4d2c11bd073069f7a4a9f38ba044d58219fad0c37ab3a2b43b300a97414432f8|856
```

## Evidence artifacts

The redacted publication contains primary evidence from run 02 and run 04, including the repeat after teardown. It includes the original checkpoint SQL rows and comparison results, isolation and teardown transcripts, source settings, filtered PostgreSQL logs, WAL and resource samples, fault inputs and outputs, and run 04's read-only walkthrough. The manifest records the tested commit, run IDs and per-record SHA-256 values. The bundle README gives reproduction commands and explains how to inspect the JSON bundles. [Browse the pinned evidence](https://gist.github.com/TiaanViviers/04c148b1f50816df6ac3e95d4237e47e/1b503cb2cc3f99fbd0abc96c50838122952072fa) · [Download ZIP](https://gist.github.com/TiaanViviers/04c148b1f50816df6ac3e95d4237e47e/archive/1b503cb2cc3f99fbd0abc96c50838122952072fa.zip)

On 2026-11-26 the ZIP downloaded without authentication. Its 16 files matched the publication allow-list, and all 625 evidence records matched the manifest's hashes. All 22 downloaded SQL snapshots matched the independent fixture. Extract the ZIP and run `sha256sum -c SHA256SUMS` in the extracted directory. The SHA-256 of `SHA256SUMS` itself is `68e5f429808bfa767e95b6864af580e4f5a72f297bd6cba1b6f16dc134714226`.

The original archives and staging transcripts remain local. The archive hashes below identify the materials inspected during independent review. The published checksums refer to the redacted files. [Independent review of the primary evidence](https://github.com/TiaanViviers/cdc-lakehouse-lab/pull/36#pullrequestreview-6069600500)

| Original archive | SHA-256 |
| --- | --- |
| `evidence-01.tar.gz` (guest tooling failure) | `6a3ac4e97d502fa7ef64a692938a77ef2f40f13a6cd83a271355bb2f9ea49fa4` |
| `evidence-02.tar.gz` | `6e1377c55375c207195634cfe15b6cd9d24f34d549821b872265e477b99038d3` |
| `evidence-03.tar.gz` | `235074cbaa748edc789a8f8c6001552d60c9e53bee16f56f50c30f27dc907a57` |
| `evidence-04.tar.gz` | `11461af000604b6f3e9fd78d06bc76cab270537ed5b64116402fb03650e26035` |

[Issue #26](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/26) · [Source gate entry point](../../tests/integration/source-gate/run.sh) · [Snapshot SQL](../../tests/integration/source-gate/snapshot.sql) · [Research register](../research-questions.md#phase-1-source-evidence)

## Interpretation

**Decision. Phase 1 technical source gate met.** Three fresh, independently isolated sources reproduced every required committed checkpoint, fault response and recovery result within the declared limits. The evidence establishes deterministic operational source behavior for fixture v1, seed 42. No material source defect surfaced in the covered cases.

## Limitations / confounders

- The resource results describe one small fixed workload on isolated two-vCPU guests sharing a staging host. The Docker CPU percentage is a single end-of-run sample. Cgroup CPU usage is cumulative. The Docker log limit and the disk thresholds serve different purposes. The thresholds rely on periodic observations and operator action.
- WAL samples include ordinary server activity. The source has no publication, slot or consumer. A source flush position cannot establish a downstream acknowledgement, retention behavior or replicated visibility.
- The replay faults target controlled before-commit and post-commit/pre-acknowledgement boundaries. Wire-level interruption during `COMMIT`, prolonged outages, failover and conflicting writes are outside the observed cases.
- The reset marker includes the database OID, cluster system identifier and enrolled UUID. Keep physical copies of the lab volume outside the reset procedure because copying the volume copies the marker.

## Follow-up action

Bring the measured source baseline and recorded limitations to the [1.9 handover review](../../backlog/phase-1.md#19-review-phase-1-findings-and-hand-over-to-phase-2). R02, R03, R04, R05, R13, R16 and R25 stay open at their full acceptance conditions. Future experiments need independent evidence of remote initial snapshot and change application, slot feedback and retention, recovery after consumer interruption, consistent downstream cutoffs, broader human inspection and operational write-back.
