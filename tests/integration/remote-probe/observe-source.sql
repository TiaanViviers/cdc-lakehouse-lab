SELECT 'wal', pg_current_wal_insert_lsn(), pg_current_wal_flush_lsn();
SELECT 'slot', slot_name, plugin, database, temporary, active, active_pid,
       restart_lsn, confirmed_flush_lsn, wal_status
FROM pg_replication_slots ORDER BY slot_name;
SELECT 'publication', pubname, pg_get_userbyid(pubowner), pubinsert, pubupdate, pubdelete
FROM pg_publication ORDER BY pubname;
SELECT 'member', pubname, schemaname, tablename
FROM pg_publication_tables ORDER BY pubname, schemaname, tablename;
SELECT 'sender', pid, usename, application_name, client_addr, state,
       sent_lsn, write_lsn, flush_lsn, replay_lsn
FROM pg_stat_replication ORDER BY pid;
SELECT 'identity', c.relreplident
FROM pg_class c WHERE c.oid = to_regclass('probe.items');
