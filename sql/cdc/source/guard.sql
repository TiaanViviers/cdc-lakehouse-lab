-- Included by source-only mutating scripts. Parameters come from operator inventory.
\set ON_ERROR_STOP on
SET search_path = pg_catalog, pg_temp;
SET statement_timeout = '10s';
SET lock_timeout = '3s';
SET idle_in_transaction_session_timeout = '15s';

SELECT current_database() = 'source_lab'
       AND session_user = 'source_admin' AND current_user = session_user
       AND current_setting('server_version_num') = '160016'
       AND current_setting('wal_level') = 'logical'
       AND current_setting('max_replication_slots') = '2'
       AND current_setting('max_wal_senders') = '2'
       AND :'run_key' ~ '^[a-z][a-z0-9]{7,23}$' AS target_ok \gset
\if :target_ok
\else
    DO $$ BEGIN RAISE EXCEPTION 'refusing CDC operation on unexpected source or run key'; END $$;
\endif

-- Session lock serializes these scripts across transactional and slot operations.
SELECT pg_try_advisory_lock(1348076337, 22) AS locked \gset
\if :locked
\else
    DO $$ BEGIN RAISE EXCEPTION 'another publisher lifecycle session holds the lock'; END $$;
\endif

SELECT EXISTS (
    SELECT FROM fixture.installation AS i
    JOIN pg_database AS d ON d.oid = i.database_oid
    WHERE d.datname = current_database() AND i.schema_version = 1
      AND i.system_identifier = (SELECT system_identifier FROM pg_control_system())
      AND i.disposable_id = :'disposable_id'::uuid
      AND i.disposable_id <> '00000000-0000-0000-0000-000000000000'::uuid
) AS enrolled,
'publisher_' || :'run_key' AS publisher,
'pub_' || :'run_key' AS publication,
'slot_' || :'run_key' AS slot,
'snap_' || :'run_key' AS snapshot_slot \gset
\if :enrolled
\else
    DO $$ BEGIN RAISE EXCEPTION 'refusing CDC operation: fixture enrollment mismatch'; END $$;
\endif
