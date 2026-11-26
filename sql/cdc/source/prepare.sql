-- Independent baseline. The role stays NOLOGIN until its HBA and SCRAM are configured.
BEGIN;
CREATE ROLE :"publisher" NOLOGIN REPLICATION NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;

GRANT CONNECT ON DATABASE source_lab TO :"publisher";
GRANT USAGE ON SCHEMA fixture TO :"publisher";
GRANT SELECT ON fixture.customers, fixture.orders, fixture.order_items, fixture.payments TO :"publisher";
SELECT oid, rolname FROM pg_roles WHERE rolname = :'publisher';
COMMIT;
