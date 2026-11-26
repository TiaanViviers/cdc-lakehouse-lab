-- Only for a native test slot whose fingerprint was recorded at creation and has
-- not advanced. Exclusive use of the cluster and reserved names is required.
SELECT EXISTS (
    SELECT FROM pg_replication_slots
    WHERE slot_name = :'slot' AND database = current_database()
      AND datoid = (SELECT oid FROM pg_database WHERE datname = current_database())
      AND slot_type = 'logical' AND plugin = 'pgoutput' AND NOT temporary
      AND NOT two_phase AND NOT active
      AND restart_lsn = :'created_restart_lsn'::pg_lsn
      AND confirmed_flush_lsn = :'created_flush_lsn'::pg_lsn
) AS expected_slot \gset
\if :expected_slot
    -- PostgreSQL also refuses to drop a slot acquired since the inventory check.
    SELECT pg_drop_replication_slot(:'slot');
\else
    DO $$ BEGIN RAISE EXCEPTION 'refusing slot drop: missing, active or unexpected slot'; END $$;
\endif
