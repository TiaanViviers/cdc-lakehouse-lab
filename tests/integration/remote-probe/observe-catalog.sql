SELECT 'catalog_schema', table_schema, table_name
FROM information_schema.tables
WHERE table_name = 'ducklake_metadata';
SELECT to_regclass('ducklake.ducklake_metadata') IS NOT NULL AS initialized \gset
\if :initialized
SELECT 'catalog', key, value, scope, scope_id FROM ducklake.ducklake_metadata
WHERE key IN ('version', 'data_path', 'data_inlining_row_limit') ORDER BY key, scope, scope_id;
SELECT 'table', s.schema_name, s.path, s.path_is_relative,
       t.table_id, t.table_name, t.path, t.path_is_relative, t.begin_snapshot, t.end_snapshot
FROM ducklake.ducklake_table t JOIN ducklake.ducklake_schema s USING (schema_id)
WHERE s.schema_name = 'bronze' AND t.table_name = 'items';
SELECT 'snapshot', snapshot_id, snapshot_time, schema_version
FROM ducklake.ducklake_snapshot ORDER BY snapshot_id LIMIT 20;
SELECT 'data_file', table_id, data_file_id, begin_snapshot, end_snapshot, path,
       path_is_relative, file_format, record_count, file_size_bytes
FROM ducklake.ducklake_data_file ORDER BY data_file_id LIMIT 20;
SELECT 'delete_file', table_id, data_file_id, begin_snapshot, end_snapshot, path,
       path_is_relative, format, delete_count, file_size_bytes
FROM ducklake.ducklake_delete_file ORDER BY delete_file_id LIMIT 20;
SELECT 'inline_table', table_id, table_name, schema_version
FROM ducklake.ducklake_inlined_data_tables ORDER BY table_id LIMIT 20;
SELECT format('SELECT %L, %s, count(*) FROM ducklake.%I', 'inline_rows', table_id, table_name)
FROM ducklake.ducklake_inlined_data_tables ORDER BY table_id LIMIT 20
\gexec
\endif
