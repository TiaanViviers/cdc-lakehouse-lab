SELECT 'group', name, publication, slot_name, enabled, mode, table_count,
       last_sync, conninfo IS NOT NULL
FROM duckpipe.groups();
SELECT 'checkpoint', name, confirmed_lsn FROM duckpipe.sync_groups;
SELECT 'table', sync_group, source_table, target_table, state, rows_synced,
       queued_changes, consecutive_failures, error_message IS NOT NULL,
       applied_lsn, snapshot_rows, snapshot_duration_ms
FROM duckpipe.status();
SELECT 'worker', * FROM duckpipe.worker_status();
SELECT 'backend', pid, backend_type, application_name, state
FROM pg_stat_activity WHERE backend_type LIKE '%duckpipe%' ORDER BY pid;
SELECT 'access_method', a.amname
FROM pg_class c JOIN pg_am a ON a.oid = c.relam
WHERE c.oid = to_regclass('bronze.items');
