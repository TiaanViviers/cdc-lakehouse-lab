BEGIN READ ONLY;
WITH selected AS (
    SELECT id, name, publication, slot_name, enabled, mode, confirmed_lsn, last_sync_at AS last_sync
    FROM duckpipe.sync_groups
    WHERE name = :'group'
), mapped AS (
    SELECT m.id, left(s.source_table, 260) AS source_table, left(s.target_table, 260) AS target_table,
           s.state, s.enabled, s.rows_synced, s.queued_changes, s.consecutive_failures,
           coalesce(s.error_message <> '', false) AS error_present, s.last_sync,
           m.snapshot_lsn, m.applied_lsn, s.snapshot_rows, s.snapshot_duration_ms
    FROM selected g JOIN duckpipe.table_mappings m ON m.group_id = g.id
    JOIN duckpipe.status() s ON s.sync_group = g.name AND s.source_table = m.source_schema || '.' || m.source_table
    ORDER BY m.id LIMIT 33
), backend AS (
    SELECT pid FROM pg_stat_activity
    WHERE backend_type = 'pg_duckpipe:' || :'group' ORDER BY pid LIMIT 2
)
SELECT json_build_object(
    'run_id', :'run_id', 'checkpoint', :'checkpoint', 'sampled_at_utc', clock_timestamp(),
    'elapsed_ms', :'elapsed_ms'::bigint,
    'group', (SELECT row_to_json(g) FROM (SELECT name, publication, slot_name, enabled,
               mode, confirmed_lsn, last_sync FROM selected) g),
    'worker_pids', coalesce((SELECT json_agg(pid) FROM backend), '[]'::json),
    'queue_metrics', (SELECT row_to_json(w) FROM (
        SELECT w.total_queued_bytes, w.is_backpressured, w.active_flushes, w.gate_wait_avg_ms,
               w.gate_timeouts FROM duckpipe.worker_status() w JOIN selected g ON g.name = w.sync_group
    ) w),
    'mapping_overflow', (SELECT count(*) > 32 FROM mapped),
    'mappings', coalesce((SELECT json_agg(m ORDER BY id) FROM (SELECT * FROM mapped ORDER BY id LIMIT 32) m), '[]'::json)
);
COMMIT;
