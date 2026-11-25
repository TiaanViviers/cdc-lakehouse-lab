# Phase 1 source schema and fixture interfaces

[Ticket 1.3](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/21) owns the SQL bootstrap and cleanup interface. The [v1 workload](synthetic-workload.md) defines the data and fixed timestamps. Tickets 1.5 and 1.7 own scenario execution and receipt reconciliation. Runtime acceptance is tracked in [EXP-005](experiments/EXP-005-source-schema.md).

## Bootstrap and role setup

Use the completed ticket 1.2 source profile in the dedicated disconnected VM. Follow its startup, isolation, health and storage checks on the actual bridge and confirm the Compose project and its named volume. The migration enrolls `source_lab` with a UUID supplied by the operator after those checks. Keep one UUID with the project and volume for their lifetime. On first use in the VM, run the following from the repository root with the variables and `source_compose` helper defined by the 1.2 procedure.

```bash
id_file="secrets/${COMPOSE_PROJECT_NAME}-fixture-id"
(umask 077; set -C; cat /proc/sys/kernel/random/uuid > "$id_file")
disposable_id=$(cat "$id_file")

admin_psql=(docker --host unix:///var/run/docker.sock compose -f "$COMPOSE_FILE" --profile source
    exec -T source-db sh -ec '
        PGPASSWORD=$(cat "$POSTGRES_PASSWORD_FILE")
        export PGPASSWORD PGCONNECT_TIMEOUT=3 PGREQUIREAUTH=scram-sha-256
        exec psql -w -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"
    ' sh)
"${admin_psql[@]}" -X -v "disposable_id=$disposable_id" -f - < sql/source/001_fixture_v1.sql
```

On subsequent runs, read the saved UUID from the existing file. `001_fixture_v1.sql` installs schema version 1 and records the UUID, database OID and PostgreSQL cluster system identifier in the owner-controlled `fixture.installation`. Repeat bootstrap with the original identity reports `Fixture schema 1 already installed` and skips DDL and grants. An identity mismatch aborts. Changes to the installed schema belong in a subsequent versioned migration. The comparison relies on the exact runtime database, cluster and UUID; a physical volume copy inherits all three, so keep copied volumes outside this reset workflow.

| Role | Scope on `source_lab` |
| --- | --- |
| `source_admin` | Source administration and migration |
| `source_fixture_owner` | Owns fixture objects and cleanup, no login |
| `source_fixture_writer` | Select and insert on all four business tables and receipts, update `quantity` and `updated_at` and delete rows on `order_items`, execute cleanup |
| `source_fixture_reader` | Select on all four business tables and receipts |

The business tables are `fixture.customers`, `fixture.orders`, `fixture.order_items` and `fixture.payments`. Use explicit integer IDs, integer cents and `timestamptz` values from the scenario contract. The writer grants preserve primary keys and `created_at`. Inspect from a separate reader session using `REPEATABLE READ READ ONLY` and UTC. Business row parity covers the four business tables. Verify receipts separately.

Bootstrap creates the writer and reader login roles with no initial passwords. Provision distinct local passwords with `\password source_fixture_writer` and `\password source_fixture_reader` from an interactive SCRAM-authenticated admin `psql` session inside `source-db`. Keep the credentials in the VM and out of SQL files and evidence. The 1.5 runner connects as `source_fixture_writer`, and checkpoint inspection connects as `source_fixture_reader`.

## Cleanup for ticket 1.5

Pass the typed Boolean `true` only for explicit reset intent, and pass the expected UUID from the selected disposable project's local file. Missing or false intent raises `22023`. Missing or mismatched identity raises `55000`. The client supplies the expected identity from the operator's inventory before connecting. An installer, reader or runner should never infer it from the connected database when deciding to reset.

In the writer's transaction, execute `SELECT fixture.cleanup($1::boolean, $2::uuid)` with bound parameters. The function checks the target before deleting. It locks the five fixture tables until the transaction ends, then deletes order items and payments before orders and customers, and clears the receipts. The caller owns the transaction. Pause other scenario writers, set finite connection, statement and lock deadlines, call cleanup, insert S00, and commit once. Roll back the entire transaction if any step fails. A successful cleanup call under autocommit commits immediately and cannot be used to make S00 atomic.

## Receipt contract for tickets 1.5 and 1.7

`fixture.scenario_receipts` has primary key `(fixture_version, seed, scenario_id)` and a required `payload_sha256` as 64 lowercase hex characters. For S04 and its S06 replay the same key is `('v1', 42, 'S04')`. S06 is an attempt's trace step. Its original S04 key and payload are the receipt inputs.

Hash the UTF-8 bytes of the JSON object below with SHA-256. Use sorted object keys, compact separators `(',', ':')`, ASCII escaping for non-ASCII text, no trailing newline, and fixed second-precision UTC `Z` timestamps. Preserve the operation array order and use JSON integers for IDs, quantities, seed and cents. In Python the canonical encoding is `json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('utf-8')`. The payload consists of the three key fields and the ordered inserts, including every written field. Exclude run IDs, attempt numbers and observation times.

```json
{
  "fixture_version": "v1",
  "seed": 42,
  "scenario_id": "S04",
  "operations": [
    {"op": "insert", "table": "orders", "row": {"order_id": 30, "customer_id": 1, "order_ref": "O30", "status": "paid", "created_at": "2026-01-01T00:04:00Z", "updated_at": "2026-01-01T00:04:00Z"}},
    {"op": "insert", "table": "order_items", "row": {"item_id": 301, "order_id": 30, "line_no": 1, "sku": "C", "quantity": 2, "unit_cents": 200, "created_at": "2026-01-01T00:04:00Z", "updated_at": "2026-01-01T00:04:00Z"}},
    {"op": "insert", "table": "payments", "row": {"payment_id": 302, "order_id": 30, "payment_ref": "P302", "amount_cents": 400, "created_at": "2026-01-01T00:04:00Z", "updated_at": "2026-01-01T00:04:00Z"}}
  ]
}
```

The canonical S04 digest is `4d2c11bd073069f7a4a9f38ba044d58219fad0c37ab3a2b43b300a97414432f8`.

Run the receipt claim and business inserts in one `READ COMMITTED` transaction with `synchronous_commit=on`. Claim with a parameterized `INSERT ... ON CONFLICT (fixture_version, seed, scenario_id) DO NOTHING RETURNING payload_sha256`. If the insert returns a row, execute the matching business operations and commit together. If it returns no row, read the stored digest in a separate statement in that transaction. A match means the earlier attempt committed and replay has no writes. A mismatch rejects the attempt, and an unavailable read or missing receipt after a conflict leaves the outcome unresolved. The separate statement gets a fresh snapshot after a concurrent claimant commits. Use finite deadlines. After an ambiguous commit, reconnect and reconcile using the same key and digest before trying the claim again. Never overwrite an existing digest. Serialize reset outside the replay window, because reset intentionally removes receipts. [PostgreSQL 16 `INSERT`](https://www.postgresql.org/docs/16/sql-insert.html) · [Transaction isolation](https://www.postgresql.org/docs/16/transaction-iso.html)

## Acceptance checks

Use a fresh volume from the verified 1.2 procedure. Define `disposable_id` and `admin_psql` as above and let the suite perform the first migration. Record the source profile evidence, branch and commit, versions, start/end UTC, role checks, disk observations and outcome for the run. Use the 1.2 disk stop thresholds.

```bash
run_id="$(date -u +%Y%m%dT%H%M%SZ)-p01-01"
mkdir -p /tmp/cdc-lab-evidence
bash tests/integration/source-schema/run.sh "/tmp/cdc-lab-evidence/$run_id" \
    "$disposable_id" "${admin_psql[@]}"
```

The suite uses test-only rows with keys 901–913, opens a separate reader session for every snapshot, and records ordered rows for each table and the receipts. It captures catalog definitions and grants and compares those before and after repeat bootstrap and committed cleanup. Negative probes assert SQLSTATE and the constraint or guard diagnostic, then compare every committed field against the baseline. For the cleanup rollback test, the writer observes the five empty relations inside the transaction before a forced division-by-zero error. The next reader session must see the original rows, including the receipt. Committed cleanup must leave the five relations empty and preserve the installation and grants.

The automated grant checks use `SET SESSION AUTHORIZATION` in authenticated admin sessions on the disposable volume. Also verify the two provisioned identities over the 1.2 loopback SCRAM path. Run the following from the VM, enter the corresponding local role password when prompted, and save the output without passwords. Expect the named role and `source_lab` in each result.

```bash
for role in source_fixture_writer source_fixture_reader; do
    source_compose exec source-db env PGCONNECT_TIMEOUT=3 PGREQUIREAUTH=scram-sha-256 \
        psql -XWAt -h 127.0.0.1 -U "$role" -d source_lab \
        -c 'SELECT current_user, current_database(), count(*) FROM fixture.scenario_receipts;'
done
```

If a check fails, capture the evidence directory and relevant redacted source logs before starting a fresh run. The suite stops on any unexpected initial rows. Preserve raw outputs outside Git and record reviewed observations in EXP-005.
