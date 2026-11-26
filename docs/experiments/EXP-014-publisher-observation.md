# EXP-014 — Independent publisher replication and WAL observation

- **Date** 2026-11-26
- **Research question IDs** R04, R05, R16
- **Status** Passed offline, source-only and accepted active-consumer checks.
- **Operator** Ticket 2.4 ([issue #41](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/41))
- **Git branch** `feature/2.4-publisher-observation`, rebased onto `500c213` after the 2.1 merge
- **Software / images** CPython 3.12.3 observed offline. Observed PostgreSQL and psql 16.16 (Debian 16.16-1.pgdg12+1) on the pinned Bookworm source. The active guest used the accepted pinned PG18.4 DuckPipe build. Image index, platform member and config identities matched [EXP-011](EXP-011-remote-pg16-probe.md#image-provenance).

## Hypothesis

An independent source-local observer can identify the expected publication and slot, track publisher positions and attributable feedback, and report WAL retention and disk use within an explicit observation budget. The same interface can represent the absence of replication objects and an inactive slot.

## Preconditions

Run offline checks on the workstation. Schedule the disconnected VM with the maintainer after ticket 2.1 has priority. For the source-only run, use a unique project, bridge, source volume and credentials. Stage this checkout, the pinned images and the isolation probe on read-only media. Follow the [EXP-011 guest procedure](../../tests/integration/remote-probe/README.md#run-in-the-guest) and verify both firewall families, Compose and volume identity, healthy PG16.16 and the source limits before provisioning the synthetic fixture. Use a separate fresh environment for the active trial. The merged [EXP-011 result](EXP-011-remote-pg16-probe.md) accepts the pinned PG18.4 DuckPipe build and its DuckLake 0.4 catalog for this one-table sequence.

Record the owner, run ID, tested SHA, VM overlay, Compose/volume/bridge IDs, image IDs, resolved configuration, database and selected group/publication/slot in a fresh private `artifacts/EXP-014/<UTC-run-id>/`. Record the existing source cgroup, WAL settings and disk checks from the [source profile](../source-profile.md#verify-limits-and-storage). Stop workload generation on sampler error, threshold breach, lost isolation or OOM. The experiment owner controls teardown.

**Decision.** Use the existing authorized disposable `source_admin` connection over source-local loopback and SCRAM, as in the Phase 1 source gate. The observer uses a read-only transaction with a restricted search path. Docker access and the admin role are privileged lab access. This experiment grants no new roles or privileges. Keep credentials in the guest-local secret file. Preserve only allow-listed client output and record generic error codes for failures.

## Procedure

1. Run `make check` and `make test-unit`. The publisher unit tests use synthetic responses with no Docker or PostgreSQL dependency.
2. Stage the pinned images and committed checkout as in the [EXP-011 reproduction](../../tests/integration/remote-probe/README.md#stage-the-images-and-revision). Use the same single-runtime lock, two-vCPU / 2 GiB no-NIC guest and read-only ISO. Use fresh overlays for `source` and `active`, in that order. The trial generates a scratch script from the merged reproducer, checks that its insertion points match, and keeps its pin, firewall, resource and cleanup guards. It uses the reproducer's deterministic `probe.items` values for both trials. The source trial stops before consumer startup.
3. For each guest, mount the media, verify its checksum manifest, extract the checkout and start the local daemon as in EXP-011. From the extracted repository root, run:

   ```bash
   export PROBE_SHA="$(cat /mnt/exp011/revision)"
   export PROBE_OVERLAY=guest-source.qcow2
   trial=source   # Use active on the separate guest, with its actual overlay name.
   python3 -m scripts.cdc.wal.trial instrument "$trial" >/tmp/exp014-run.sh
   bash -n /tmp/exp014-run.sh
   timeout --foreground -k 35s 480s bash /tmp/exp014-run.sh /mnt/exp011 </dev/null
   ```

4. The source trial captures empty inventory, then creates an explicit publication for `probe.items` and an inactive persistent `pgoutput` slot. It verifies exact source rows before and after the independent insert of `(2, 'inserted')`, samples both positions with one observer, and compares native catalog output. It checks rejection of an unexpected name and of an additional inactive slot under the two-slot cap, and checks a one-microsecond observation deadline. Guarded teardown verifies zero remaining slots and publications and unchanged Phase 1 fixture privileges.
5. The active trial uses the accepted snapshot and three DML checkpoints. It checks that the temporary snapshot slot has cleared before starting the observation timeline. At each hold, the merged reproducer checks exact independently read source and target rows. The observation process keeps one monotonic origin for all four live samples. After guarded connector teardown, it captures the empty baseline again.
6. For independent consumption, invoke `python3 -m scripts.cdc.wal.observe --help`. Supply the full container and bridge IDs, Compose project and enrolled PostgreSQL system ID from the recorded run. Request an empty baseline without slot, publication or member arguments. To sample the active hold points, supply the approved names and one `--member schema.table` per expected table. A caller with its own checkpoint driver can reuse `Observer.sample(phase, checkpoint)` on one observer object.

## Expected results

- Empty inventory has null slot, publication, feedback and slot-related spans, plus an empty membership array. Current source LSNs and disk counters are present.
- The inactive baseline identifies the exact logical `pgoutput` slot and `probe.items` membership. It has `active: false`, null PID and null feedback. After the insert, source key 2 has value `inserted` and key 1 still has value `seed`, and the slot's confirmed flush and restart positions remain unchanged with no consumer. The insertion position increases across the committed write and the insert-to-restart span grows. Disk allocation may stay unchanged.
- Independently recompute each populated slot span by converting the hexadecimal halves of the two LSNs to one integer each and subtracting. Compare same-history samples and check increasing monotonic observation boundaries. Use scoped source SQL to corroborate membership and slot state. In the active trial, verify the expected slot is active and any feedback PID matches that slot. Compare before/after feedback with the source commits and corroborate data visibility using exact target keys and values.
- The unexpected-name and extra-slot cases return `slot_identity` and null telemetry. An exhausted wall budget returns a trace row and nonzero status, with `deadline_exhausted` or `capture_timeout` depending on whether a command began.

## Actual observations

**Observed offline.** `python3 -m scripts.cdc.wal.observe --help` exposed the publisher invocation. `make test-unit` passed 32 tests, including eight publisher tests for empty/inactive samples, synthetic feedback, membership and slot identity, bounded attempts, deadline exhaustion, timeout redaction and an observation timeline with a backwards UTC clock. The inactive synthetic fixture retained null feedback and reported a 16-byte between-sample span. The mock deadline invoked no Docker command. A CLI smoke check with synthetic identities and `--budget-seconds 0.000001` exited 1 and emitted one JSONL row with `deadline_exhausted` and null SQL/disk data. `make check` passed.

**Attempt 01, source only.** Run `20261126t082520z` on `8c8a0084d2b7419225c1bea69833974826846f3a` reached the observer checks and exited 1 at a verifier assertion that compared the entire slot JSON. The actual restart and confirmed positions matched before and after. The headroom field `safe_wal_size` decreased by 184 bytes as WAL advanced. The rerun checks the two expected stable positions and keeps headroom as its own measurement. Teardown removed the run's resources and reported an empty slot/publication inventory.

**Attempts 02 and 03.** The source-only run `20261126t082603z` and active run `20261126t082647z` both tested `2a2c48535d6d39d2b37bf99998ce61212a1e0942` and exited 0 on separate fresh no-NIC overlays. Ubuntu 24.04.5 ran Linux 6.8.0-147, Engine 29.1.3 and Compose 2.40.3 on cgroup v2. The empty-bridge preflight verified the firewall controls in both families before each source startup. The active project used separate single-homed source and consumer containers, separate named volumes and no published ports.

**Source-only result.** Empty inventory returned nulls for slot, publication, feedback and all slot spans. Native SQL independently matched the sampled `probe.items` membership and inactive slot positions. Exact rows changed from `(1, 'seed')` to `(1, 'seed'), (2, 'inserted')`. At 0.170 s and 0.458 s on the same observer clock, publisher insert/write/flush moved from `0/19A90B0` to `0/19A9168`. Restart stayed at `0/19A9078` and confirmed flush at `0/19A90B0`. The insert-to-restart span grew from 56 to 240 bytes while allocated WAL stayed at 16,392 KiB. Safe WAL size moved from 140,865,360 to 140,865,176 bytes. Both slot-identity failures exited 1 with null SQL and disk data. The one-microsecond observation returned `deadline_exhausted` with the same nulls.

**Active result.** The publication contained only `probe.items`. One persistent `pgoutput` slot remained after initial copy. Every active sample attributed its sender by the slot PID, 267 in this run. The slot was `reserved` throughout. The verifier independently recomputed the three WAL spans from the hexadecimal LSNs and confirmed monotonic sample windows. Source and direct target reads matched at each hold. The target had no key 2 and no duplicate keys after delete.

| Hold | Exact source and target rows | Sample elapsed (s) | Publisher insert LSN | Restart LSN | Confirmed flush LSN | Insert to restart (bytes) |
| --- | --- | ---: | --- | --- | --- | ---: |
| Initial | `(1, 'seed')` | 0.173 | `0/19A9318` | `0/19A92A0` | `0/19A92D8` | 120 |
| Insert | `(1, 'seed'), (2, 'inserted')` | 6.932 | `0/19A9408` | `0/19A92A0` | `0/19A9318` | 360 |
| Update | `(1, 'updated'), (2, 'inserted')` | 11.894 | `0/19A9498` | `0/19A92A0` | `0/19A9318` | 504 |
| Delete | `(1, 'updated')` | 16.787 | `0/19A9518` | `0/19A93D0` | `0/19A9408` | 328 |

Sender write/flush/replay feedback matched sampled confirmed flush in these reads. The initial lag fields were null. At update parity, confirmed flush remained at its preceding value and PostgreSQL reported a replay lag of about 11.44 s. The target poll had already passed after 4 whole seconds on the reproducer's checkpoint timer. These different clocks and fields describe distinct boundaries. No transaction commit/end LSN was attributed. The independent target reads demonstrate visibility at the holds. Durable application and restart recovery remain open.

**Resources and teardown.** Active PGDATA peaked at 47,352 KiB in the sampler, with 16,392 KiB of allocated WAL and at least 3,668,908 KiB of free space. Source and consumer memory peaks at the active hold points were about 129 and 144 MiB, and OOM counters stayed zero. The 768 MiB source and 512 MiB consumer had zero container swap. Both PostgreSQL processes exited 0 in the active trial. Each passing run verified `after|0|0|t|t`, preserved the Phase 1 fixture ACL inventory and disposed of the owned volumes and bridge. On the active run, the post-group sampler also returned the empty baseline.

## Evidence artifacts

The ignored worktree directory `artifacts/EXP-014/` contains exported trial bundles and `SHA256SUMS`. From that directory, `sha256sum -c SHA256SUMS` verified all three exports. The bundles include exact sampled JSONL, redacted SQL and log evidence, source/target rows, resource counters, identity and teardown checks. The commands above reproduce them from the tested source revision.

| Archive | SHA-256 |
| --- | --- |
| `attempt-01-source.tar.gz` | `77112b9e515412898960068974c4930d94dbd8fc73e5c4653130326f628c955d` |
| `attempt-02-source.tar.gz` | `a2ff4beb2c172f926b849f996ceb22e4e59023546d2a0ab5c832a1ce6989863f` |
| `attempt-03-active.tar.gz` | `cca0082d34267d3d524b6a481bd0741c84cb11df8afa1aa53ea8810252c9ea26` |

### Reviewable guest excerpts

The checksummed transcript below is available in the repository. It preserves the sampler's JSONL, independent SQL and row reads, and scoped cleanup outputs from the exported trials. Bracketed headers identify the original run and file. Log excerpts are limited to run identities, image pins, version and isolation checks, verifier results and teardown. Guest connection strings and credentials are excluded.

From the repository root, extract the transcript and verify its SHA-256.

```bash
awk '/^```text$/ { copying=1; next } /^```$/ { copying=0 } copying' \
    docs/experiments/EXP-014-publisher-observation.md > /tmp/exp014-guest-excerpts.txt
printf '%s  %s\n' '6d507c5c5acb9d18425f08a8a3c8fd7ad944366dc8820d40743f3f1b8f2a741c' /tmp/exp014-guest-excerpts.txt | sha256sum -c -
```

<details>
<summary>Guest observations for all three attempts</summary>

```text
[20261126t082520z/observations.log]
owner=2.4/Codex ticket=41 run=20261126t082520z revision=8c8a0084d2b7419225c1bea69833974826846f3a overlay=guest-source.qcow2 project=cdc24-20261126t082520z bridge=p24082520 db=source_lab group=g24_20261126t082520z publication=pub24_20261126t082520z slot=slot24_20261126t082520z
    assert before["slot"] == after["slot"]
AssertionError
probe step failed at line 370 (exit 1)
source_exit=0 oom=false
project_cleanup_exit=1

[20261126t082520z/timeline.jsonl]
{"run_id":"20261126t082520z","phase":"2.4","checkpoint":"before","utc":"2026-11-26T08:25:50.278577Z","monotonic_elapsed_ns":173344785,"sample_started_elapsed_ns":16451,"sample":1,"role":"publisher","ownership":{"project":"cdc24-20261126t082520z","container":"93688acd2d12ada137a564fcb68dfd02f865226dd206e9f7fec726509447e246","bridge":"a34cd436c759dff574e13dcfb93b2eb5eb2a3ac9068345ec97553ea2a06a0c6c","database":"source_lab","system_identifier":"7712393504248066085","slot":"slot24_20261126t082520z","publication":"pub24_20261126t082520z"},"error":null,"postgresql":{"server_version_num":160016,"positions":{"insert_lsn":"0/19A90B0","write_lsn":"0/19A90B0","flush_lsn":"0/19A90B0","checkpoint_timeline_id":1,"postmaster_started_at":"2026-11-26T08:25:44.727833+00:00"},"publication":{"pubname":"pub24_20261126t082520z","puballtables":false,"schema_wide":false},"members":[{"schema":"probe","table":"items","filtered":false}],"slot":{"slot_name":"slot24_20261126t082520z","slot_type":"logical","database":"source_lab","plugin":"pgoutput","temporary":false,"active":false,"active_pid":null,"restart_lsn":"0/19A9078","confirmed_flush_lsn":"0/19A90B0","wal_status":"reserved","safe_wal_size":140865360},"feedback":null,"wal_bytes":{"insert_since_previous":null,"insert_to_restart":56,"insert_to_confirmed_flush":0}},"storage":{"pgdata_kib":47344,"wal_kib":16392,"available_kib":3710612},"commit_lsn":null,"end_lsn":null}
{"run_id":"20261126t082520z","phase":"2.4","checkpoint":"after","utc":"2026-11-26T08:25:50.561544Z","monotonic_elapsed_ns":456308882,"sample_started_elapsed_ns":286230941,"sample":2,"role":"publisher","ownership":{"project":"cdc24-20261126t082520z","container":"93688acd2d12ada137a564fcb68dfd02f865226dd206e9f7fec726509447e246","bridge":"a34cd436c759dff574e13dcfb93b2eb5eb2a3ac9068345ec97553ea2a06a0c6c","database":"source_lab","system_identifier":"7712393504248066085","slot":"slot24_20261126t082520z","publication":"pub24_20261126t082520z"},"error":null,"postgresql":{"server_version_num":160016,"positions":{"insert_lsn":"0/19A9168","write_lsn":"0/19A9168","flush_lsn":"0/19A9168","checkpoint_timeline_id":1,"postmaster_started_at":"2026-11-26T08:25:44.727833+00:00"},"publication":{"pubname":"pub24_20261126t082520z","puballtables":false,"schema_wide":false},"members":[{"schema":"probe","table":"items","filtered":false}],"slot":{"slot_name":"slot24_20261126t082520z","slot_type":"logical","database":"source_lab","plugin":"pgoutput","temporary":false,"active":false,"active_pid":null,"restart_lsn":"0/19A9078","confirmed_flush_lsn":"0/19A90B0","wal_status":"reserved","safe_wal_size":140865176},"feedback":null,"wal_bytes":{"insert_since_previous":184,"insert_to_restart":240,"insert_to_confirmed_flush":184}},"storage":{"pgdata_kib":47344,"wal_kib":16392,"available_kib":3710604},"commit_lsn":null,"end_lsn":null}

[20261126t082520z/cleanup.txt]
after|0|0|t|t

[20261126t082603z/observations.log]
owner=2.4/Codex ticket=41 run=20261126t082603z revision=2a2c48535d6d39d2b37bf99998ce61212a1e0942 overlay=guest-source.qcow2 project=cdc24-20261126t082603z bridge=p24082603 db=source_lab group=g24_20261126t082603z publication=pub24_20261126t082603z slot=slot24_20261126t082603z
source index=sha256:cd0e9518bda5f2ea667ff84d22795d089720c883f288e215d97ce57437e8ef37 amd64=sha256:d755a91aff87574a57060f86ecc0d55f83ccb51ceec6ec6f904c1210d018d998 config=sha256:76500a7555b1f245546af93974bb208366013cf537fa3038f0bdd493efe0c612
consumer index=sha256:091236d2acecfec1216817aff6e43dc4c036159cebe44a19c73c95c1fe9be348 amd64=sha256:de0a9036fd11a75eaff23508209c2cea675d081aecea51f60cdca78c0802a5a6 config=sha256:a0452c3a54190ba6eeaf94dd3e434f97fd3862944c73b3f681f85eb8e3b2f56e
PASS: source bridge probes and required IPv4/IPv6 rules verified
PostgreSQL 16.16 (Debian 16.16-1.pgdg12+1) on x86_64-pc-linux-gnu, compiled by gcc (Debian 12.2.0-14+deb12u1) 12.2.0, 64-bit
psql (PostgreSQL) 16.16 (Debian 16.16-1.pgdg12+1)
EXP-014 source: JSON, identity, timeline and WAL span checks passed
source_exit=0 oom=false
project_cleanup_exit=0

[20261126t082603z/empty.jsonl]
{"run_id":"20261126t082603z","phase":"2.4","checkpoint":"empty","utc":"2026-11-26T08:26:33.392470Z","monotonic_elapsed_ns":176737965,"sample_started_elapsed_ns":4438,"sample":1,"role":"publisher","ownership":{"project":"cdc24-20261126t082603z","container":"e7789eb86e2fae1f19f45f8fc6fca78a50865114c9f7690290ab6d88b5d01218","bridge":"23d37e5c922a804ddb53ceea88270e94b279796836a9479b8093bf0bcddc5ef3","database":"source_lab","system_identifier":"7712393691725733925","slot":null,"publication":null},"error":null,"postgresql":{"server_version_num":160016,"positions":{"insert_lsn":"0/19A8480","write_lsn":"0/19A8480","flush_lsn":"0/19A8480","checkpoint_timeline_id":1,"postmaster_started_at":"2026-11-26T08:26:28.354184+00:00"},"publication":null,"members":[],"slot":null,"feedback":null,"wal_bytes":{"insert_since_previous":null,"insert_to_restart":null,"insert_to_confirmed_flush":null}},"storage":{"pgdata_kib":47280,"wal_kib":16392,"available_kib":3710688},"commit_lsn":null,"end_lsn":null}

[20261126t082603z/timeline.jsonl]
{"run_id":"20261126t082603z","phase":"2.4","checkpoint":"before","utc":"2026-11-26T08:26:33.908244Z","monotonic_elapsed_ns":169888005,"sample_started_elapsed_ns":17042,"sample":1,"role":"publisher","ownership":{"project":"cdc24-20261126t082603z","container":"e7789eb86e2fae1f19f45f8fc6fca78a50865114c9f7690290ab6d88b5d01218","bridge":"23d37e5c922a804ddb53ceea88270e94b279796836a9479b8093bf0bcddc5ef3","database":"source_lab","system_identifier":"7712393691725733925","slot":"slot24_20261126t082603z","publication":"pub24_20261126t082603z"},"error":null,"postgresql":{"server_version_num":160016,"positions":{"insert_lsn":"0/19A90B0","write_lsn":"0/19A90B0","flush_lsn":"0/19A90B0","checkpoint_timeline_id":1,"postmaster_started_at":"2026-11-26T08:26:28.354184+00:00"},"publication":{"pubname":"pub24_20261126t082603z","puballtables":false,"schema_wide":false},"members":[{"schema":"probe","table":"items","filtered":false}],"slot":{"slot_name":"slot24_20261126t082603z","slot_type":"logical","database":"source_lab","plugin":"pgoutput","temporary":false,"active":false,"active_pid":null,"restart_lsn":"0/19A9078","confirmed_flush_lsn":"0/19A90B0","wal_status":"reserved","safe_wal_size":140865360},"feedback":null,"wal_bytes":{"insert_since_previous":null,"insert_to_restart":56,"insert_to_confirmed_flush":0}},"storage":{"pgdata_kib":47344,"wal_kib":16392,"available_kib":3710612},"commit_lsn":null,"end_lsn":null}
{"run_id":"20261126t082603z","phase":"2.4","checkpoint":"after","utc":"2026-11-26T08:26:34.196581Z","monotonic_elapsed_ns":458222273,"sample_started_elapsed_ns":279236621,"sample":2,"role":"publisher","ownership":{"project":"cdc24-20261126t082603z","container":"e7789eb86e2fae1f19f45f8fc6fca78a50865114c9f7690290ab6d88b5d01218","bridge":"23d37e5c922a804ddb53ceea88270e94b279796836a9479b8093bf0bcddc5ef3","database":"source_lab","system_identifier":"7712393691725733925","slot":"slot24_20261126t082603z","publication":"pub24_20261126t082603z"},"error":null,"postgresql":{"server_version_num":160016,"positions":{"insert_lsn":"0/19A9168","write_lsn":"0/19A9168","flush_lsn":"0/19A9168","checkpoint_timeline_id":1,"postmaster_started_at":"2026-11-26T08:26:28.354184+00:00"},"publication":{"pubname":"pub24_20261126t082603z","puballtables":false,"schema_wide":false},"members":[{"schema":"probe","table":"items","filtered":false}],"slot":{"slot_name":"slot24_20261126t082603z","slot_type":"logical","database":"source_lab","plugin":"pgoutput","temporary":false,"active":false,"active_pid":null,"restart_lsn":"0/19A9078","confirmed_flush_lsn":"0/19A90B0","wal_status":"reserved","safe_wal_size":140865176},"feedback":null,"wal_bytes":{"insert_since_previous":184,"insert_to_restart":240,"insert_to_confirmed_flush":184}},"storage":{"pgdata_kib":47344,"wal_kib":16392,"available_kib":3710604},"commit_lsn":null,"end_lsn":null}

[20261126t082603z/wrong-slot.jsonl]
{"run_id":"20261126t082603z","phase":"2.4","checkpoint":"wrong-slot","utc":"2026-11-26T08:26:34.566693Z","monotonic_elapsed_ns":115239070,"sample_started_elapsed_ns":4789,"sample":1,"role":"publisher","ownership":{"project":"cdc24-20261126t082603z","container":"e7789eb86e2fae1f19f45f8fc6fca78a50865114c9f7690290ab6d88b5d01218","bridge":"23d37e5c922a804ddb53ceea88270e94b279796836a9479b8093bf0bcddc5ef3","database":"source_lab","system_identifier":"7712393691725733925","slot":"unexpected_20261126t082603z","publication":"pub24_20261126t082603z"},"error":"slot_identity","postgresql":null,"storage":null,"commit_lsn":null,"end_lsn":null}

[20261126t082603z/extra-slot.jsonl]
{"run_id":"20261126t082603z","phase":"2.4","checkpoint":"extra-slot","utc":"2026-11-26T08:26:34.835437Z","monotonic_elapsed_ns":105430023,"sample_started_elapsed_ns":4910,"sample":1,"role":"publisher","ownership":{"project":"cdc24-20261126t082603z","container":"e7789eb86e2fae1f19f45f8fc6fca78a50865114c9f7690290ab6d88b5d01218","bridge":"23d37e5c922a804ddb53ceea88270e94b279796836a9479b8093bf0bcddc5ef3","database":"source_lab","system_identifier":"7712393691725733925","slot":"slot24_20261126t082603z","publication":"pub24_20261126t082603z"},"error":"slot_identity","postgresql":null,"storage":null,"commit_lsn":null,"end_lsn":null}

[20261126t082603z/deadline.jsonl]
{"run_id":"20261126t082603z","phase":"2.4","checkpoint":"deadline","utc":"2026-11-26T08:26:35.063898Z","monotonic_elapsed_ns":25347,"sample_started_elapsed_ns":4057,"sample":1,"role":"publisher","ownership":{"project":"cdc24-20261126t082603z","container":"e7789eb86e2fae1f19f45f8fc6fca78a50865114c9f7690290ab6d88b5d01218","bridge":"23d37e5c922a804ddb53ceea88270e94b279796836a9479b8093bf0bcddc5ef3","database":"source_lab","system_identifier":"7712393691725733925","slot":"slot24_20261126t082603z","publication":"pub24_20261126t082603z"},"error":"deadline_exhausted","postgresql":null,"storage":null,"commit_lsn":null,"end_lsn":null}

[20261126t082603z/before.rows]
1|seed

[20261126t082603z/after.rows]
1|seed
2|inserted

[20261126t082603z/before.state]
wal|0/19A90B0|0/19A90B0
slot|slot24_20261126t082603z|pgoutput|source_lab|f|f||0/19A9078|0/19A90B0|reserved
member|pub24_20261126t082603z|probe|items

[20261126t082603z/after.state]
wal|0/19A9168|0/19A9168
slot|slot24_20261126t082603z|pgoutput|source_lab|f|f||0/19A9078|0/19A90B0|reserved
member|pub24_20261126t082603z|probe|items

[20261126t082603z/cleanup.txt]
after|0|0|t|t

[20261126t082647z/observations.log]
owner=2.4/Codex ticket=41 run=20261126t082647z revision=2a2c48535d6d39d2b37bf99998ce61212a1e0942 overlay=guest-active.qcow2 project=cdc24-20261126t082647z bridge=p24082647 db=source_lab group=g24_20261126t082647z publication=pub24_20261126t082647z slot=slot24_20261126t082647z
source index=sha256:cd0e9518bda5f2ea667ff84d22795d089720c883f288e215d97ce57437e8ef37 amd64=sha256:d755a91aff87574a57060f86ecc0d55f83ccb51ceec6ec6f904c1210d018d998 config=sha256:76500a7555b1f245546af93974bb208366013cf537fa3038f0bdd493efe0c612
consumer index=sha256:091236d2acecfec1216817aff6e43dc4c036159cebe44a19c73c95c1fe9be348 amd64=sha256:de0a9036fd11a75eaff23508209c2cea675d081aecea51f60cdca78c0802a5a6 config=sha256:a0452c3a54190ba6eeaf94dd3e434f97fd3862944c73b3f681f85eb8e3b2f56e
PASS: source bridge probes and required IPv4/IPv6 rules verified
PostgreSQL 16.16 (Debian 16.16-1.pgdg12+1) on x86_64-pc-linux-gnu, compiled by gcc (Debian 12.2.0-14+deb12u1) 12.2.0, 64-bit
psql (PostgreSQL) 16.16 (Debian 16.16-1.pgdg12+1)
PostgreSQL 18.4 (Debian 18.4-1.pgdg12+1) on x86_64-pc-linux-gnu, compiled by gcc (Debian 12.2.0-14+deb12u1) 12.2.0, 64-bit
EXP-014 active: JSON, identity, timeline and WAL span checks passed
consumer_exit=0 oom=false
source_exit=0 oom=false
project_cleanup_exit=0

[20261126t082647z/empty.jsonl]
{"run_id":"20261126t082647z","phase":"2.4","checkpoint":"empty","utc":"2026-11-26T08:27:16.674463Z","monotonic_elapsed_ns":184953200,"sample_started_elapsed_ns":4719,"sample":1,"role":"publisher","ownership":{"project":"cdc24-20261126t082647z","container":"49028d24b80f97d7ae06007fe34035c4528939170f0c2aacffa3bafdc2223ba1","bridge":"49fea59a6ab47cc46849e97e3d25dc6e98e77498b881f4799b3954e62c9fa2e9","database":"source_lab","system_identifier":"7712393877342404645","slot":null,"publication":null},"error":null,"postgresql":{"server_version_num":160016,"positions":{"insert_lsn":"0/19A8480","write_lsn":"0/19A8480","flush_lsn":"0/19A8480","checkpoint_timeline_id":1,"postmaster_started_at":"2026-11-26T08:27:11.587863+00:00"},"publication":null,"members":[],"slot":null,"feedback":null,"wal_bytes":{"insert_since_previous":null,"insert_to_restart":null,"insert_to_confirmed_flush":null}},"storage":{"pgdata_kib":47280,"wal_kib":16392,"available_kib":3710684},"commit_lsn":null,"end_lsn":null}

[20261126t082647z/timeline.jsonl]
{"run_id":"20261126t082647z","phase":"2.4","checkpoint":"initial","utc":"2026-11-26T08:27:24.716747Z","monotonic_elapsed_ns":173032691,"sample_started_elapsed_ns":17062,"sample":1,"role":"publisher","ownership":{"project":"cdc24-20261126t082647z","container":"49028d24b80f97d7ae06007fe34035c4528939170f0c2aacffa3bafdc2223ba1","bridge":"49fea59a6ab47cc46849e97e3d25dc6e98e77498b881f4799b3954e62c9fa2e9","database":"source_lab","system_identifier":"7712393877342404645","slot":"slot24_20261126t082647z","publication":"pub24_20261126t082647z"},"error":null,"postgresql":{"server_version_num":160016,"positions":{"insert_lsn":"0/19A9318","write_lsn":"0/19A92D8","flush_lsn":"0/19A92D8","checkpoint_timeline_id":1,"postmaster_started_at":"2026-11-26T08:27:11.587863+00:00"},"publication":{"pubname":"pub24_20261126t082647z","puballtables":false,"schema_wide":false},"members":[{"schema":"probe","table":"items","filtered":false}],"slot":{"slot_name":"slot24_20261126t082647z","slot_type":"logical","database":"source_lab","plugin":"pgoutput","temporary":false,"active":true,"active_pid":267,"restart_lsn":"0/19A92A0","confirmed_flush_lsn":"0/19A92D8","wal_status":"reserved","safe_wal_size":140864808},"feedback":{"pid":267,"state":"streaming","sent_lsn":"0/19A92D8","write_lsn":"0/19A92D8","flush_lsn":"0/19A92D8","replay_lsn":"0/19A92D8","write_lag":null,"flush_lag":null,"replay_lag":null,"reply_time":"2026-11-26T08:27:24.562826+00:00"},"wal_bytes":{"insert_since_previous":null,"insert_to_restart":120,"insert_to_confirmed_flush":64}},"storage":{"pgdata_kib":47348,"wal_kib":16392,"available_kib":3669056},"commit_lsn":null,"end_lsn":null}
{"run_id":"20261126t082647z","phase":"2.4","checkpoint":"insert","utc":"2026-11-26T08:27:31.475360Z","monotonic_elapsed_ns":6931716957,"sample_started_elapsed_ns":6763489790,"sample":2,"role":"publisher","ownership":{"project":"cdc24-20261126t082647z","container":"49028d24b80f97d7ae06007fe34035c4528939170f0c2aacffa3bafdc2223ba1","bridge":"49fea59a6ab47cc46849e97e3d25dc6e98e77498b881f4799b3954e62c9fa2e9","database":"source_lab","system_identifier":"7712393877342404645","slot":"slot24_20261126t082647z","publication":"pub24_20261126t082647z"},"error":null,"postgresql":{"server_version_num":160016,"positions":{"insert_lsn":"0/19A9408","write_lsn":"0/19A9408","flush_lsn":"0/19A9408","checkpoint_timeline_id":1,"postmaster_started_at":"2026-11-26T08:27:11.587863+00:00"},"publication":{"pubname":"pub24_20261126t082647z","puballtables":false,"schema_wide":false},"members":[{"schema":"probe","table":"items","filtered":false}],"slot":{"slot_name":"slot24_20261126t082647z","slot_type":"logical","database":"source_lab","plugin":"pgoutput","temporary":false,"active":true,"active_pid":267,"restart_lsn":"0/19A92A0","confirmed_flush_lsn":"0/19A9318","wal_status":"reserved","safe_wal_size":140864504},"feedback":{"pid":267,"state":"streaming","sent_lsn":"0/19A9408","write_lsn":"0/19A9318","flush_lsn":"0/19A9318","replay_lsn":"0/19A9318","write_lag":"00:00:06.512389","flush_lag":"00:00:06.512389","replay_lag":"00:00:06.512389","reply_time":"2026-11-26T08:27:31.343468+00:00"},"wal_bytes":{"insert_since_previous":240,"insert_to_restart":360,"insert_to_confirmed_flush":240}},"storage":{"pgdata_kib":47352,"wal_kib":16392,"available_kib":3668992},"commit_lsn":null,"end_lsn":null}
{"run_id":"20261126t082647z","phase":"2.4","checkpoint":"update","utc":"2026-11-26T08:27:36.437271Z","monotonic_elapsed_ns":11893552762,"sample_started_elapsed_ns":11720226342,"sample":3,"role":"publisher","ownership":{"project":"cdc24-20261126t082647z","container":"49028d24b80f97d7ae06007fe34035c4528939170f0c2aacffa3bafdc2223ba1","bridge":"49fea59a6ab47cc46849e97e3d25dc6e98e77498b881f4799b3954e62c9fa2e9","database":"source_lab","system_identifier":"7712393877342404645","slot":"slot24_20261126t082647z","publication":"pub24_20261126t082647z"},"error":null,"postgresql":{"server_version_num":160016,"positions":{"insert_lsn":"0/19A9498","write_lsn":"0/19A9498","flush_lsn":"0/19A9498","checkpoint_timeline_id":1,"postmaster_started_at":"2026-11-26T08:27:11.587863+00:00"},"publication":{"pubname":"pub24_20261126t082647z","puballtables":false,"schema_wide":false},"members":[{"schema":"probe","table":"items","filtered":false}],"slot":{"slot_name":"slot24_20261126t082647z","slot_type":"logical","database":"source_lab","plugin":"pgoutput","temporary":false,"active":true,"active_pid":267,"restart_lsn":"0/19A92A0","confirmed_flush_lsn":"0/19A9318","wal_status":"reserved","safe_wal_size":140864360},"feedback":{"pid":267,"state":"streaming","sent_lsn":"0/19A9498","write_lsn":"0/19A9318","flush_lsn":"0/19A9318","replay_lsn":"0/19A9318","write_lag":"00:00:11.443039","flush_lag":"00:00:11.443039","replay_lag":"00:00:11.443039","reply_time":"2026-11-26T08:27:36.273535+00:00"},"wal_bytes":{"insert_since_previous":144,"insert_to_restart":504,"insert_to_confirmed_flush":384}},"storage":{"pgdata_kib":47352,"wal_kib":16392,"available_kib":3668952},"commit_lsn":null,"end_lsn":null}
{"run_id":"20261126t082647z","phase":"2.4","checkpoint":"delete","utc":"2026-11-26T08:27:41.330958Z","monotonic_elapsed_ns":16787239216,"sample_started_elapsed_ns":16615157054,"sample":4,"role":"publisher","ownership":{"project":"cdc24-20261126t082647z","container":"49028d24b80f97d7ae06007fe34035c4528939170f0c2aacffa3bafdc2223ba1","bridge":"49fea59a6ab47cc46849e97e3d25dc6e98e77498b881f4799b3954e62c9fa2e9","database":"source_lab","system_identifier":"7712393877342404645","slot":"slot24_20261126t082647z","publication":"pub24_20261126t082647z"},"error":null,"postgresql":{"server_version_num":160016,"positions":{"insert_lsn":"0/19A9518","write_lsn":"0/19A9518","flush_lsn":"0/19A9518","checkpoint_timeline_id":1,"postmaster_started_at":"2026-11-26T08:27:11.587863+00:00"},"publication":{"pubname":"pub24_20261126t082647z","puballtables":false,"schema_wide":false},"members":[{"schema":"probe","table":"items","filtered":false}],"slot":{"slot_name":"slot24_20261126t082647z","slot_type":"logical","database":"source_lab","plugin":"pgoutput","temporary":false,"active":true,"active_pid":267,"restart_lsn":"0/19A93D0","confirmed_flush_lsn":"0/19A9408","wal_status":"reserved","safe_wal_size":140864232},"feedback":{"pid":267,"state":"streaming","sent_lsn":"0/19A9518","write_lsn":"0/19A9408","flush_lsn":"0/19A9408","replay_lsn":"0/19A9408","write_lag":"00:00:14.514075","flush_lag":"00:00:14.514075","replay_lag":"00:00:14.514075","reply_time":"2026-11-26T08:27:41.238247+00:00"},"wal_bytes":{"insert_since_previous":128,"insert_to_restart":328,"insert_to_confirmed_flush":272}},"storage":{"pgdata_kib":47352,"wal_kib":16392,"available_kib":3668908},"commit_lsn":null,"end_lsn":null}

[20261126t082647z/initial.source.rows]
1|seed

[20261126t082647z/initial.source.state]
slot|slot24_20261126t082647z|pgoutput|source_lab|f|t|267|0/19A8480|0/19A84B8|reserved
member|pub24_20261126t082647z|probe|items

[20261126t082647z/initial.target.rows]
1|seed

[20261126t082647z/insert.source.rows]
1|seed
2|inserted

[20261126t082647z/insert.source.state]
slot|slot24_20261126t082647z|pgoutput|source_lab|f|t|267|0/19A92A0|0/19A9318|reserved
member|pub24_20261126t082647z|probe|items

[20261126t082647z/insert.target.rows]
1|seed
2|inserted

[20261126t082647z/update.source.rows]
1|updated
2|inserted

[20261126t082647z/update.source.state]
slot|slot24_20261126t082647z|pgoutput|source_lab|f|t|267|0/19A92A0|0/19A9318|reserved
member|pub24_20261126t082647z|probe|items

[20261126t082647z/update.target.rows]
1|updated
2|inserted

[20261126t082647z/delete.source.rows]
1|updated

[20261126t082647z/delete.source.state]
slot|slot24_20261126t082647z|pgoutput|source_lab|f|t|267|0/19A93D0|0/19A9408|reserved
member|pub24_20261126t082647z|probe|items

[20261126t082647z/delete.target.rows]
1|updated

[20261126t082647z/final-keys.txt]
deleted_absent|t
duplicate_keys|0

[20261126t082647z/cleaned.jsonl]
{"run_id":"20261126t082647z","phase":"2.4","checkpoint":"cleaned","utc":"2026-11-26T08:27:43.110325Z","monotonic_elapsed_ns":171176336,"sample_started_elapsed_ns":4238,"sample":1,"role":"publisher","ownership":{"project":"cdc24-20261126t082647z","container":"49028d24b80f97d7ae06007fe34035c4528939170f0c2aacffa3bafdc2223ba1","bridge":"49fea59a6ab47cc46849e97e3d25dc6e98e77498b881f4799b3954e62c9fa2e9","database":"source_lab","system_identifier":"7712393877342404645","slot":null,"publication":null},"error":null,"postgresql":{"server_version_num":160016,"positions":{"insert_lsn":"0/19A9938","write_lsn":"0/19A9938","flush_lsn":"0/19A9938","checkpoint_timeline_id":1,"postmaster_started_at":"2026-11-26T08:27:11.587863+00:00"},"publication":null,"members":[],"slot":null,"feedback":null,"wal_bytes":{"insert_since_previous":null,"insert_to_restart":null,"insert_to_confirmed_flush":null}},"storage":{"pgdata_kib":47348,"wal_kib":16392,"available_kib":3668900},"commit_lsn":null,"end_lsn":null}

[20261126t082647z/cleanup.txt]
after|0|0|t|t
```

</details>

## Interpretation

Each JSONL row carries `run_id`, `phase`, `checkpoint`, UTC finishing time, start and finish elapsed nanoseconds from the observer's monotonic clock, sample ordinal, publisher role, configured ownership and an error code or null. Only rows from the same observer instance share an elapsed-time origin. The SQL inventory validates the configured publication and slot independently. PG16's catalogs do not expose a persistent slot-to-publication binding. `postgresql.feedback` is attributed through the sampled active slot PID. A missing sender match remains null. The query omits connection details, unrelated sessions, row filter text and credentials.

**Verified documentation** (PG16, consulted 2026-11-26). [Slot view](https://www.postgresql.org/docs/16/view-pg-replication-slots.html) describes `restart_lsn` as the oldest WAL the slot may need and `confirmed_flush_lsn` as the consumer-confirmed receive position. `wal_status` can shift from reserved or extended to unreserved, and then lost when required WAL can no longer be retained. The Phase 1 profile's `max_slot_wal_keep_size=128MB` applies at checkpoint time. `safe_wal_size` can be null for a lost slot or an unlimited retention setting. Check both status and the actual allocation. [Replication settings](https://www.postgresql.org/docs/16/runtime-config-replication.html) · [PG16.16 release](https://www.postgresql.org/docs/16/release-16-16.html)

The [administration functions](https://www.postgresql.org/docs/16/functions-admin.html) provide the source insert, write and flush LSNs and signed `pg_wal_lsn_diff` byte spans. The first between-sample span is null. A changed checkpoint timeline or postmaster start also yields null. Spans describe cluster-wide WAL ranges, including unrelated records. Disk counters report allocated KiB and filesystem availability. These can diverge from spans due to WAL segment rounding, preallocation and recycling.

The [WAL sender statistics](https://www.postgresql.org/docs/16/monitoring-stats.html#MONITORING-PG-STAT-REPLICATION-VIEW) describe reported feedback and lag for recent WAL, and allow null lag during idle periods or when tracking data is unavailable. Write, flush and replay fields describe feedback reported over the protocol. Durable DuckLake application requires separate persistence evidence. Query visibility requires an independent exact target read. Commit-to-visibility latency requires attributable timed checkpoints and is bounded by the observation cadence. This SQL observer leaves `commit_lsn` and `end_lsn` null.

## Limitations / confounders

Source SQL and disk captures have distinct instants within one observation window. Slots and WAL senders can change while sampling. An active slot may have no matching sender row during a transition. A source crash can rewind slot positions. The sampler rejects extra slots, so take identity-checked samples at steady-state hold points; temporary-slot lifecycle evidence belongs to ticket 2.2. An empty publication and slot baseline represents catalog absence. No sender inventory from outside the expected slot is included. The outer deadline covers Docker inspection and both captures. SQL and disk commands also have in-container limits. A disk threshold emits the measured values and an error for the operator to act on.

## Follow-up action

R04, R05 and R16 remain **OPEN** at their full acceptance conditions. Preserve independent publisher observations for the checkpoint, interruption and walkthrough experiments. Ticket 2.9 owns reconciliation of the shared research register. [Phase 2 ownership and runtime plan](../../backlog/phase-2.md#parallel-development-and-runtime-conventions)
