-- Native PG16 source-only trial. Capture the returned fingerprint immediately.
SELECT NOT EXISTS (SELECT FROM pg_replication_slots) AND NOT EXISTS (SELECT FROM pg_publication)
       AS empty_inventory \gset
\if :empty_inventory
\else
    DO $$ BEGIN RAISE EXCEPTION 'slot creation requires an empty replication inventory'; END $$;
\endif

SET SESSION AUTHORIZATION :"publisher";
SELECT * FROM pg_create_logical_replication_slot(:'slot', 'pgoutput');
RESET SESSION AUTHORIZATION;
SELECT slot_name, datoid, plugin, temporary, active, restart_lsn, confirmed_flush_lsn
FROM pg_replication_slots WHERE slot_name = :'slot';
