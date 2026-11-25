# PostgreSQL source profile

The [`source` profile](../compose.source.yaml) starts `source-db` on an isolated `source-input` bridge. Use the dedicated disconnected VM and firewall procedure in the [1.1 source startup gate](source-runbook.md#dedicated-vm-procedure-for-ticket-12). Use the administrator only for this disposable bootstrap and the following checks. The profile starts with an empty `source_lab` database. Follow [schema setup](source-schema.md) and then the [sequential fixture runner](source-runner.md) to populate and inspect it. [Runtime evidence](experiments/EXP-004-source-profile.md)

## Stage and start

On the staging machine, with Python 3.12 and access to Docker Hub, create the linux/amd64 archive and transfer it, the repository and the [pinned 1.1 probe image](source-runbook.md#reproduce-the-negative-experiment) on read-only media. The archive retains the approved multi-platform index and includes the verified amd64 layers. Use the containerd image store in the offline guest.

```sh
mkdir -p artifacts
python3 scripts/source/stage-image.py artifacts/source.tar
```

From the repository root inside the VM, use a fresh Compose project name per disposable run. The guard checks the exact volume name before creating the secret or bridge. If the volume exists, choose a different project name for the fresh experiment. Record the project name and keep it together with the secret for the [restart procedure](#verify-a-clean-restart-and-stop).

```sh
set -eu
labdocker() { docker --host unix:///var/run/docker.sock "$@"; }
export COMPOSE_PROJECT_NAME=cdc-source-12
export COMPOSE_FILE="$PWD/compose.source.yaml"
source_compose() { labdocker compose -f "$COMPOSE_FILE" --profile source "$@"; }
source_gate() { python3 scripts/isolation/preflight.py --start-compose "$COMPOSE_FILE"; }

expected_volume="${COMPOSE_PROJECT_NAME}_source-pg"
local_volumes=$(labdocker volume ls --format '{{.Name}}')
if printf '%s\n' "$local_volumes" | grep -Fxq -- "$expected_volume"; then
    printf 'STOP: volume %s already exists. Choose a fresh project name for this experiment.\n' "$expected_volume" >&2
    exit 1
fi

image=$(sed -n 's/^    image: //p' "$COMPOSE_FILE")
labdocker load -i /mnt/source/source.tar
labdocker image inspect "$image" --format '{{.Os}}/{{.Architecture}} {{.Id}} {{json .RepoDigests}}'
labdocker image ls --tree postgres

# On a fresh project only. Keep the file for subsequent starts.
mkdir -m 0700 -p secrets
(umask 077; set -C; openssl rand -hex 32 > secrets/source-db-password)

# Provision the actual source network while the source remains stopped.
br=cdc-src12
SOURCE_INPUT_ID=$(labdocker network create --internal --ipv6 \
  --opt "com.docker.network.bridge.name=$br" "${COMPOSE_PROJECT_NAME}-input")
export SOURCE_INPUT_ID
mkdir -p artifacts
source_compose config -q
source_compose config > artifacts/source.resolved.yaml
labdocker network inspect "$SOURCE_INPUT_ID" --format '{{.Name}} {{.Internal}} {{.EnableIPv6}} {{json .IPAM.Config}}'
df -Pk "$(labdocker info --format '{{.DockerRootDir}}')"
```

The resolved model must show only `source-db`, a single external network referenced by the full captured ID, the named volume and the file-backed secret. Published ports, host networking, custom DNS, proxy environment, privileged mode and host sockets must be absent. Check the disk thresholds below. If reproducing the negative control on a fresh VM, `source_gate` before the firewall rules must fail and `source_compose ps --all -q` must be empty. Apply the IPv4 and IPv6 bridge rules before running the gate. [1.1 firewall procedure](source-runbook.md#dedicated-vm-procedure-for-ticket-12)

```sh
source_gate
cid=$(source_compose ps -q source-db)
for attempt in $(seq 1 30); do
    [ "$(labdocker inspect -f '{{.State.Health.Status}}' "$cid")" != healthy ] || break
    sleep 2
done
test "$(labdocker inspect -f '{{.State.Health.Status}}' "$cid")" = healthy
labdocker inspect -f '{{json .State.Health.Log}}' "$cid"
test "$(labdocker inspect -f '{{range .NetworkSettings.Networks}}{{.NetworkID}}{{end}}' "$cid")" = "$SOURCE_INPUT_ID"
test -z "$(labdocker port "$cid")"
labdocker inspect -f 'bindings={{json .HostConfig.PortBindings}} ports={{json .NetworkSettings.Ports}}' "$cid"
```

Stop on a gate or health failure and inspect `source_compose logs --tail=40 source-db`. The health check runs a loopback TCP query with `psql` and requires SCRAM. The image reads `POSTGRES_PASSWORD_FILE` at container startup, and uses the value to initialize the role on a fresh volume. Editing the file alone leaves the stored password as it was. Keep the secret root-owned and mode `0600` in the dedicated VM. Compose mounts it as a file and the health check passes its value through a short-lived local client environment. Avoid dumping process environments or enabling shell tracing. [Official image entrypoint](https://github.com/docker-library/postgres/blob/ac9627dcf544a8454f212a12ddeebfcdc0803d3e/docker-entrypoint.sh) · [libpq environment](https://www.postgresql.org/docs/16/libpq-envars.html)

## Verify from a peer

The one-shot client joins the same verified bridge and reads its password over standard input. A valid client must return `source_admin|source_lab|t|256`. The invalid client must exit nonzero with `password authentication failed`. Confirm the HBA rule in the server log and verify that the HBA view has no parse errors.

```sh
secret=$PWD/secrets/source-db-password
peer_psql() {
    labdocker run --rm -i --pull never --network "$SOURCE_INPUT_ID" \
      --memory 96m --cpus 0.5 --pids-limit 32 --read-only --cap-drop ALL \
      --env PGCONNECT_TIMEOUT=3 --env PGREQUIREAUTH=scram-sha-256 \
      --env PGOPTIONS='-c statement_timeout=5000' --env LC_ALL=C --entrypoint sh "$image" \
      -ec 'IFS= read -r PGPASSWORD; export PGPASSWORD; exec psql -Xw -v ON_ERROR_STOP=1 -h source-db -U source_admin -d source_lab "$@"' sh "$@"
}
test "$(peer_psql -Atc 'SELECT current_user, current_database(), inet_client_addr() IS NOT NULL, 16 * 16;' <"$secret")" = 'source_admin|source_lab|t|256'
peer_psql -Atc 'SELECT current_user, current_database(), inet_client_addr(), inet_server_addr(), 16 * 16;' <"$secret"
if printf '%s\n' 'intentionally-incorrect' | peer_psql -Atc 'SELECT 1;' >artifacts/rejected.txt 2>&1; then
    echo 'Unexpected authentication success' >&2
    exit 1
fi
grep -F 'password authentication failed for user "source_admin"' artifacts/rejected.txt
source_compose logs --tail=25 source-db
peer_psql -P pager=off -c 'SELECT version(); SELECT line_number,type,database,user_name,address,auth_method,error FROM pg_hba_file_rules ORDER BY line_number;' <"$secret"
peer_psql -P pager=off -c "SELECT name,setting,unit,source FROM pg_settings WHERE name IN
 ('max_connections','shared_buffers','password_encryption','wal_level','max_wal_senders','max_replication_slots',
  'max_slot_wal_keep_size','wal_keep_size','min_wal_size','max_wal_size','checkpoint_timeout','wal_segment_size',
  'archive_mode','logging_collector','log_connections') ORDER BY name;" <"$secret"
test "$(peer_psql -Atc 'SELECT (SELECT count(*) FROM pg_publication), (SELECT count(*) FROM pg_replication_slots);' <"$secret")" = '0|0'
```

## Verify limits and storage

Expect 805306368 bytes of memory, CPU quota `100000 100000` on cgroup v2, zero container swap, 128 PIDs, and Docker `local` log rotation at 5 MB across three files. PostgreSQL allows 20 connections, has 128 MiB shared buffers, and writes connection and checkpoint messages to the Docker log. The local volume lives on the guest's Docker filesystem. Check the volume, physical WAL and free space before writes, at each bounded checkpoint and after restart.

```sh
labdocker inspect -f 'memory={{.HostConfig.Memory}} memorySwap={{.HostConfig.MemorySwap}} nanoCPUs={{.HostConfig.NanoCpus}} pids={{.HostConfig.PidsLimit}} shm={{.HostConfig.ShmSize}} oomKilled={{.State.OOMKilled}} log={{json .HostConfig.LogConfig}}' "$cid"
test "$(labdocker exec "$cid" cat /sys/fs/cgroup/memory.max /sys/fs/cgroup/memory.swap.max /sys/fs/cgroup/cpu.max)" = "$(printf '805306368\n0\n100000 100000')"
labdocker exec "$cid" sh -c 'for ctl in memory.max memory.swap.max cpu.max pids.max memory.events cpu.stat; do echo "$ctl"; cat "/sys/fs/cgroup/$ctl"; done'
labdocker stats --no-stream --format '{{.CPUPerc}} {{.MemUsage}} {{.BlockIO}} {{.PIDs}}' "$cid"
mounted_volume() {
    labdocker inspect -f '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}' "$cid"
}
volume=$(mounted_volume)
test "$volume" = "${COMPOSE_PROJECT_NAME}_source-pg"
labdocker volume inspect "$volume" --format 'name={{.Name}} driver={{.Driver}} labels={{json .Labels}}'

disk_sample() {
    peer_psql -Atc 'SELECT count(*), coalesce(sum(size), 0) FROM pg_ls_waldir();' <"$secret"
    labdocker exec "$cid" sh -ec 'du -sk "$PGDATA"; du -sk "$PGDATA/pg_wal"; df -Pk "$PGDATA"'
}
disk_sample
```

**Stop thresholds.** Pause writes and cleanly stop the source if allocated WAL reaches 256 MiB (262144 KiB), the database directory reaches 512 MiB (524288 KiB, including WAL), free space falls below 1 GiB (1048576 KiB), or an OOM event occurs. These are operator stop thresholds. Docker's memory cap and log rotation do not impose a quota on the volume.

**WAL behavior.** Two sender and two slot positions are configured. The 128 MiB `max_slot_wal_keep_size` is evaluated at checkpoints. WAL needed by a slot that falls beyond the allowed span can be removed and the slot can then become unusable. The 128 MiB `max_wal_size` is a soft checkpoint target. Checkpoint timing, bursts and ongoing WAL activity can cause disk use to exceed either setting. `du` measures allocated space and `pg_ls_waldir()` reports PostgreSQL's directory entries and file sizes. Keep both measurements separate from slot LSNs. [PostgreSQL 16 replication settings](https://www.postgresql.org/docs/16/runtime-config-replication.html) · [PostgreSQL 16 WAL and checkpoints](https://www.postgresql.org/docs/16/runtime-config-wal.html)

## Verify a clean restart and stop

Use the disposable project already initialized above for the sentinel. Keep the same `COMPOSE_PROJECT_NAME` and secret through the stop and restart. After removing the old container, verify that the volume still exists before running the gate on the empty bridge.

```sh
sentinel='7|source-profile-1.2'
peer_psql -c "CREATE TABLE source_profile_sentinel (id integer PRIMARY KEY, value text NOT NULL);
INSERT INTO source_profile_sentinel VALUES (7, 'source-profile-1.2');" <"$secret"
test "$(peer_psql -Atc 'TABLE source_profile_sentinel;' <"$secret")" = "$sentinel"
peer_psql -c 'CHECKPOINT;' <"$secret"
disk_sample
previous=$cid
source_compose stop
test "$(labdocker inspect -f '{{.State.ExitCode}} {{.State.OOMKilled}}' "$cid")" = '0 false'
source_compose logs --tail=10 source-db
source_compose down
labdocker volume inspect "$volume" --format 'retained={{.Name}}'
source_gate
```

Repeat the health wait and `cid` assignment above, then check the recovered value.

```sh
test "$cid" != "$previous"
test "$(mounted_volume)" = "$volume"
test "$(peer_psql -Atc 'TABLE source_profile_sentinel;' <"$secret")" = "$sentinel"
test "$(peer_psql -Atc 'SELECT (SELECT count(*) FROM pg_publication), (SELECT count(*) FROM pg_replication_slots);' <"$secret")" = '0|0'
disk_sample
peer_psql -c 'DROP TABLE source_profile_sentinel;' <"$secret"
source_compose down
labdocker volume inspect "$volume" --format 'retained={{.Name}}'
```

Use the [1.1 rollback commands](source-runbook.md#dedicated-vm-procedure-for-ticket-12) to remove the two rules in each firewall family, then run `labdocker network rm "$SOURCE_INPUT_ID"`. For a later start, set the recorded project name, confirm `${COMPOSE_PROJECT_NAME}_source-pg` exists with `labdocker volume inspect`, and keep the original secret file. Provision a new bridge using the network commands above, apply its firewall rules, and rerun the gate and health checks.
