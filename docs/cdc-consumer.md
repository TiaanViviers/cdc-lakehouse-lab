# Local DuckPipe consumer profile

Ticket [2.5](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/42) packages the [reviewed one-table remote path](experiments/EXP-011-remote-pg16-probe.md). The `cdc-catalog` service runs PG18.4 with DuckPipe, pg_ducklake and pg_duckdb on the Phase 2 bridge. The stock PG16.16 publisher stays at `source-db:5432/source_lab`. Apply [ADR-002](decisions/ADR-002-phase-2-local-cdc-probe.md) and the [Phase 2 runtime conventions](../backlog/phase-2.md#parallel-development-and-runtime-conventions).

## Stage and verify the image

On the online staging host, from the repository root, prepare read-only transfer media. Obtain `probe.tar` through the [source isolation procedure](source-runbook.md#reproduce-the-negative-experiment). The consumer staging command preserves the registry index and includes only the approved linux/amd64 payload. It verifies the manifest, config and every selected layer before publishing the archive.

```bash
media=$(mktemp -d)
python3 scripts/source/stage-image.py "$media/source.tar"
python3 scripts/cdc/consumer/image.py stage "$media/consumer.tar"
cp /path/to/approved/probe.tar "$media/probe.tar"
git archive --format=tar --prefix=repo/ HEAD > "$media/repo.tar"
git rev-parse HEAD > "$media/revision"
(cd "$media" && sha256sum source.tar consumer.tar probe.tar revision repo.tar > SHA256SUMS)
xorriso -as mkisofs -quiet -r -J -o cdc-consumer.iso "$media"
```

Reserve exclusive VM access with the maintainer or current runtime owner. Coordinating ticket runs on the shared lab host uses `flock -x /tmp/cdc-lab-vm-runtime.lock` for the lifetime of the guest process. Create a fresh overlay of the approved lab guest, with 2 vCPUs, 2 GiB RAM, no NIC, read-only media and the local rootful Docker daemon using its containerd store and iptables backend in both address families.

### Reproduce EXP-015

In the scheduled guest root console, start Docker and run the whole one-table acceptance sequence on a fresh guest overlay with the images still absent. The runner creates its own project and bridge, applies the source gate, imports the artifacts and exercises startup, authentication, exact rows, file-backed storage, recreation and teardown. It keeps the checked Compose configuration and observations under `artifacts/EXP-015/<run>/`.

```bash
mkdir /mnt/exp015 /root/exp015
mount -o ro /dev/sr0 /mnt/exp015
(cd /mnt/exp015 && sha256sum -c SHA256SUMS)
tar -xf /mnt/exp015/repo.tar -C /root/exp015
cd /root/exp015/repo
export CDC_REVISION="$(cat /mnt/exp015/revision)"
export CDC_OVERLAY=guest-01.qcow2  # Use the actual overlay identity.
timeout --foreground -k 60s 480s bash tests/integration/cdc-consumer/run.sh /mnt/exp015 </dev/null
```

### Add the consumer to an enrolled source run

In the disconnected guest, verify the media checksums and `python3 scripts/cdc/consumer/image.py verify /mnt/exp015/consumer.tar` before `docker image load -i /mnt/exp015/consumer.tar`. Verify `docker image inspect` reports the pinned index ID and linux/amd64. Use the enrolled source's unique `COMPOSE_PROJECT_NAME` and full `SOURCE_INPUT_ID` from its successful empty-bridge preflight. Verify the bridge retains its IPv4 and IPv6 rules and that its sole peer is the expected publisher.

Generate `secrets/cdc-catalog-password` once per new project with `openssl rand -hex 24` in the root-only `secrets/` directory. Make the file readable by the container's postgres OS user (`chmod 0444` within that directory). Keep the same secret with the volume through recreation. The image uses it to set the database password on first initialization.

```bash
stack=(docker --host unix:///var/run/docker.sock compose -f compose.source.yaml -f compose.cdc.yaml --profile source --profile cdc)
"${stack[@]}" config
"${stack[@]}" up -d --wait --wait-timeout 60 --no-deps --no-build --pull never cdc-catalog
consumer_id=$(docker inspect -f '{{.Id}}' "$("${stack[@]}" ps -q cdc-catalog)")
bash scripts/cdc/consumer/psql.sh "$consumer_id" < scripts/cdc/consumer/bootstrap.sql
```

Check the resolved configuration and actual container for exactly one network with the verified ID, no published ports and the expected project and `cdc-pg` volume labels. Record the image/member/config, project/bridge/volume, source and target database, and the explicit mappings for your run. Use the small connector configuration in `bootstrap.sql` before registering via the [2.1 API sequence](../tests/integration/remote-probe/README.md#minimal-api-sequence-for-25) and the Phase 2 publisher contract. Send secret-bearing SQL on stdin, keep shell tracing off and keep raw errors, connector configuration dumps and conninfo out of shared evidence. Query routing is explicitly off. Use direct `bronze.<table>` queries for exact parity.

### Authentication and observations

The pinned image's init scripts allow passwordless loopback TCP for the embedded DuckDB PostgreSQL scanner and retain local socket trust. Only the disposable consumer's process and network namespaces have that loopback. The consumer has one endpoint on the already-gated internal bridge. Its other TCP connections require SCRAM through the image's host HBA. The authenticated health probe connects to the service address through Docker DNS with `PGREQUIREAUTH=scram-sha-256`, a short connect/statement timeout and a trivial SQL query. Host ports are unpublished. Keep this profile inside the approved VM boundary.

```bash
bash scripts/cdc/consumer/status.sh "$consumer_id" "$group" "$run_id" "$checkpoint" "$elapsed_ms"
python3 scripts/cdc/consumer/catalog.py "$consumer_id"
```

- The status sample is one JSON object from authenticated read-only SQL. Supply the same run/checkpoint labels and elapsed milliseconds from the caller's monotonic clock for publisher and consumer samples. It reports a group checkpoint, table snapshot and apply LSNs, mappings, error presence, worker backend PIDs and queue metrics. It caps mappings at 32 with an overflow flag. It omits raw errors and conninfo. The pinned queue function returns default-valued fields even after the group worker stops, so use the PID list for backend presence. Null identifies missing observations. Healthy means the authenticated SQL endpoint answered. Establish replication progress from sequential scoped observations and correctness from independently compared source and target rows.
- The catalog inspection reads the latest 16 snapshots, the live Bronze table/storage metadata, inlining option overrides, and at most 32 entries per inventory. It resolves paths under the pinned local root and verifies live referenced file size, Parquet magic and SHA-256. Run it at a quiescent hold point so physical verification follows a stable metadata read. A missing option row means no explicit catalog override at that scope.
- The named `cdc-pg` volume is mounted at `/var/lib/postgresql`. PGDATA at `/var/lib/postgresql/18/docker` holds catalog/worker state. Its `pg_ducklake/` subdirectory holds the referenced files. Both survive container recreation as one volume. Temporary DuckDB work uses the 64 MiB `/tmp` tmpfs with a 48 MiB DuckDB temp limit. Docker caps consumer memory at 512 MiB with zero swap, CPU at 0.75, PIDs at 128 and the local logs at three 5 MiB files.

## Stop, recreate or tear down

Stop only the verified consumer and keep its volume and credentials for a planned same-state test. Recreate with `up -d --force-recreate --no-deps --no-build --pull never cdc-catalog` using the same Compose project and then obtain the new full container ID. Compare PG cluster identity, catalog, status and exact direct rows with a fresh connection. EXP-015 holds the group stopped throughout recreation to test storage independently of source replay.

For disposal, verify the project, complete bridge ID, container and volume labels, and quiesce the specific worker. Remove the mapping and group with the connector API and check the named slot and publication are gone. Hand any unresolved publisher objects to the owning publisher lifecycle procedure before destroying the consumer. Stop the service and check its exact exit/OOM result. On the disposable acceptance project, the runner confirms the labelled workloads, volumes and exact external bridge are gone before removing the bridge firewall rules. A failed stop, removal or inventory check ends cleanup and reports the remaining assets and rules. The failed run keeps its root-only credentials for investigation. The acceptance control injects a stop failure with both containers still running and tests that their bridge protections continue to deny host connections in both families. Inspect the experiment output for `project_cleanup_exit=0` as well as the acceptance marker.
