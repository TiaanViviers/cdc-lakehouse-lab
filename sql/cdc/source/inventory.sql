SELECT current_database(), current_setting('server_version_num'),
       current_setting('password_encryption'), current_setting('max_slot_wal_keep_size');
SELECT rolname, oid, rolcanlogin, rolreplication, rolsuper, rolcreatedb, rolcreaterole,
       rolbypassrls, rolinherit
FROM pg_roles WHERE rolname LIKE 'publisher\_%' OR rolname LIKE 'source\_fixture\_%'
ORDER BY rolname;
SELECT member.rolname, parent.rolname, m.admin_option, m.inherit_option, m.set_option
FROM pg_auth_members AS m
JOIN pg_roles AS member ON member.oid = m.member
JOIN pg_roles AS parent ON parent.oid = m.roleid
WHERE member.rolname LIKE 'publisher\_%' OR member.rolname LIKE 'source\_fixture\_%'
ORDER BY 1, 2;
SELECT datname, datacl FROM pg_database WHERE datname = current_database();
SELECT rolname, has_database_privilege(oid, current_database(), 'CONNECT') AS db_connect,
       has_database_privilege(oid, current_database(), 'CREATE') AS db_create,
       has_schema_privilege(oid, 'fixture', 'USAGE') AS fixture_usage,
       has_schema_privilege(oid, 'fixture', 'CREATE') AS fixture_create
FROM pg_roles WHERE rolname = :'publisher';
SELECT nspname, pg_get_userbyid(nspowner), nspacl FROM pg_namespace WHERE nspname = 'fixture';
SELECT c.oid, c.relname, pg_get_userbyid(c.relowner), c.relreplident, c.relacl
FROM pg_class AS c WHERE c.relnamespace = 'fixture'::regnamespace AND c.relkind = 'r'
ORDER BY c.relname;
SELECT c.relname, has_table_privilege(r.oid, c.oid, 'SELECT') AS can_read,
       has_table_privilege(r.oid, c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE') AS can_write,
       EXISTS (
           SELECT FROM pg_index AS i WHERE i.indrelid = c.oid AND i.indisprimary AND i.indisvalid
       ) AS valid_primary_key
FROM pg_class AS c CROSS JOIN pg_roles AS r
WHERE r.rolname = :'publisher' AND c.relnamespace = 'fixture'::regnamespace AND c.relkind = 'r'
ORDER BY c.relname;
SELECT c.relname, a.attname, a.attacl
FROM pg_class AS c JOIN pg_attribute AS a ON a.attrelid = c.oid
WHERE c.relnamespace = 'fixture'::regnamespace AND a.attacl IS NOT NULL
ORDER BY 1, 2;
SELECT oid, pubname, pg_get_userbyid(pubowner), puballtables, pubinsert, pubupdate, pubdelete,
       pubtruncate, pubviaroot FROM pg_publication ORDER BY pubname;
SELECT pubname, schemaname, tablename, attnames, rowfilter
FROM pg_publication_tables ORDER BY 1, 2, 3;
SELECT slot_name, slot_type, plugin, database, datoid, temporary, active,
       restart_lsn, confirmed_flush_lsn
FROM pg_replication_slots ORDER BY slot_name;
SELECT rule_number, type, database, user_name, address, netmask, auth_method, error
FROM pg_hba_file_rules ORDER BY rule_number;
