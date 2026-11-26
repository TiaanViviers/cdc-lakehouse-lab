# EXP-015 — Package the pinned consumer and local DuckLake sink

- **Date:** 2026-11-26 UTC
- **Research question IDs:** R01, R04, R05, R08, R09, R16
- **Operator:** Codex, ticket [2.5 / #42](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/42)
- **Software:** Stock PostgreSQL 16.16 Bookworm publisher and the May DuckPipe PG18.4 consumer. The bundle includes DuckPipe 1.0.0 at `86d5c248d80370fb2e10ddc1abd780fd94c3a52b`, pg_ducklake 0.1.0 at `20d799e673639fb0c36a3b31db413e45057a10ed`, pg_duckdb 1.1.0 and DuckDB v1.5.1. The runtime uses Docker Engine 29.1.3 with the containerd store and Compose 2.40.3 on Ubuntu 24.04.5 amd64, kernel 6.8.0-147-generic.

## Hypothesis

The reviewed [EXP-011](EXP-011-remote-pg16-probe.md) consumer can be staged and started offline as a bounded Compose service. Its PostgreSQL catalog and referenced Parquet can survive consumer recreation with both the publisher and stopped group undisturbed. Authenticated PostgreSQL health should be observable independently of connector workers and exact data reads.

## Preconditions and decisions

- [ADR-002](../decisions/ADR-002-phase-2-local-cdc-probe.md) and the [independent EXP-011 review](https://github.com/TiaanViviers/cdc-lakehouse-lab/pull/49#pullrequestreview-6070606302) establish the selected runtime scope. Follow the [consumer runbook](../cdc-consumer.md) using a fresh guest overlay with KVM, 2 vCPUs, 2 GiB RAM, `-nic none` and read-only staging media. The host holds the shared runtime lock while the guest lives.
- Retain the pinned image's HBA. Its Docker setup appends loopback trust for the embedded DuckDB scanner. Constrain socket and loopback trust to the disposable consumer, require SCRAM on the health and observation clients, publish zero ports and allow only the already-gated source bridge. The source test role has the EXP-011 registration prerequisites and scoped dual-stack SCRAM. [Pinned init script](https://github.com/relytcloud/pg_duckpipe/blob/86d5c248d80370fb2e10ddc1abd780fd94c3a52b/docker/init.d/0002-localhost-trust.sh) · [PostgreSQL 18 HBA](https://www.postgresql.org/docs/18/auth-pg-hba-conf.html) · [libpq require_auth](https://www.postgresql.org/docs/18/libpq-connect.html)
- Use the pinned local data directory in the same named volume as the consumer's PGDATA. Read the catalog directly to establish its storage format. The build exposes per-table inlining settings and the scoped inline flush. [Pinned pg_ducklake settings](https://github.com/relytcloud/pg_ducklake/blob/20d799e673639fb0c36a3b31db413e45057a10ed/docs/settings.md) · [Pinned DuckLake SQL API](https://github.com/relytcloud/pg_ducklake/blob/20d799e673639fb0c36a3b31db413e45057a10ed/sql/pg_ducklake--0.1.0.sql)
- Documentation and pinned sources verified 2026-11-26. Compose defines `pull_policy: never`, health checks, local volumes and resource caps. The Docker CLI loads the staged archive into the guest store. EXP-011 established that the Engine reports the registry index ID, so the staging verifier checks the actual selected manifest and config inside the archive. [Compose service reference](https://docs.docker.com/reference/compose-file/services/) · [Docker image load](https://docs.docker.com/reference/cli/docker/image/load/)

## Procedure and expected results

1. Stage and checksum the pinned artifacts and archive the tested revision using the [runbook](../cdc-consumer.md#stage-and-verify-the-image). Attempt consumer startup with the pin absent and observe a local missing-image error. Load the exact archives and verify linux/amd64 and all consumer digests.
2. On a unique internal bridge, apply and test dual-stack rules through the existing empty-bridge gate. Start stock PG16 and add the separate consumer. Verify image identity, cgroups, no host ports, distinct namespaces, effective SQL settings, extension load and visible HBA order. Loopback trust should work before group registration, while peers and the status client must satisfy SCRAM.
3. Check that a fresh peer accepts the real secret and rejects a wrong password. Temporarily change the health client's mounted secret in place while preserving the server's verifier. The SQL health check must become unhealthy and the adapter must fail without status. Restore the correct secret.
4. Register only `probe.items → bronze.items`. Compare the independent source and target reads to exact ordered pairs `(1, 'file seed'), (2, 'second key')`, using a bounded query and up to 60 seconds of polling at 500 ms after an unsuccessful read. Inspect the initial catalog and worker.
5. Disable the group and stop its worker. Check that SQL health stays healthy, status shows the mapping and absent worker, and the source slot is inactive. Disable table inlining and call the pinned scoped flush. Check the metadata, snapshot IDs, physical file path, size, Parquet header/footer and SHA-256.
6. Gracefully stop and force-recreate the consumer with the same volume, bridge and credentials. Use a new authenticated SQL session to verify exact rows. Check the unchanged cluster, group and mapping, inactive source slot, and identical catalog and physical file digest.
7. Remove the mapping and group through the consumer API, prove zero source publications and slots, and run scoped teardown. Require clean exit and no OOM, and check the labelled containers, volumes, bridge and firewall rules. Record the precise assertion if the trial stops early.

## Actual observations

### Image staging

| Consumer identity | SHA-256 |
| --- | --- |
| Registry index | `091236d2acecfec1216817aff6e43dc4c036159cebe44a19c73c95c1fe9be348` |
| linux/amd64 manifest | `de0a9036fd11a75eaff23508209c2cea675d081aecea51f60cdca78c0802a5a6` |
| Config | `a0452c3a54190ba6eeaf94dd3e434f97fd3862944c73b3f681f85eb8e3b2f56e` |
| Transferred archive | `91185421b787b82476b65f32abb02f3ae15ae01956214b4b5a12fea87a2fa38c` |

The online staging command downloaded and verified all selected registry blobs. The fresh guest verified the archive checksum and all selected blob hashes again before import. OCI tar timestamps can change the transfer checksum when restaged. The source and preflight archives reused the checksummed artifacts from EXP-011.

### Guest runs

- **Attempt 01, `20261126t083228z-aba9`, `907d4047dd1ec5527fde9f5a45308003f8b99cbd`.** Missing-image, offline import, bridge preflight and both database starts passed. The source resource sampler tried to read PID 1's namespace symlinks as container root while the postmaster ran as the postgres OS user. The namespace inspection exited 1. The guarded cleanup checked clean exits without OOM and removed the project, two volumes and bridge before guest power-off. The retry reads namespace links as the postmaster OS user, verifies interface and route boundaries, and samples the PGDATA and WAL sizes separately.
- **Attempt 02, `20261126t083345z-5916`, `7803c440864f974234dc4d74774761e70c032fad`. Status: passed.** QEMU 8.2.2 booted `guest-02.qcow2` against the approved guest base while holding the exclusive runtime lock. The acceptance script and checked cleanup returned 0. Credential and file controls exercised the actual consumer and the read-only transfer archive. See the [recorded observations](evidence/EXP-015-guest-observations.txt).

| Check | Observed result |
| --- | --- |
| Startup and networking | With the pin absent, Compose reported `No such image` and created no consumer. After offline load both DBs used the pinned index IDs and separate PID and network namespaces. The preflight verified expected peer DNS/TCP and denied host IPv4 and IPv6, routed LAN and VPN, and delegated DNS. The actual services had only loopback and their single bridge interface, with no usable default route or published host ports. |
| Preloads and bounds | The consumer SQL reported the expected preloads and versions, SCRAM password encryption, query routing off and a one-thread, 96 MiB DuckDB configuration with a 48 MiB temp bound. The bundle's DuckPipe settings reported one concurrent flush and a 1 MiB queue limit. Effective cgroups were 768 MiB / 1 CPU for the source and 512 MiB / 0.75 CPU for the consumer, with 128 PIDs and zero swap each. |
| HBA and controls | The IPv4 loopback trust login passed without a password and failed when libpq required SCRAM. The IPv6 Docker peer succeeded with SCRAM and rejected the wrong password. PG18 HBA had zero errors and trust entries only for local sockets and loopback. The restarted server logged SCRAM at HBA line 128. The wrong mounted credential drove SQL health to `unhealthy` and the status adapter returned its generic failure. Restoring it returned health to `healthy`. |
| Worker and exact contents | The source and direct Bronze queries returned `1\|file seed` and `2\|second key`. Bronze was exact on the first bounded attempt. At the initial sample the group had PID 426, a `CATCHUP` mapping, group checkpoint and table snapshot LSN `0/19E8E90`, and null table apply LSN. After disabling the group and stopping the worker, the named source slot was inactive and SQL health stayed healthy. The mapping's last sampled state and zero-valued queue counters remained visible after the PID disappeared. |
| Catalog and physical storage | Schema `ducklake` recorded version `0.4`, table ID 2 and snapshots 0–2 at first parity. The inline table was present and the file inventories were empty. After setting the per-table `data_inlining_row_limit=0`, the scoped flush reported two records. Snapshot 3 appeared and the referenced Parquet under `/var/lib/postgresql/18/docker/pg_ducklake/bronze/items/` had 1,024 bytes, two records, `PAR1` header/footer and SHA-256 `16879fb099bc38447e2673e4629c723a3c34e14d187dd874980925b15fe77c26`. There were zero live delete files. |
| Recreation and teardown | A new container ID used the same labelled volume and PG system identifier `7712395715686359067`. The unchanged disabled group, mapping, inactive slot and publication survived. A fresh authenticated session returned the same exact ordered rows. The catalog and file observation JSON matched byte for byte. The group was never re-registered. Connector teardown left zero publisher slots or publications. Both containers stopped with exit 0 and `OOMKilled=false`. The runner removed its containers, volumes, exact bridge and installed firewall rules. |
| Measured resources | Peak consumer memory reached 195.4 MiB before recreation and 30.9 MiB after. Its first cgroup recorded 23 throttled periods and 0.641 s throttled time. Source peak was 129.6 MiB. Maximum sampled named volume sizes were 41,392 KiB consumer and 47,412 KiB source. Source WAL was 16,392 KiB and minimum sampled guest free disk was 3,668,968 KiB. OOM counters stayed zero. |

## Evidence artifacts and checks

- Run the [guest acceptance procedure](../cdc-consumer.md#reproduce-exp-015) or inspect the [acceptance script](../../tests/integration/cdc-consumer/run.sh). The tested runtime commit is `7803c440864f974234dc4d74774761e70c032fad`. Its transferred repository tar SHA-256 was `eb9893ce4e9669431d888882ef6ec9dab3085a0d7ef0ad9368ae5e1fd99d7c30`.
- The [redacted excerpts](evidence/EXP-015-guest-observations.txt) preserve image IDs, isolation outcomes, HBA and SQL settings, cgroups, labelled observations, snapshots, file hashes, and exit evidence. Run `sha256sum -c docs/experiments/evidence/EXP-015.sha256`. The full guest evidence is in the ignored `artifacts/EXP-015/20261126t083345z-5916/` directory in the ticket worktree. The exported redacted archive SHA-256 was `ac98241e06c746dca23e49fd144bad9fe107f8f8eb0f3b70fad11b6ff82efefa`.
- `make help check BASE=origin/main`, `make test-unit` (24 tests), `sh tests/repository-checks.sh` (five cases), Bash syntax checks, and Python compilation passed. The disconnected guest emitted `EXP-015 ACCEPTANCE CHECKS PASSED` and `project_cleanup_exit=0`.

## Interpretation and follow-up

The one-table result demonstrates reproducible offline startup and file-backed storage across graceful consumer container recreation. Holding the worker stopped across recreation excluded replay and re-registration as sources of the observed rows. The credentials experiment demonstrates database health and observability failure under a wrong password. The worker experiment shows why successful database health, mapping state and a zero queue alone cannot establish progress or exact rows. The scoped flush changed physical representation of connector-written data under a quiescent workload.

| Question | Pending Phase 2 register update |
| --- | --- |
| R01 | The pinned remote setup is packaged and reproduced from staged images on a fresh bridge, with exact one-table initial parity. The baseline mapping for all four tables belongs to 2.6. |
| R04 | The group checkpoint, mapping positions, backend presence and queue state are available as separate, bounded observations. A stopped worker can still have a persisted mapping and default-valued queue counters. Durable acknowledgement remains open. |
| R05 | Graceful recreation preserved a quiescent catalog and its data with the group disabled. Catch-up, fault recovery and durability during apply remain open for 2.7. |
| R08 | The colocated PostgreSQL worker state and catalog were durable on the consumer volume. Remote catalog placement remains open. |
| R09 | The bundled 0.4 catalog and the referenced local Parquet survived recreation with an exact consumer-local read. Independent DuckDB attachment remains open. |
| R16 | Authenticated health, redacted connector observations, scoped catalog inventory and exact rows are reproducible. End-to-end observation remains open. |
