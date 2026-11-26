BEGIN;
CREATE SCHEMA IF NOT EXISTS bronze;
SELECT duckpipe.set_config('duckdb_threads', '1');
SELECT duckpipe.set_config('duckdb_buffer_memory_mb', '16');
SELECT duckpipe.set_config('duckdb_flush_memory_mb', '96');
SELECT duckpipe.set_config('max_concurrent_flushes', '1');
SELECT duckpipe.set_config('max_queued_bytes', '1048576');
COMMIT;
SELECT duckpipe.get_config();
