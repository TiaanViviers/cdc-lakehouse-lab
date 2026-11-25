# S05 ordered overlap

Use [the source profile](source-profile.md) and [runner setup](source-runner.md#stage-and-provision) in a disconnected lab VM. For a parallel exercise, use a separate VM overlay, Compose project, verified bridge, project volume and artifact directory. Keep the guarded reset identity and the two role password files local to that VM. The S05 commands use the image built from this revision of the runner.

## Run and inspect

With the `fixture_runner` helper from the [runner guide](source-runner.md#run-and-inspect), run S05 from exact S04. The runner holds the existing advisory lock across the schedule. It uses two writer connections and a third, read-only connection. Each observation starts a fresh read-only `REPEATABLE READ` transaction.

```bash
fixture_runner inspect S04
fixture_runner run S05
fixture_runner inspect S05
```

Writer A updates item 101 and writer B inserts payment 303. Both stage their writes before the coordinator releases A's four-second commit barrier. With B blocked at its own four-second barrier, the observer checks exact S04 before A commits and exact `S05-A` after A's commit acknowledgement. Only then can the coordinator release B's barrier. The final snapshot checks exact S05. Each gate uses a timed rendezvous. The trace carries two backend PIDs, two assigned transaction IDs and independent PostgreSQL transaction statuses at the three boundaries. The runner also retains the SQL, connection and process deadlines from the sequential scenarios.

`inspect S05-A` validates the intermediate state. Its expectations use the independent S05 oracle for customers, orders, items and report, and the independent S04 oracle for payments. All three checkpoints require the same single S04 receipt.

The shared CLI adds `run S05`, its two fault options and inspection of `S05-A` and `S05`. The checkpoint checker accepts the intermediate label, and the existing writer identity helper lives with the transaction helpers so both schedules use the same query. The S00–S04 entry points, advisory lock key, schema, image pins and receipt identity retain their existing contracts.

## Faults and recovery

Start each fault from exact S04 on an enrolled disposable source.

| Command | Expected exit and database state |
| --- | --- |
| `fixture_runner run S05 --s05-fault barrier-timeout` | Exit 1 after the A barrier times out. Both transactions abort and both writer connections close. `inspect S04` passes. |
| `fixture_runner run S05 --s05-fault after-a-commit` | Exit 1 after exact A-only visibility is observed. The failure trace reports `partial_commit`. B aborts, both writer connections close and `inspect S05-A` passes. |

The failure trace records the observed checkpoint and outcome. When the runner cannot verify the outcome, take a fresh independent inspection before any retry. For the A-only state, the usual S05 predecessor check rejects another S05 attempt. The following commands rebuild S04 on the same verified disposable target using its reset identity.

```bash
fixture_runner inspect S05-A
fixture_runner reset --confirm
for step in S01 S02 S03 S04; do
    fixture_runner run "$step" || break
done
fixture_runner inspect S04 && fixture_runner run S05 && fixture_runner inspect S05
```

## Reproduce ticket 1.6

After bootstrapping the separate source and provisioning both fixture roles, use the S05 harness from the repository root. It performs four guarded reset/replays to S04, runs the normal schedule twice around the two faults, checks both writer backends disappear from `pg_stat_activity`, compares fresh inspection rows and records canonical hashes. The timeout case must complete within 15 seconds including Compose startup. The last run leaves exact S05.

```bash
mkdir -p artifacts
run_id="$(date -u +%Y%m%dT%H%M%SZ)-p01-01"
bash tests/integration/source-overlap/run.sh "$run_id" "artifacts/$run_id-s05"
```

See the [experiment results](experiments/EXP-016-source-overlap.md) and the [source stop procedure](source-profile.md#verify-a-clean-restart-and-stop).
