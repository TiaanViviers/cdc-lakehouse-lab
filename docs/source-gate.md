# Verify the Phase 1 source gate

[Ticket 1.8 (#26)](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/26) verifies the disposable PostgreSQL simulator and fixture v1, seed 42. The suite runs the accepted S00–S06 order, checks each state from a separate read-only `psql` connection, and invokes the existing schema, sequential, overlap and replay fault checks.

## Set up a fresh disposable source

1. Stage the pinned [PostgreSQL image](source-profile.md#stage-and-start), [isolation probe](source-runbook.md#reproduce-the-negative-experiment) and [runner built from this checkout](source-runner.md#stage-and-provision) on read-only media. Include the repository tree. The staging command in the runner guide uses the default tag. If you stage a different tag, export `SOURCE_RUNNER_IMAGE` with that exact tag in the guest.
2. Use the dedicated Linux VM with external uplinks disconnected. Confirm it has no routable NIC or default route. Use Python 3.12.3, GNU Make, Bash, Docker Engine with the local Unix socket and cgroup v2, and Compose v2. Use a fresh project and empty volume for each run, as in the [source profile](source-profile.md#stage-and-start). Save the resolved Compose model and check the disk thresholds.
3. Before installing the [bridge firewall rules](source-runbook.md#dedicated-vm-procedure-for-ticket-12), run the startup gate and confirm the controlled host gateway is reachable and Compose has no source container. Install both firewall families' rules for that exact bridge ID and run the gate again. Save both probe transcripts. Require a healthy source, unpublished port, and the expected local named volume. Keep the controls in effect until teardown.
4. [Bootstrap the schema and provision both SCRAM roles](source-schema.md#bootstrap-and-role-setup). Keep the enrolled UUID and the three passwords in the documented guest-local files. Leave the four business tables and receipt table empty. Pause any other clients. The suite rechecks the running container, project volume, bridge, firewall rules, enrolled identity, settings and empty fixture before its first write.

## Run twice and review the evidence

From the repository root inside the verified VM, keep the same exported `COMPOSE_PROJECT_NAME` and `SOURCE_INPUT_ID` that passed startup. Give each run a UTC run ID and new evidence directory.

```bash
mkdir -p artifacts
run_id="$(date -u +%Y%m%dT%H%M%SZ)-p01-01"
RUN_ID="$run_id" EVIDENCE_DIR="artifacts/$run_id" make test-integration
```

The suite requires an empty live fixture before and after the schema checks, compares each scenario to the independent expected JSON, checks S04/S05 receipt equality and complete S05/S06 equality including the receipt's tuple version, then checks exact S00 after reset. It subsequently clears the fixture through the UUID-guarded cleanup to run the sequential fault suite from empty. It follows with the S05 and S06 fault suites and ends with a second exact S00 restore. Disk and OOM stop thresholds are checked before the fixture, at each normal checkpoint, and between fault suites.

Read `comparisons.jsonl` alongside `S00.json` through `S06.json`. A passing run has an empty `differences` array on every comparison, one receipt throughout S04–S06, matching hashes for S05 and S06, and matching hashes for initial S00 and both resets. The ordered snapshot JSON preserves all rows and receipt `xmin` separately. Timestamps in the raw SQL capture use PostgreSQL's UTC rendering. The comparator converts them to the fixture's UTC format and preserves any nonzero fractional seconds. The fault directories use their own attempt numbers within the run. Use `settings.txt`, `wal.txt`, `storage.txt`, `source-cgroup.txt`, `source-stats.txt`, runner resource events and the filtered `source.log` for operational evidence. The WAL positions are labeled publisher observations sampled around workload boundaries. They include ordinary server activity.

Capture and review any failure evidence before teardown. Follow [stop and disposal](#guarded-reset-and-stop). Repeat the entire setup with a new disposable project, fresh volume and bridge, and another run ID ending in `-p01-02`. Compare canonical hashes across runs. Receipt `xmin` is meaningful for before/after equality within one run. All service-free checks, including `make check` and `make test-unit`, run separately.

## Read-only S04 inspection in psql

Use a separate verified disposable source to walk through the fixture manually. Start at a fresh empty fixture, or run the guarded reset below and start at S01.

```bash
run_id="$(date -u +%Y%m%dT%H%M%SZ)-p01-01"
fixture_runner() {
    labdocker compose -f compose.source.yaml -f compose.runner.yaml --profile source \
        run --rm --no-deps -T fixture-runner --run-id "$run_id" "$@"
}

# Start from empty. Omit S00 immediately after an exact reset to S00.
for scenario in S00 S01 S02 S03 S04; do
    fixture_runner run "$scenario" || break
done

source_compose exec source-db env PGCONNECT_TIMEOUT=3 PGREQUIREAUTH=scram-sha-256 \
    psql -XW -v ON_ERROR_STOP=1 -h 127.0.0.1 -U source_fixture_reader -d source_lab
```

Enter the reader role's local password at the hidden prompt. In `psql` run the following.

```sql
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL TIME ZONE 'UTC';
SET LOCAL statement_timeout = '5s';
SHOW transaction_read_only;
SELECT * FROM fixture.orders WHERE order_id = 30;
SELECT * FROM fixture.order_items WHERE item_id IN (102, 301) ORDER BY item_id;
SELECT * FROM fixture.payments WHERE payment_id = 302;
SELECT fixture_version, seed, scenario_id, payload_sha256, xmin::text AS tuple_xid
FROM fixture.scenario_receipts ORDER BY fixture_version, seed, scenario_id;
COMMIT;
```

Expect `on`, order 30 for customer 1 with reference `O30` and status `paid`, item 301 with SKU `C` and 2 × 200 cents for order 30, payment 302 for 400 cents on order 30, and one S04 receipt for v1/42 with the [published payload digest](source-schema.md#receipt-contract-for-tickets-15-and-17). Both timestamps on each of the three S04 business rows represent `2026-01-01T00:04:00Z`. The item query returns item 301 only. Use `\q` to exit. The suite's [snapshot query](../tests/integration/source-gate/snapshot.sql) also reads all four tables and derives both exact reporting aggregates in one snapshot.

## Guarded reset and stop

Run a reset only on the enrolled disposable source with its original project, volume and identity file while other fixture clients are paused. Reset and S00 seeding commit together.

```bash
fixture_runner reset --confirm
fixture_runner inspect S00
source_compose stop
labdocker inspect -f '{{.State.ExitCode}} {{.State.OOMKilled}}' "$(source_compose ps --all -q source-db)"
source_compose down
```

Expect exit 0 and no OOM. Retain the volume and secret files if you need later inspection. For a complete disposable teardown, remove only the exact project volume after checking its name and Compose labels. Then [undo the per-bridge rules and remove the verified bridge by ID](source-runbook.md#dedicated-vm-procedure-for-ticket-12).
