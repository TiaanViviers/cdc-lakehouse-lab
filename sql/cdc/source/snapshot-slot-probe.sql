SELECT count(*) = 1 AND bool_and(
    slot_name = :'slot' AND slot_type = 'logical' AND database = current_database()
    AND plugin = 'pgoutput' AND NOT temporary AND NOT active
    AND restart_lsn = :'created_restart_lsn'::pg_lsn
    AND confirmed_flush_lsn = :'created_flush_lsn'::pg_lsn
) AS persistent_only FROM pg_replication_slots \gset
\if :persistent_only
\else
    DO $$ BEGIN RAISE EXCEPTION 'snapshot trial requires only the recorded inactive persistent slot'; END $$;
\endif

SET SESSION AUTHORIZATION :"publisher";
SELECT * FROM pg_create_logical_replication_slot(:'snapshot_slot', 'pgoutput', true);
SELECT slot_name, temporary, active, active_pid = pg_backend_pid() AS held_by_this_session
FROM pg_replication_slots ORDER BY slot_name;

-- The only intentional failure in this script. End the session after checking the SQLSTATE.
\set ON_ERROR_STOP off
SELECT * FROM pg_create_logical_replication_slot(('cap_' || :'run_key')::name, 'pgoutput', true);
\set ON_ERROR_STOP on
SELECT :'SQLSTATE' = '53400' AS cap_rejected \gset
\if :cap_rejected
    \echo Slot cap rejected third allocation (53400)
\else
    DO $$ BEGIN RAISE EXCEPTION 'expected PG16 replication slot exhaustion'; END $$;
\endif
