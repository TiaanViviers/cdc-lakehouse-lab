# EXP-011 — Remote PG16 snapshot and DML on the pinned DuckPipe build

- **Date** 2026-11-26
- **Research questions** R01–R04, R08, R09
- **Operator** Codex
- **Ticket** [2.1 / #38](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/38)
- **Branch base** `d9de734a14ad33c75025cf564ada801461bde516` from `origin/main`

## Hypothesis

A separate DuckPipe PostgreSQL process can snapshot a keyed table from stock PG16.16 over TCP with SCRAM and maintain exact current-state rows in a local DuckLake table after committed inserts, updates and deletes.

## Preconditions and procedure

1. Stage both digest-pinned PostgreSQL artifacts and the verified isolation probe on read-only media. Start a fresh two-vCPU, 2 GiB QEMU/KVM overlay with no NIC. Use the existing empty-bridge gate on the actual bridge before starting the stock PG16 source profile. The consumer and publisher each have one endpoint on that bridge and distinct named volumes. [Minimal reproducer](../../tests/integration/remote-probe/README.md)
2. Enroll the Phase 1 schema, record its owners and ACLs, then create the disposable `probe_replicator` and `probe.items`. Commit `(1, 'seed')` before registration. Verify the effective source HBA match, fresh success, wrong password, alternate database denial and fixture schema access denial. Check consumer loopback and peer authentication, preloads and extension identities.
3. Create one remote `bgworker` group with an explicit publication and slot. Register the only table, with `copy_data => true`, `sync_mode => 'upsert'` and direct target `bronze.items`. While writes are held, poll the target after registration and after each of the three isolated source commits. Allow 60 seconds a checkpoint and sleep 500 ms after unsuccessful reads. Record expected, last failing and first passing rows. A third returned row fails parity because this fixture has at most two.
4. Observe the publisher publication and slots, connector group, mapping and worker, DuckLake catalog and local files. Drop the mapping and group through DuckPipe and inspect the source again. Only the verified disposable source and inactive exact-name slot are eligible for fallback cleanup. Verify the source probe role and schema are gone and the Phase 1 ACL/enrollment inventory still matches.
5. Observe the 480-second run limit and 1 GiB guest free-space floor. PG16 is capped at 768 MiB and one CPU, the consumer at 512 MiB and 0.75 CPU. Both have 128 PIDs and zero container swap. The run stops before further writes on a measured OOM or disk-limit breach. The volume stop thresholds are 512 MiB per PostgreSQL volume and 256 MiB allocated WAL. Consumer `/tmp` is a 64 MiB tmpfs. Resource settings, throttle and OOM counters are sampled from cgroup v2.

**Verified documentation and pinned code, 2026-11-26.** PostgreSQL 16 uses the SQL database HBA rule for logical replication. The reviewed DuckPipe build `86d5c248d80370fb2e10ddc1abd780fd94c3a52b` creates the slot before the publication, adds the registered table, changes replica identity to FULL and creates a temporary snapshot slot in the repeatable-read COPY session. Its bundled pg_ducklake source is `20d799e673639fb0c36a3b31db413e45057a10ed`. The source role has database CREATE and owns the test schema/table to support this exact API. [PG16 HBA](https://www.postgresql.org/docs/16/auth-pg-hba-conf.html) · [Pinned DuckPipe API](https://github.com/relytcloud/pg_duckpipe/blob/86d5c248d80370fb2e10ddc1abd780fd94c3a52b/duckpipe-pg/src/api.rs) · [Pinned snapshot code](https://github.com/relytcloud/pg_duckpipe/blob/86d5c248d80370fb2e10ddc1abd780fd94c3a52b/duckpipe-core/src/snapshot.rs) · [Candidate review](EXP-010-phase-2-candidate-review.md)

## Expected results

| Hold point | Exact ordered source and direct target rows |
| --- | --- |
| Initial copy | `(1, 'seed')` |
| Insert | `(1, 'seed'), (2, 'inserted')` |
| Update | `(1, 'updated'), (2, 'inserted')` |
| Delete | `(1, 'updated')`. Key 2 absent and zero duplicate keys |

The active slot should be persistent, use `pgoutput` and leave the second slot available after initial copy. The catalog format hypothesis is 0.4. The direct target access method, catalog version and file or inlining metadata determine the storage result.

## Actual observations

### Image provenance

All hashes are SHA-256. The archive checksum is specific to the file transferred to these guests.

| Artifact | Registry index | linux/amd64 manifest | Image config | Archive |
| --- | --- | --- | --- | --- |
| Stock PG16.16 Bookworm | `cd0e9518bda5f2ea667ff84d22795d089720c883f288e215d97ce57437e8ef37` | `d755a91aff87574a57060f86ecc0d55f83ccb51ceec6ec6f904c1210d018d998` | `76500a7555b1f245546af93974bb208366013cf537fa3038f0bdd493efe0c612` | `0c0a5c57fdf877a81f0930f105bb789f01d4f333e40d025584197fcdc5975366` |
| DuckPipe May PG18 candidate | `091236d2acecfec1216817aff6e43dc4c036159cebe44a19c73c95c1fe9be348` | `de0a9036fd11a75eaff23508209c2cea675d081aecea51f60cdca78c0802a5a6` | `a0452c3a54190ba6eeaf94dd3e434f97fd3862944c73b3f681f85eb8e3b2f56e` | `751170b67de6c649ac6efd4b74a32bebd63d733e6265c7a9c4247a9df4ed6728` |
| Isolation probe | See [1.1 probe pins](../source-runbook.md#reproduce-the-negative-experiment) | | | `a5ad58ea45e9e1728b51a72bc2e0bc3e2a33ca4316566faec9932cb0b5f26a13` |

**Attempt 01, 08:00:40 UTC, `4846b1733085f7a3f06028cc57a6b243feb71ac4`.** All archives imported and the expected amd64 members appeared in the image trees. The harness compared the Docker containerd image inspect ID to the image config digest and stopped before creating network or database resources. Inspect returned the registry index ID. The next revision verifies the config and its membership in the pinned index through OCI content hashes and compares Docker's reported ID with the index.

**Attempt 02, 08:08:02 UTC, `abae975d0cff1e8107297e897e39013345278b66`.** The hashes, offline import and bridge gate passed. Source-local SQL reported PG16.16, only `plpgsql` and the expected logical WAL configuration. The foreground run stalled between that first query and fixture enrollment. It was interrupted at the serial console and the disposable guest was powered off. No consumer ran and no registration was attempted. The working hypothesis was a Docker client with an inherited terminal input in a separate `timeout` process group. The next run closes the inherited input, retains explicit SQL stdin redirections and applies a bounded kill after the per-command timeout.

**Attempt 03, 08:12:25 UTC, `ecde4544837af0c8ef9c6332a9dfc6663cacf297`.** PG16 enrollment and consumer startup passed. The first cross-container login selected IPv6. PG16 returned `FATAL: pg_hba.conf rejects connection` for `probe_replicator` on `source_lab`. The scoped SCRAM rule matched IPv4 only, so the IPv6 connection hit the explicit reject rule. The PG16 log and HBA order reproduce the boundary. The publisher still had zero publications and slots. The consumer had initialized the `ducklake` schema and metadata version `0.4` at `/var/lib/postgresql/18/docker/pg_ducklake/`. It had only snapshot 0 and no registered table. Both services stopped with exit 0, without OOM. The guarded SQL cleanup returned `after|0|0|t|t`. The next run adds exactly one SCRAM rule for the same bridge's IPv6 subnet and keeps the images and connector path pinned.

**Attempt 04, 08:13:34 UTC, `c1724174d35789412160004dda1c4fae2db8e746`.** Both fresh peer SCRAM logins and wrong-password controls passed. The seed and the three commits reached exact source/target parity in four reads labelled initial, insert, update and delete. The separate deleted-key assertion then produced `(PGDuckDB/CreatePlan) Prepared query returned an error: Parser Error: SELECT clause without selection list` on `NOT EXISTS (SELECT FROM bronze.items WHERE id=2)`. The ordered rows already showed key 2 absent and the lone key unique. The error arose in the verification query after parity. The fallback removed the inactive slot, publication and probe scope after stopping the consumer. The next run uses `SELECT 1` in the deleted-key assertion and checks the normal mapping and group teardown. It also records the inline row count and treats an empty DuckPipe error field as empty because the pinned flush worker resets that field to an empty string. [Pinned worker update](https://github.com/relytcloud/pg_duckpipe/blob/86d5c248d80370fb2e10ddc1abd780fd94c3a52b/duckpipe-core/src/flush_worker.rs)

### Passing guest run

**Attempt 05, 08:15:22 UTC, `949b093298a85e11a042e2cbd2376ce4a09d591f`. Verdict: compatible for this one-table local probe.** The quiescent snapshot and each committed DML checkpoint reached exact parity. The connector removed the slot and publication. The guest returned exit 0. The [checksummed observations](evidence/EXP-011-guest-observations.txt) preserve the tested SHA, overlay, run ID, bridge ID, container identities, volume labels and excerpts.

The guest ran Ubuntu 24.04.5 LTS amd64, Linux 6.8.0-147-generic, Docker Engine 29.1.3 with the containerd store, Compose 2.40.3 and cgroup v2 with the iptables backend. QEMU 8.2.2 used a fresh overlay, KVM, 2 vCPUs, 2048 MiB and `-nic none`. Attempts 04 and 05 booted the same kernel and initrd from the Phase 1 image directly, with `systemd-networkd-wait-online.service` masked to skip its wait for an uplink. Both guests had only loopback and Docker's default bridge before provisioning, with no default routes.

| Observation | Result |
| --- | --- |
| Image and executable identity | The offline OCI archive hashes, amd64 member/config digests, loaded index IDs and image trees agreed with the pins. Stock source SQL reported 16.16, an empty preload list, only `plpgsql` and no available `pg_duck*` extension. The separate consumer was 18.4 with `pg_duckdb,pg_ducklake,pg_duckpipe` preloaded. Installed versions were `1.1.0`, `0.1.0` and `1.0.0` respectively. `duckdb.raw_query('SELECT version()')` returned `v1.5.1`. Extension library and init-script hashes are in the evidence. |
| Connectivity and auth | Both containers had separate PID/network namespaces and one endpoint on the verified internal bridge. No host ports were published. The empty-bridge preflight reached its peer by Docker DNS and denied host IPv4/IPv6, routed LAN/VPN and delegated DNS. The fresh PG16 login from the consumer and PG18 login from the one-shot peer both required SCRAM. Both wrong passwords were rejected. The source role could access `source_lab` and its probe table. It was denied access to the `postgres` database and `fixture` schema. |
| Effective HBA | PG16 used the scoped IPv6 SCRAM rule on line 2 for the actual peer and WAL connections. An IPv4 rule covered the same Docker bridge's IPv4 subnet. PG18 used the broad SCRAM rule on line 128 from a peer and the earlier loopback trust rule on line 119 for passwordless TCP from itself. The image's appended trust lines 129–130 were present. Both HBA views had zero parse errors. |
| Resources | Peak memory was about 126.4 MiB on PG16 and 145.0 MiB on PG18. OOM counters stayed zero. The consumer recorded 22 throttled periods and about 0.664 s throttled time. PG16 used at most 47,356 KiB of its PG volume and 16,392 KiB of allocated WAL. PG18's whole volume reached 41,344 KiB. The minimum sampled guest free space was 3,668,888 KiB. Both stopped with exit 0. |

### Exact contents

Target SQL was `SELECT id,value FROM bronze.items ORDER BY id,value LIMIT 3` through consumer-local `psql`, with query routing off. The exact source state was read separately after each commit. The timestamp and attempt count below describe the target read. Elapsed seconds use Bash's whole-second timer and include the source observation. The polling delay was 500 ms after each unsuccessful read, plus client and query time.

| Checkpoint | Last failing target read | First passing target read UTC | Exact source and target |
| --- | --- | --- | --- |
| Initial | Empty on attempt 1 | 08:16:08.032, attempt 2, 1 s | `(1, 'seed')` |
| Insert | `(1, 'seed')` on attempt 9 | 08:16:14.755, attempt 10, 6 s | `(1, 'seed'), (2, 'inserted')` |
| Update | `(1, 'seed'), (2, 'inserted')` on attempt 6 | 08:16:19.354, attempt 7, 4 s | `(1, 'updated'), (2, 'inserted')` |
| Delete | `(1, 'updated'), (2, 'inserted')` on attempt 7 | 08:16:24.546, attempt 8, 5 s | `(1, 'updated')` |

The final explicit checks returned `deleted_absent|t` and `duplicate_keys|0`. The connector's three flush log entries recorded one insert, an update represented by two buffered changes with one delete, and a delete with one affected key.

### Slot, worker and catalog

- The publisher started with zero publications and slots. `create_group` created an empty publication owned by `probe_replicator` and an inactive persistent `pgoutput` slot. `add_table` enrolled only `probe.items` and changed replica identity from default to FULL. PG16 logged `START_REPLICATION` with protocol 1 and the named publication. The source walsender used the probe role and the consumer address.
- PG16 logged the call to `pg_create_logical_replication_slot($1, 'pgoutput', true)` with `duckpipe_snap_1`, followed by a consistent point, COPY and COMMIT on its snapshot session. The consumer logged one row copied with snapshot LSN `0/19A92D8`. The post-copy publisher inventory held only the single active persistent slot, which establishes release of the temporary slot. Polling did not sample the temporary slot while it was live.
- The connector group worker and table mapping remained observable over all four checkpoints. The first exact read was followed by a `CATCHUP` sample, then `STREAMING` at all DML checkpoints. At update parity the table's applied LSN was `0/19A9408` while the group checkpoint and source confirmed flush were `0/19A9350`. After delete, those fields sampled `0/19A9498`, `0/19A9498` and `0/19A9408` respectively. These sequential reads distinguish visible rows, table apply, group checkpoint and publisher feedback. They are sampled positions with separate observation times.
- The target used the `ducklake` access method. The PostgreSQL catalog schema was `ducklake` and `ducklake_metadata.version` was `0.4`. It mapped table ID 2 to relative path `bronze/items/` at `/var/lib/postgresql/18/docker/pg_ducklake/` inside the named PG18 volume. Snapshots 0–5 recorded initialization, target DDL, initial copy and the three DML changes. The inline table `ducklake_inlined_data_2_1` held 1, 2, 3 and 3 physical records at the four checks. That history coexisted with one live row after delete. Data-file and delete-file inventories were empty, and the filesystem had no table data files under the local root.
- `remove_table` removed the table from the publication and warned that the slot still held WAL. `drop_group` removed the slot and publication. The source inventory was empty for both before stopping the consumer. The fallback guard then verified no remaining replication objects, dropped the probe schema/table and role, and returned `after|0|0|t|t`. Phase 1 role, fixture relation ACL and enrollment records matched byte for byte before and after. Compose removed both owned volumes and containers and the script removed the bridge and its firewall rules.

## Evidence artifacts and checks

- [Reproduce in the disconnected guest](../../tests/integration/remote-probe/README.md) and run the [native SQL probe](../../tests/integration/remote-probe/run.sh).
- [Redacted guest observations](evidence/EXP-011-guest-observations.txt) and [SHA-256 manifest](evidence/EXP-011.sha256). Run `sha256sum -c docs/experiments/evidence/EXP-011.sha256` from the repository root. The complete redacted run records are under ignored `artifacts/EXP-011/` in the ticket worktree. The transferred archive for attempt 05 has SHA-256 `49293645a9c3131db4732eb9e93254aba55ecaa44e7fbddfa9841e42f540c265`.
- `make help check BASE=origin/main`, `make test-unit` (24 tests), `sh tests/repository-checks.sh` (five cases), and `bash -n tests/integration/remote-probe/run.sh` passed. The disconnected VM probe returned 0 with the parity and lifecycle checks enabled.

## Interpretation and limits

The May digest-pinned build supports the tested stock PG16.16 → PG18.4 remote DuckPipe path with its bundled local DuckLake 0.4 catalog. All four target checks used connector-maintained data. The reviewed Phase 2 plan can carry this build and its observed API and format into 2.5 after review. M2 also requires rollback exclusion, multi-table visibility and bounded same-slot recovery. Those are future experiments. A quiescent single-table snapshot, sampled acknowledgements and an inline sink leave concurrent snapshot timing, durable replay, file-backed parity, remote catalog placement and independent readers open.

| Research ID | Proposed Phase 2 register update |
| --- | --- |
| R01 | Remote PG16.16 read and committed streaming demonstrated for this pinned, isolated one-table setup. |
| R02 | Quiescent initial snapshot, exact rows and temporary slot release demonstrated. The snapshot-overlap window remains open. |
| R03 | One committed insert, update and delete converged to exact current-state keys and values. Larger fixture and fault cases remain open. |
| R04 | Persistent slot lifecycle and progress observed. Sampled table apply led group or publisher feedback at some checkpoints. Recovery and durable acknowledgement remain open. |
| R08 | Colocated PostgreSQL metadata and local data observed. A separate catalog host remains open. |
| R09 | Actual catalog format and inline storage observed. Independent reader attachment remains open. |

## Follow-up

Use the [2.5 API handoff](../../tests/integration/remote-probe/README.md#minimal-api-sequence-for-25) for the reusable consumer setup, including explicit loopback versus peer authentication and direct target SQL. Preserve the source's dual-stack scoped SCRAM rule and account for database CREATE and table ownership during registration. The catalog evidence gives Phase 3 a 0.4 reader compatibility target. Publication/slot failure cleanup, privilege reduction, restart and written Parquet require their own checks.
