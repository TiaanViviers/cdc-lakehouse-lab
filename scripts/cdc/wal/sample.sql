BEGIN READ ONLY;
SET LOCAL search_path = pg_catalog;
SET LOCAL statement_timeout = '2s';
SET LOCAL lock_timeout = '1s';
SET LOCAL timezone = 'UTC';

SELECT current_database() = 'source_lab'
       AND current_setting('server_version_num')::integer = 160016
       AND current_setting('data_directory') = '/var/lib/postgresql/data'
       AND current_setting('wal_level') = 'logical'
       AND NOT pg_is_in_recovery()
       AND (SELECT system_identifier::text FROM pg_control_system()) = :'system_identifier'
       AS source_matches
\gset

\if :source_matches
WITH positions AS MATERIALIZED (
    SELECT pg_current_wal_insert_lsn() AS insert_lsn,
           pg_current_wal_lsn() AS write_lsn,
           pg_current_wal_flush_lsn() AS flush_lsn,
           (SELECT timeline_id FROM pg_control_checkpoint()) AS checkpoint_timeline_id,
           pg_postmaster_start_time() AS postmaster_started_at
), slot_inventory AS MATERIALIZED (
    -- The enrolled profile budgets two slots. The extra row detects overflow.
    SELECT slot_name, slot_type, database, plugin, temporary, active, active_pid,
           restart_lsn, confirmed_flush_lsn, wal_status, safe_wal_size
    FROM pg_replication_slots
    LIMIT 3
), publication_inventory AS MATERIALIZED (
    SELECT pubname, puballtables,
           EXISTS (SELECT FROM pg_publication_namespace WHERE pnpubid = p.oid) AS schema_wide
    FROM pg_publication AS p
    LIMIT 2
), members AS MATERIALIZED (
    SELECT schemaname AS schema, tablename AS table,
           rowfilter IS NOT NULL AS filtered
    FROM pg_publication_tables
    WHERE pubname = :'publication'
    ORDER BY schemaname, tablename
    LIMIT 33
)
SELECT json_build_object(
    'server_version_num', current_setting('server_version_num')::integer,
    'positions', row_to_json(p),
    'slot_inventory_count', (SELECT count(*) FROM slot_inventory),
    'publication_inventory_count', (SELECT count(*) FROM publication_inventory),
    'publication', (SELECT row_to_json(pub) FROM publication_inventory AS pub WHERE pubname = :'publication'),
    'members', COALESCE((SELECT json_agg(m) FROM members AS m), '[]'::json),
    'slot', (SELECT row_to_json(s) FROM slot_inventory AS s WHERE slot_name = :'slot'),
    'feedback', (SELECT row_to_json(f) FROM (
        SELECT r.pid, r.state, r.sent_lsn, r.write_lsn, r.flush_lsn, r.replay_lsn,
               r.write_lag, r.flush_lag, r.replay_lag, r.reply_time
        FROM slot_inventory AS s JOIN pg_stat_replication AS r ON r.pid = s.active_pid
        WHERE s.slot_name = :'slot' AND s.active AND NOT s.temporary
          AND s.slot_type = 'logical' AND s.plugin = 'pgoutput' AND s.database = current_database()
    ) AS f),
    'wal_bytes', json_build_object(
        'insert_since_previous',
        CASE WHEN p.checkpoint_timeline_id = NULLIF(:'previous_timeline', '')::integer
                  AND p.postmaster_started_at = NULLIF(:'previous_start', '')::timestamptz
             THEN pg_wal_lsn_diff(p.insert_lsn, NULLIF(:'previous_insert', '')::pg_lsn) END,
        'insert_to_restart', pg_wal_lsn_diff(p.insert_lsn, s.restart_lsn),
        'insert_to_confirmed_flush', pg_wal_lsn_diff(p.insert_lsn, s.confirmed_flush_lsn)
    )
)
FROM positions AS p
LEFT JOIN slot_inventory AS s ON s.slot_name = :'slot';
\else
SELECT '{"error":"source_identity"}';
\endif
ROLLBACK;
