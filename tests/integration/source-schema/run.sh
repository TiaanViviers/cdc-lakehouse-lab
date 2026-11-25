#!/usr/bin/env bash
set -euo pipefail

if (( $# < 3 )); then
    echo 'Usage: bash run.sh NEW_EVIDENCE_DIR DISPOSABLE_UUID PSQL_COMMAND [ARG ...]' >&2
    exit 2
fi
evidence_dir=$1
disposable_id=$2
shift 2
here=$(cd -- "$(dirname -- "$0")" && pwd)
root=$(cd -- "$here/../../.." && pwd)

# The caller supplies the source-local psql command from the verified 1.2 environment.
psql=("$@" -XqAt -v ON_ERROR_STOP=1 -v VERBOSITY=verbose -v "disposable_id=$disposable_id"
    -c "SET statement_timeout = '10s'; SET lock_timeout = '3s'; SET idle_in_transaction_session_timeout = '10s'" -f -)
mkdir -- "$evidence_dir"

compare() {
    diff -u -- "$1" "$2"
}

expect_error() {
    local name=$1 state=$2 diagnostic=$3 exit_code=0
    # Read the exact negative SQL from stdin and retain it with the server response.
    cat > "$evidence_dir/$name.sql"
    "${psql[@]}" < "$evidence_dir/$name.sql" > "$evidence_dir/$name.log" 2>&1 || exit_code=$?
    if [[ $exit_code != 3 ]] || ! grep -Eq "ERROR:[[:space:]]+$state:" "$evidence_dir/$name.log" \
        || ! grep -Fq -- "$diagnostic" "$evidence_dir/$name.log"; then
        echo "FAIL $name (expected SQLSTATE $state and $diagnostic, psql exit $exit_code)" >&2
        cat -- "$evidence_dir/$name.log" >&2
        return 1
    fi
    "${psql[@]}" < "$here/rows.sql" > "$evidence_dir/$name.rows"
    compare "$evidence_dir/before.rows" "$evidence_dir/$name.rows"
    printf 'PASS %s (%s; full rows and receipts unchanged)\n' "$name" "$state"
}

reject() {
    local name=$1 state=$2 diagnostic=$3 role=$4 statement=$5
    if [[ $role == admin ]]; then
        expect_error "$name" "$state" "$diagnostic" <<< "$statement"
    else
        expect_error "$name" "$state" "$diagnostic" <<SQL
SET SESSION AUTHORIZATION $role;
$statement
SQL
    fi
}

writer=source_fixture_writer
reader=source_fixture_reader
migration=$root/sql/source/001_fixture_v1.sql
probe_time="TIMESTAMPTZ '2026-02-03T00:00:00Z'"

"${psql[@]}" <<< "SELECT current_setting('server_version_num');" > "$evidence_dir/server-version"
compare <(printf '160016\n') "$evidence_dir/server-version"
"${psql[@]}" < "$migration" > "$evidence_dir/bootstrap-first.log" 2>&1
"${psql[@]}" < "$here/catalog.sql" > "$evidence_dir/schema-initial.txt"
grep -Fx 'installation|1|t|t|t' "$evidence_dir/schema-initial.txt"
grep -Fx 'role|source_fixture_writer|t|f|f|f|f|f|t|f|f' "$evidence_dir/schema-initial.txt"
grep -Fx 'role|source_fixture_reader|t|f|f|f|f|f|t|f|f' "$evidence_dir/schema-initial.txt"
if grep -q '^membership|' "$evidence_dir/schema-initial.txt"; then
    echo 'Unexpected role membership for a fixture role' >&2
    exit 1
fi
"${psql[@]}" < "$here/rows.sql" > "$evidence_dir/initial.rows"
printf '%s|[]\n' customers orders order_items payments scenario_receipts > "$evidence_dir/expected-empty.rows"
compare "$evidence_dir/expected-empty.rows" "$evidence_dir/initial.rows"

"${psql[@]}" < "$here/probe-rows.sql" > "$evidence_dir/probe-rows.log" 2>&1
"${psql[@]}" < "$here/rows.sql" > "$evidence_dir/before.rows"
compare "$here/expected-probe-rows.txt" "$evidence_dir/before.rows"
"${psql[@]}" < "$migration" > "$evidence_dir/bootstrap-repeat.log" 2>&1
grep -Fx 'Fixture schema 1 already installed' "$evidence_dir/bootstrap-repeat.log"
"${psql[@]}" < "$here/rows.sql" > "$evidence_dir/repeat.rows"
"${psql[@]}" < "$here/catalog.sql" > "$evidence_dir/schema-repeat.txt"
compare "$evidence_dir/before.rows" "$evidence_dir/repeat.rows"
compare "$evidence_dir/schema-initial.txt" "$evidence_dir/schema-repeat.txt"
echo 'PASS repeat bootstrap (full rows, receipts, schema and grants unchanged)'

reject orphan-order 23503 orders_customer_fk "$writer" \
    "INSERT INTO fixture.orders VALUES (915, 999, 'O915', 'open', $probe_time, $probe_time);"
reject orphan-item 23503 order_items_order_fk "$writer" \
    "INSERT INTO fixture.order_items VALUES (915, 999, 1, 'Test', 1, 0, $probe_time, $probe_time);"
reject orphan-payment 23503 payments_order_fk "$writer" \
    "BEGIN; INSERT INTO fixture.scenario_receipts VALUES ('v1', 0, 'S03', repeat('b', 64));
    INSERT INTO fixture.payments VALUES (915, 999, 'P915', 0, $probe_time, $probe_time); COMMIT;"
reject restricted-customer-delete 23503 orders_customer_fk admin \
    'DELETE FROM fixture.customers WHERE customer_id = 901;'
reject restricted-order-delete 23503 order_fk admin \
    'DELETE FROM fixture.orders WHERE order_id = 910;'
reject duplicate-customer-pk 23505 customers_pkey "$writer" \
    "INSERT INTO fixture.customers VALUES (901, 'C915', 'Test', $probe_time, $probe_time);"
reject duplicate-customer-code 23505 customers_code_key "$writer" \
    "INSERT INTO fixture.customers VALUES (915, 'C901', 'Test', $probe_time, $probe_time);"
reject duplicate-order-ref 23505 orders_ref_key "$writer" \
    "INSERT INTO fixture.orders VALUES (915, 901, 'O910', 'open', $probe_time, $probe_time);"
reject duplicate-line 23505 order_items_order_line_key "$writer" \
    "INSERT INTO fixture.order_items VALUES (915, 910, 1, 'Test', 1, 0, $probe_time, $probe_time);"
reject duplicate-payment-ref 23505 payments_ref_key "$writer" \
    "INSERT INTO fixture.payments VALUES (915, 910, 'P912', 0, $probe_time, $probe_time);"
reject duplicate-receipt 23505 scenario_receipts_pkey "$writer" \
    "INSERT INTO fixture.scenario_receipts VALUES ('v1', 0, 'S04', repeat('b', 64));"
reject null-timestamp 23502 created_at "$writer" \
    "INSERT INTO fixture.customers VALUES (915, 'C915', 'Test', NULL, $probe_time);"
reject nonpositive-id 23514 customers_positive_id "$writer" \
    "INSERT INTO fixture.customers VALUES (0, 'C915', 'Test', $probe_time, $probe_time);"
reject invalid-status 23514 orders_valid_status "$writer" \
    "INSERT INTO fixture.orders VALUES (915, 901, 'O915', 'invalid', $probe_time, $probe_time);"
reject nonpositive-line 23514 order_items_positive_line "$writer" \
    "INSERT INTO fixture.order_items VALUES (915, 910, 0, 'Test', 1, 0, $probe_time, $probe_time);"
reject nonpositive-quantity 23514 order_items_positive_quantity "$writer" \
    'UPDATE fixture.order_items SET quantity = 0 WHERE item_id = 911;'
reject negative-unit-cents 23514 order_items_nonnegative_cents "$writer" \
    "INSERT INTO fixture.order_items VALUES (915, 910, 2, 'Test', 1, -1, $probe_time, $probe_time);"
reject negative-payment-cents 23514 payments_nonnegative_cents "$writer" \
    "INSERT INTO fixture.payments VALUES (915, 910, 'P915', -1, $probe_time, $probe_time);"
reject invalid-payload-digest 23514 scenario_receipts_sha256 "$writer" \
    "INSERT INTO fixture.scenario_receipts VALUES ('v1', 0, 'S02', 'invalid');"

reject reader-update 42501 order_items "$reader" \
    'UPDATE fixture.order_items SET quantity = 9 WHERE item_id = 911;'
reject reader-insert-receipt 42501 scenario_receipts "$reader" \
    "INSERT INTO fixture.scenario_receipts VALUES ('v1', 0, 'S03', repeat('b', 64));"
reject reader-cleanup 42501 cleanup "$reader" \
    "SELECT fixture.cleanup(true, :'disposable_id'::uuid);"
reject writer-change-pk 42501 order_items "$writer" 'UPDATE fixture.order_items SET item_id = 915;'
reject writer-change-created-at 42501 order_items "$writer" "UPDATE fixture.order_items SET created_at = $probe_time;"
reject writer-update-receipt 42501 scenario_receipts "$writer" \
    "UPDATE fixture.scenario_receipts SET payload_sha256 = repeat('b', 64);"
reject writer-delete-receipt 42501 scenario_receipts "$writer" 'DELETE FROM fixture.scenario_receipts;'
reject writer-truncate 42501 order_items "$writer" 'TRUNCATE fixture.order_items;'
reject writer-create-table 42501 fixture "$writer" 'CREATE TABLE fixture.unauthorized (id int);'
reject writer-alter-identity 42501 installation "$writer" \
    "UPDATE fixture.installation SET disposable_id = '00000000-0000-0000-0000-000000000000';"

# A read-only transaction would report a different SQLSTATE if cleanup attempted a DELETE.
reject reset-without-intent 22023 'requires explicit reset intent' "$writer" \
    "BEGIN READ ONLY; SELECT fixture.cleanup(false, :'disposable_id'::uuid);"
reject reset-null-intent 22023 'requires explicit reset intent' "$writer" \
    "BEGIN READ ONLY; SELECT fixture.cleanup(NULL, :'disposable_id'::uuid);"
reject reset-wrong-id 55000 'disposable database identity mismatch' "$writer" \
    "BEGIN READ ONLY; SELECT fixture.cleanup(true, '00000000-0000-0000-0000-000000000000');"
reject reset-missing-id 55000 'disposable database identity mismatch' "$writer" \
    'BEGIN READ ONLY; SELECT fixture.cleanup(true, NULL);'
expect_error reset-no-marker 55000 'disposable database identity mismatch' <<'SQL'
BEGIN;
DELETE FROM fixture.installation;
SET LOCAL SESSION AUTHORIZATION source_fixture_writer;
SELECT fixture.cleanup(true, :'disposable_id'::uuid);
SQL
expect_error reset-database-oid-mismatch 55000 'disposable database identity mismatch' <<'SQL'
BEGIN;
UPDATE fixture.installation SET database_oid = 0;
SET LOCAL SESSION AUTHORIZATION source_fixture_writer;
SELECT fixture.cleanup(true, :'disposable_id'::uuid);
SQL
expect_error reset-cluster-mismatch 55000 'disposable database identity mismatch' <<'SQL'
BEGIN;
UPDATE fixture.installation SET system_identifier = 0;
SET LOCAL SESSION AUTHORIZATION source_fixture_writer;
SELECT fixture.cleanup(true, :'disposable_id'::uuid);
SQL

expect_error cleanup-rollback 22012 'division by zero' <<'SQL'
SET SESSION AUTHORIZATION source_fixture_writer;
BEGIN;
SELECT fixture.cleanup(true, :'disposable_id'::uuid);
DO $$ BEGIN
    IF EXISTS (SELECT FROM fixture.customers) OR EXISTS (SELECT FROM fixture.orders)
        OR EXISTS (SELECT FROM fixture.order_items) OR EXISTS (SELECT FROM fixture.payments)
        OR EXISTS (SELECT FROM fixture.scenario_receipts) THEN
        RAISE EXCEPTION 'cleanup left fixture rows behind inside the transaction';
    END IF;
END $$;
SELECT 1 / 0;
COMMIT;
SQL

"${psql[@]}" > "$evidence_dir/cleanup-commit.log" 2>&1 <<'SQL'
SET SESSION AUTHORIZATION source_fixture_writer;
BEGIN;
SELECT fixture.cleanup(true, :'disposable_id'::uuid);
COMMIT;
SQL
"${psql[@]}" < "$here/rows.sql" > "$evidence_dir/after.rows"
"${psql[@]}" < "$here/catalog.sql" > "$evidence_dir/schema-after.txt"
compare "$evidence_dir/expected-empty.rows" "$evidence_dir/after.rows"
compare "$evidence_dir/schema-initial.txt" "$evidence_dir/schema-after.txt"
echo 'PASS committed cleanup (all fixture rows and receipts removed; installation and grants preserved)'
