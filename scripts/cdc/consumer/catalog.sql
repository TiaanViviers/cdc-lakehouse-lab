BEGIN READ ONLY;
SELECT to_regclass('ducklake.ducklake_metadata') IS NOT NULL AS initialized \gset
\if :initialized
WITH tables AS (
    SELECT s.schema_name, s.path AS schema_path, s.path_is_relative AS schema_relative,
           t.table_id, t.table_name, t.path AS table_path, t.path_is_relative AS table_relative,
           t.begin_snapshot
    FROM ducklake.ducklake_table t JOIN ducklake.ducklake_schema s USING (schema_id)
    WHERE s.schema_name = 'bronze' AND t.end_snapshot IS NULL AND s.end_snapshot IS NULL
    ORDER BY t.table_id LIMIT 33
), data_files AS (
    SELECT f.table_id, f.data_file_id AS file_id, f.begin_snapshot, f.path, f.path_is_relative,
           f.file_format AS format, f.record_count, f.file_size_bytes
    FROM ducklake.ducklake_data_file f JOIN tables t USING (table_id)
    WHERE f.end_snapshot IS NULL ORDER BY f.data_file_id LIMIT 33
), delete_files AS (
    SELECT f.table_id, f.delete_file_id AS file_id, f.begin_snapshot, f.path, f.path_is_relative,
           f.format, f.delete_count AS record_count, f.file_size_bytes
    FROM ducklake.ducklake_delete_file f JOIN tables t USING (table_id)
    WHERE f.end_snapshot IS NULL ORDER BY f.delete_file_id LIMIT 33
)
SELECT json_build_object(
    'catalog_schema', 'ducklake',
    'options', (SELECT json_agg(m ORDER BY key, scope, scope_id) FROM (
        SELECT key, value, scope, scope_id FROM ducklake.ducklake_metadata
        WHERE key IN ('version', 'data_path', 'data_inlining_row_limit')
        ORDER BY key, scope, scope_id LIMIT 33
    ) m),
    'snapshots', (SELECT json_agg(s ORDER BY snapshot_id) FROM (
        SELECT snapshot_id, snapshot_time, schema_version FROM ducklake.ducklake_snapshot
        ORDER BY snapshot_id DESC LIMIT 16
    ) s),
    'tables', coalesce((SELECT json_agg(t ORDER BY table_id) FROM tables t), '[]'::json),
    'inline_tables', coalesce((SELECT json_agg(i ORDER BY table_id, schema_version) FROM (
        SELECT i.table_id, i.table_name, i.schema_version
        FROM ducklake.ducklake_inlined_data_tables i JOIN tables t USING (table_id)
        ORDER BY i.table_id, i.schema_version LIMIT 33
    ) i), '[]'::json),
    'data_files', coalesce((SELECT json_agg(f ORDER BY file_id) FROM data_files f), '[]'::json),
    'delete_files', coalesce((SELECT json_agg(f ORDER BY file_id) FROM delete_files f), '[]'::json)
);
\else
SELECT '{"catalog_schema":null}';
\endif
COMMIT;
