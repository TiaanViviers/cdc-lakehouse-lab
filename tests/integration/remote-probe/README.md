# EXP-011 one-table probe

Run this experiment only in the scheduled disconnected lab guest. It creates and removes its own PostgreSQL clusters, Docker volumes, bridge and firewall rules. Use a fresh VM overlay and fresh repository copy each time. The publisher uses the existing [Phase 1 source profile](../../../docs/source-profile.md) and enrollment SQL. The consumer overlay exists for this experiment. See [ticket 2.1](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/38) and [ADR-002](../../../docs/decisions/ADR-002-phase-2-local-cdc-probe.md).

## Stage the images and revision

On the online staging host, from the repository root, create the two linux/amd64 OCI archives. Apply the two pin changes to a scratch copy of the existing index-preserving source staging script. This fetches by digest and hashes the index, selected manifest, config and layers. Keep the third, [pinned isolation-probe archive](../../../docs/source-runbook.md#reproduce-the-negative-experiment), under the filename `probe.tar`. The isolation preflight verifies its image ID before use.

```bash
media=$(mktemp -d)
python3 scripts/source/stage-image.py "$media/source.tar" | sed 's/^/source /' > "$media/images.txt"
sed -e 's#library/postgres#pgducklake/pipe-ci-builds#g' \
    -e 's/cd0e9518bda5f2ea667ff84d22795d089720c883f288e215d97ce57437e8ef37/091236d2acecfec1216817aff6e43dc4c036159cebe44a19c73c95c1fe9be348/' \
    scripts/source/stage-image.py > "$media/stage-consumer.py"
python3 "$media/stage-consumer.py" "$media/consumer.tar" | sed 's/^/consumer /' >> "$media/images.txt"
rm "$media/stage-consumer.py"
cp /path/to/pinned/probe.tar "$media/probe.tar"
git archive --format=tar --prefix=repo/ HEAD > "$media/repo.tar"
git rev-parse HEAD > "$media/revision"
(cd "$media" && sha256sum source.tar consumer.tar probe.tar images.txt repo.tar revision > SHA256SUMS)
xorriso -as mkisofs -quiet -r -J -o exp011.iso "$media"
```

Expect the image identities shown in EXP-011. The archive SHA-256 can vary when restaging the same OCI content because file timestamps are part of the tar.

## Run in the guest

Reserve the single runtime window with the maintainer. Use the Phase 1 guest base with 2 vCPUs, 2 GiB RAM, no NIC (`-nic none` in QEMU), the local rootful Docker Engine with containerd store on cgroup v2 and the iptables backend in both families. Attach the ISO read-only. Review [the source bridge procedure](../../../docs/source-runbook.md#dedicated-vm-procedure-for-ticket-12) and the two Compose files before startup. The runner applies that procedure to its empty bridge before starting PG16, then adds the one consumer.

From the guest root console, with the local daemon running and existing lab stacks stopped, run these commands in a fresh directory.

```bash
mkdir /mnt/exp011 /root/exp011
mount -o ro /dev/sr0 /mnt/exp011
(cd /mnt/exp011 && sha256sum -c SHA256SUMS)
tar -xf /mnt/exp011/repo.tar -C /root/exp011
cd /root/exp011/repo
export PROBE_SHA="$(cat /mnt/exp011/revision)"
export PROBE_OVERLAY=guest-01.qcow2  # Use the actual overlay identity.
timeout --foreground -k 35s 480s bash tests/integration/remote-probe/run.sh /mnt/exp011
```

The evidence directory is `artifacts/EXP-011/<UTC-run-id>/`. Keep the two PostgreSQL logs and SQL observations with the resolved Compose file, exact rows, resource measurements and teardown checks. Export only the redacted experiment evidence through the guest console. The files in `secrets/` and both volumes belong to the disposable guest. Prior to a successful run, the script intentionally stops at the first failed assertion so later mutations cannot hide the boundary.

## Minimal API sequence for 2.5

The runner above provides the executable, bounded reproducer and three native-SQL observation queries. The consumer-side SQL interfaces under test are shown below. The publisher role needs SCRAM, LOGIN, REPLICATION, database CONNECT and CREATE, and ownership of the single registered table. Start with the seed row already committed, one available persistent slot and one available temporary slot. Supply the probe password through a local secret and the connection string through standard input.

```sql
CREATE SCHEMA bronze;
SELECT duckpipe.create_group(:'group', publication => :'publication', slot_name => :'slot',
    conninfo => :'disposable_conninfo', mode => 'bgworker');
SELECT duckpipe.add_table('probe.items', target_table => 'bronze.items', sync_group => :'group',
                          copy_data => true, sync_mode => 'upsert');
SELECT id, value FROM bronze.items ORDER BY id, value LIMIT 3;
SELECT duckpipe.remove_table('probe.items', drop_target => false, sync_group => :'group');
SELECT duckpipe.drop_group(:'group');
```

Use consumer-local `psql` with query routing off. Pause at each checkpoint for exact parity before committing the next mutation on PG16. Compare the source inventory after `drop_group` and stop the consumer before any scoped fallback cleanup. Keep the group, publication, slot and bridge IDs unique per run.
