# EXP-004 — Bounded PostgreSQL source profile

- **Date:** 2026-11-25
- **Research question IDs:** R01, R04, R05 (publisher baseline)
- **Status:** passed in the disconnected lab VM
- **Operator:** Codex
- **Branch and base:** `feature/1.2-bounded-source` from `5d4c463`, including the merged 1.1 gate
- **Run IDs:** `20261125T110105Z-p01-01` (project `cdc-source-12`) and `20261125T110439Z-p01-02` (project `cdc-source-12b`)

## Hypothesis and preconditions

Stock PostgreSQL 16.16 can serve an authenticated query and retain a committed sentinel across a clean restart, with verified isolation, resource ceilings and a bounded publisher configuration. Each run used a new Compose project and empty volume. The only test row was `(7, 'source-profile-1.2')`.

QEMU 8.2.2 with KVM, two vCPUs, 2048 MiB RAM and `-nic none` ran a new QCOW2 overlay over the powered-off 1.1 VM. The guest had only `lo` and `docker0` before provisioning. The tested stack was Ubuntu 24.04.5 LTS amd64, kernel 6.8.0-147-generic, Docker Engine 29.1.3 using the containerd image store and cgroup v2, Compose 2.40.3+ds1-0ubuntu1~24.04.1, Python 3.12.3, and iptables and ip6tables 1.8.10 (nf_tables). Engine reported the iptables firewall backend. [VM and probe provenance](../source-runbook.md#dedicated-vm-observations-2026-11-25)

| Image fact | Observed value |
| --- | --- |
| Registry reference | `docker.io/library/postgres:16.16-bookworm` |
| Index and guest Engine image ID | `sha256:cd0e9518bda5f2ea667ff84d22795d089720c883f288e215d97ce57437e8ef37` |
| `linux/amd64` platform manifest | `sha256:d755a91aff87574a57060f86ecc0d55f83ccb51ceec6ec6f904c1210d018d998` |
| Image config | `sha256:76500a7555b1f245546af93974bb208366013cf537fa3038f0bdd493efe0c612` |
| Authenticated `version()` | `PostgreSQL 16.16 (Debian 16.16-1.pgdg12+1) on x86_64-pc-linux-gnu`, GCC 12.2.0, 64-bit |

## Procedure and expected results

1. Stage the pinned `linux/amd64` OCI archive, transfer it on read-only media and inspect its exact reference after `docker load`. The image ID must match the approved registry index. [Staging commands](../source-profile.md#stage-and-start)
2. Validate the resolved profile, then run the 1.1 preflight on its only actual network. With the guest firewall rules missing, expect the startup command to exit 1 and the source project to have zero containers. Apply the rules, run the gate again, and expect each positive and negative control to succeed before Compose starts the source. Check the running endpoint's Engine network ID and unpublished port. [Startup and inspection commands](../source-profile.md#stage-and-start)
3. Wait for authenticated readiness, connect over service DNS from a disposable peer on the verified bridge, and compare the exact identity, database and SQL result. Repeat with an invalid password and require a server rejection. Query the HBA file and settings and confirm empty publication and slot catalogs. [Peer and SQL commands](../source-profile.md#verify-from-a-peer)
4. Confirm the resource and logging configuration with Engine inspection, the cgroup ceilings and metrics, the named volume labels and the WAL and filesystem samples. Insert the sentinel, force a checkpoint and sample again. Stop cleanly, remove the container with `down`, rerun the preflight with the same bridge and recreate the source. Verify a new container ID, the same volume, the exact row and the empty catalogs. Drop the sentinel, stop and roll back the firewall and bridge. [Limits and disk commands](../source-profile.md#verify-limits-and-storage) · [Restart and cleanup commands](../source-profile.md#verify-a-clean-restart-and-stop)

## Actual observations

Both runs returned 0 and emitted `SOURCE-PROFILE-PASS`. The measurements below are from the second run, 11:04:39–11:05:20 UTC. The source profile and 1.1 preflight used SHA-256 `6430a6d6cbce55afef1f2f044b3ce143c94ec6fec39e0d72c627540fb7076bf` and `6cc45325ce0b54115e897db518ac87964a2b76d8f806411da1d938eb28e74410`, respectively. The Compose hash is recorded against the exact file in this ticket. [Redacted resolved Compose config](evidence/EXP-004-compose.resolved.yaml)

### Isolation and authentication

Bridge `cdc-source-12b-input` (`cdc-src12b`, Engine ID `097eec3da934ccf6a7b4579dfb15d921b83bc992d4f1aa6034c5d77d0a43fa98`) was internal, with connected routes for `172.18.0.0/16` and `fdfa:653f:4c09::/64` and no usable off-bridge default route. Both IPv4 and IPv6 `FORWARD` chains began with `-j DOCKER-USER`. After applying the controls, each `INPUT` chain began with `-i cdc-src12b -j DROP` and each `DOCKER-USER` chain had `-i cdc-src12b ! -o cdc-src12b -j DROP`. Engine confirmed the source endpoint used that exact ID, `PortBindings={}` and container port mapping `{"5432/tcp":null}`. `docker port` returned no mappings.

| Probe | Before firewall rules | Before startup | Before recreation |
| --- | --- | --- | --- |
| Peer DNS and TCP | Marker, 0.08 s | Marker, 0.09 s | Marker, 0.09 s |
| VM gateway IPv4 / IPv6 | Markers, 0.07 / 0.08 s | `ETIMEDOUT`, 1.59 / 1.59 s | `ETIMEDOUT`, 1.59 / 1.58 s |
| Routed IPv4 LAN / VPN | `ENETUNREACH`, 0.08 / 0.07 s | `ENETUNREACH`, 0.08 / 0.07 s | `ENETUNREACH`, 0.08 / 0.08 s |
| Off-bridge IPv6 | `ENETUNREACH`, 0.08 s | `ENETUNREACH`, 0.08 s | `ENETUNREACH`, 0.08 s |
| Delegated DNS | `ESERVFAIL`, 0.07 s | `ESERVFAIL`, 0.08 s | `ESERVFAIL`, 0.10 s |
| Startup decision | Exit 1, zero source containers | Gate passed | Gate passed |

In each case the host reached its controlled gateway listeners, same-side LAN, VPN and IPv6 clients returned `cdc-isolation-v1`, and the direct DNS control returned `172.19.0.2`. All fixture ports were unpublished. The recorded LAN, VPN and IPv6 failures establish absence of useful routes in this topology. The gateway timeouts demonstrate the additional host-path control. The DNS result covers the controlled upstream and embedded resolver in this setup.

Health checks exited 0 at 11:04:56 and 11:05:15 UTC. PostgreSQL recorded SCRAM on loopback HBA line 115 (`host all all 127.0.0.1/32 scram-sha-256`). The peer used the bridge's IPv6 path and returned `source_admin|source_lab|fdfa:653f:4c09::3|fdfa:653f:4c09::2|256`. Its successful SCRAM connection and the rejected password both matched HBA line 124. The seven HBA rows had no parser errors.

```text
LOG:  connection authenticated: identity="source_admin" method=scram-sha-256 (/var/lib/postgresql/data/pg_hba.conf:124)
FATAL:  password authentication failed for user "source_admin"
DETAIL:  Connection matched file "/var/lib/postgresql/data/pg_hba.conf" line 124: "host all all all scram-sha-256"
```

### Settings, resource limits and durable state

| Effective SQL settings | Observed values |
| --- | --- |
| `wal_level`, `max_wal_senders`, `max_replication_slots`, `max_slot_wal_keep_size` | `logical`, `2`, `2`, `128 MB` |
| `min_wal_size`, `max_wal_size`, `wal_keep_size`, `checkpoint_timeout`, `archive_mode` | `32 MB`, `128 MB`, `0 MB`, `300 s`, `off` |
| `max_connections`, `shared_buffers`, `password_encryption` | `20`, `16384 × 8 KiB` (128 MiB), `scram-sha-256` |
| `logging_collector`, `log_connections`, `wal_segment_size` | `off`, `on`, `16777216 B` |
| `pg_publication` / `pg_replication_slots` | Zero of each on the fresh and recreated source |

`docker inspect` showed `Memory=805306368`, `MemorySwap=805306368`, `NanoCpus=1000000000`, `PidsLimit=128`, `ShmSize=134217728`, `OOMKilled=false` and `local` logging (`max-size=5m`, `max-file=3`). Kernel reads showed `memory.max=805306368`, `memory.swap.max=0`, `cpu.max=100000 100000` and `pids.max=128` on both containers. The source had zero OOM and OOM-kill events. The first sample was `0.04%` CPU, `19.78 MiB / 768 MiB`, block I/O `0 B / 52.5 MB`, and 6 PIDs. `cpu.stat` recorded `950434` CPU microseconds and three throttled periods (`9629` microseconds). After recreation the sample was `0.05%` CPU, `16.43 MiB / 768 MiB`, block I/O `0 B / 225 kB` and 6 PIDs (`169925` CPU microseconds, zero throttled periods).

| Disk sample | WAL entries / SQL file bytes | `pg_wal` allocated KiB | `PGDATA` allocated KiB | Available KiB on volume filesystem |
| --- | ---: | ---: | ---: | ---: |
| Fresh | 1 / 16777216 | 16392 | 46952 | 4610708 |
| After sentinel and `CHECKPOINT` | 1 / 16777216 | 16392 | 46992 | 4610640 |
| After container recreation | 1 / 16777216 | 16392 | 47000 | 4610560 |

The volume inspection showed `cdc-source-12b_source-pg`, driver `local`, with `com.docker.compose.project=cdc-source-12b` and `com.docker.compose.volume=source-pg`. The first container logged `received fast shutdown request`, `checkpoint starting: shutdown immediate`, then `database system is shut down`, and exited 0. After `down`, the volume still existed. A new container with the same mount returned exactly `7|source-profile-1.2` in a fresh authenticated session. Both runs dropped their sentinel and ended with zero containers and only the three default networks. The guest retained each run's project volume. Before poweroff, both guest `INPUT` chains were back to the default ACCEPT policy and both `DOCKER-USER` chains were empty.

### Repository and configuration checks

`make help check BASE=origin/main` passed, `sh tests/repository-checks.sh` passed all five cases, and `make test-unit` passed 20 tests. The runbook shell blocks passed `bash -n`. A separate local `docker compose config` matched the saved output after replacing the local secret-file path. Omitting `SOURCE_INPUT_ID` failed interpolation. The final staging helper's archive matched the VM-tested OCI payload file for file by SHA-256.

**Review follow-up.** The runbook now checks the exact project volume name before fresh startup. On Engine 29.1.3, `docker volume ls --format '{{.Name}}'` succeeded. With the Docker response stubbed, the shell guard continued when the name was absent or only a similarly named volume existed, and stopped on an exact match or a failed listing. The separate restart procedure uses the existing volume. `make test-unit` passed 23 tests, including mocked registry tests that reject altered bytes at each digest boundary, reject an index with no amd64 manifest, and compare the generated OCI archive's descriptor and exact member contents. [Docker volume listing](https://docs.docker.com/reference/cli/docker/volume/ls/)

## Interpretation and limitations

**Verified documentation, reviewed 2026-11-25.** PostgreSQL 16 evaluates `max_slot_wal_keep_size` at checkpoints, and a slot may become unusable when necessary WAL is removed. `max_wal_size` is a soft target. Docker Compose's CPU and memory options set container limits, and the local logging driver rotates by size and file count. [PostgreSQL 16.16 release](https://www.postgresql.org/docs/16/release-16-16.html) · [Replication settings](https://www.postgresql.org/docs/16/runtime-config-replication.html) · [WAL settings](https://www.postgresql.org/docs/16/runtime-config-wal.html) · [Compose service keys](https://docs.docker.com/reference/compose-file/services/) · [Docker local logging driver](https://docs.docker.com/engine/logging/drivers/local/)

**Observed staging limitation.** Explicit `docker load --platform linux/amd64` on Engine 29.1.3 rejected the sparse OCI archive with `content digest sha256:d200884353ae00dc87ac1ee50ae7077afe3799373328a58befcb732c9013bf3f: not found` (the index's amd64 attestation descriptor). Plain `docker load -i` loaded the same index digest with the amd64 image present. The second source run used the archive generated by the checked-in script. [Docker image load](https://docs.docker.com/reference/cli/docker/image/load/) · [OCI image layout v1.1.1](https://github.com/opencontainers/image-spec/blob/v1.1.1/image-layout.md)

An attempt at 11:02:33 UTC still saw the original media after swapping the virtual CD. The fresh-volume guard stopped it before bridge creation because the original project volume existed. Ejecting and attaching the new media, checking the archive hash in the guest and using a new project cleared the prerequisite for the second run.

**Decision.** Use the measured lab limits and the operator stop thresholds in the runbook. The sample shows the physical publisher footprint at idle and after one small transaction. Volume growth under load, log rotation after filling a file, crash recovery, active/inactive slot retention and replication client compatibility need separate tests. The peer authenticated as the disposable bootstrap superuser over the lab network. Workload identities belong to subsequent tickets.

**Follow-up.** R01, R04 and R05 remain open. Test the actual consumer, resulting slot and retention behavior in Phase 2. [Research register](../research-questions.md)
