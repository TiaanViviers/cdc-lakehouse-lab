BEGIN;
SELECT EXISTS (
    SELECT FROM pg_authid
    WHERE rolname = :'publisher' AND oid = :'created_role_oid'::oid
      AND rolreplication AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
      AND NOT rolbypassrls AND NOT rolinherit
      AND (NOT :'enable_login'::boolean OR rolpassword LIKE 'SCRAM-SHA-256$%')
) AS expected_role \gset
\if :expected_role
\else
    DO $$ BEGIN RAISE EXCEPTION 'publisher role identity or SCRAM verifier mismatch'; END $$;
\endif
\if :enable_login
    ALTER ROLE :"publisher" LOGIN;
\else
    ALTER ROLE :"publisher" NOLOGIN;
\endif
COMMIT;
