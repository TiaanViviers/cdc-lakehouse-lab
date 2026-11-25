BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL search_path = pg_catalog, pg_temp;

SELECT version(), current_database(), session_user;
SELECT 'installation', schema_version, disposable_id = :'disposable_id'::uuid AS uuid_matches,
       database_oid = (SELECT oid FROM pg_database WHERE datname = current_database()) AS oid_matches,
       system_identifier = (SELECT system_identifier FROM pg_control_system()) AS cluster_matches
FROM fixture.installation;

SELECT 'column', c.relname, a.attnum, a.attname, format_type(a.atttypid, a.atttypmod) AS type, a.attnotnull
FROM pg_attribute AS a
JOIN pg_class AS c ON c.oid = a.attrelid
WHERE c.relnamespace = 'fixture'::regnamespace AND c.relkind = 'r'
  AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY c.relname, a.attnum;

SELECT 'constraint', conrelid::regclass, conname, convalidated, condeferrable, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE connamespace = 'fixture'::regnamespace
ORDER BY conrelid::regclass::text, conname;

SELECT 'role', rolname, rolcanlogin, rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls,
       has_database_privilege(rolname, current_database(), 'CONNECT') AS can_connect,
       has_database_privilege(rolname, current_database(), 'TEMP') AS can_create_temp,
       has_schema_privilege(rolname, 'fixture', 'CREATE') AS can_create_in_fixture
FROM pg_roles
WHERE rolname IN ('source_fixture_owner', 'source_fixture_reader', 'source_fixture_writer')
ORDER BY rolname;

SELECT 'membership', member.rolname, granted.rolname
FROM pg_auth_members AS memberships
JOIN pg_roles AS member ON member.oid = memberships.member
JOIN pg_roles AS granted ON granted.oid = memberships.roleid
WHERE member.rolname IN ('source_fixture_owner', 'source_fixture_reader', 'source_fixture_writer')
ORDER BY member.rolname, granted.rolname;

SELECT 'table ACL', relname, relowner::regrole, relacl
FROM pg_class
WHERE relnamespace = 'fixture'::regnamespace AND relkind = 'r'
ORDER BY relname;

SELECT 'column ACL', attrelid::regclass, attname, attacl
FROM pg_attribute
WHERE attrelid = 'fixture.order_items'::regclass AND attacl IS NOT NULL
ORDER BY attnum;

SELECT 'function', proname, proowner::regrole, prosecdef, proacl, pg_get_functiondef(oid)
FROM pg_proc
WHERE oid = 'fixture.cleanup(boolean, uuid)'::regprocedure;

COMMIT;
