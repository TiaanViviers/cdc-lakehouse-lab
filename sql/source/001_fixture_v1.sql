\set ON_ERROR_STOP on
\if :{?disposable_id}
\else
    \set disposable_id ''
\endif

BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '10s';

SELECT current_database() = 'source_lab' AND session_user = 'source_admin'
       AND coalesce(NULLIF(:'disposable_id', '')::uuid <> '00000000-0000-0000-0000-000000000000', false)
       AS allowed \gset
\if :allowed
\else
    DO $$ BEGIN
        RAISE EXCEPTION 'bootstrap requires source_admin on source_lab and a disposable database UUID';
    END $$;
\endif

-- Serialize bootstrap attempts before examining the version marker.
SELECT pg_advisory_xact_lock(1348076337, 1);
SELECT to_regclass('fixture.installation') IS NOT NULL AS installed \gset
\if :installed
    SELECT EXISTS (
        SELECT FROM fixture.installation AS installation
        JOIN pg_database AS db ON db.oid = installation.database_oid
        WHERE db.datname = current_database() AND installation.schema_version = 1
          AND installation.system_identifier = (SELECT system_identifier FROM pg_control_system())
          AND installation.disposable_id = :'disposable_id'::uuid
    ) AS matches \gset
    \if :matches
        \echo Fixture schema 1 already installed
    \else
        DO $$ BEGIN
            RAISE EXCEPTION 'existing fixture installation does not match schema version or disposable database identity';
        END $$;
    \endif
\else
    CREATE ROLE source_fixture_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    CREATE ROLE source_fixture_writer LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    CREATE ROLE source_fixture_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

    REVOKE ALL ON DATABASE source_lab FROM PUBLIC;
    GRANT CONNECT ON DATABASE source_lab TO source_fixture_writer, source_fixture_reader;
    REVOKE CREATE ON SCHEMA public FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION pg_control_system() TO source_fixture_owner;
    CREATE SCHEMA fixture AUTHORIZATION source_fixture_owner;
    SET LOCAL ROLE source_fixture_owner;

    CREATE TABLE fixture.customers (
        customer_id integer PRIMARY KEY CONSTRAINT customers_positive_id CHECK (customer_id > 0),
        code text NOT NULL CONSTRAINT customers_code_key UNIQUE,
        name text NOT NULL,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL
    );

    CREATE TABLE fixture.orders (
        order_id integer PRIMARY KEY CONSTRAINT orders_positive_id CHECK (order_id > 0),
        customer_id integer NOT NULL CONSTRAINT orders_customer_fk
            REFERENCES fixture.customers (customer_id) ON DELETE RESTRICT,
        order_ref text NOT NULL CONSTRAINT orders_ref_key UNIQUE,
        status text NOT NULL CONSTRAINT orders_valid_status CHECK (status IN ('open', 'paid')),
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL
    );

    CREATE TABLE fixture.order_items (
        item_id integer PRIMARY KEY CONSTRAINT order_items_positive_id CHECK (item_id > 0),
        order_id integer NOT NULL CONSTRAINT order_items_order_fk
            REFERENCES fixture.orders (order_id) ON DELETE RESTRICT,
        line_no integer NOT NULL CONSTRAINT order_items_positive_line CHECK (line_no > 0),
        sku text NOT NULL,
        quantity integer NOT NULL CONSTRAINT order_items_positive_quantity CHECK (quantity > 0),
        unit_cents integer NOT NULL CONSTRAINT order_items_nonnegative_cents CHECK (unit_cents >= 0),
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        CONSTRAINT order_items_order_line_key UNIQUE (order_id, line_no)
    );

    CREATE TABLE fixture.payments (
        payment_id integer PRIMARY KEY CONSTRAINT payments_positive_id CHECK (payment_id > 0),
        order_id integer NOT NULL CONSTRAINT payments_order_fk
            REFERENCES fixture.orders (order_id) ON DELETE RESTRICT,
        payment_ref text NOT NULL CONSTRAINT payments_ref_key UNIQUE,
        amount_cents integer NOT NULL CONSTRAINT payments_nonnegative_cents CHECK (amount_cents >= 0),
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL
    );

    CREATE TABLE fixture.scenario_receipts (
        fixture_version text COLLATE "C" NOT NULL CHECK (fixture_version ~ '^v[1-9][0-9]*$'),
        seed integer NOT NULL CHECK (seed >= 0),
        scenario_id text COLLATE "C" NOT NULL CHECK (scenario_id ~ '^S[0-9]{2}$'),
        payload_sha256 text COLLATE "C" NOT NULL CONSTRAINT scenario_receipts_sha256
            CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
        PRIMARY KEY (fixture_version, seed, scenario_id)
    );

    CREATE TABLE fixture.installation (
        schema_version integer PRIMARY KEY CHECK (schema_version = 1),
        system_identifier bigint NOT NULL,
        database_oid oid NOT NULL,
        disposable_id uuid NOT NULL
    );

    INSERT INTO fixture.installation (schema_version, system_identifier, database_oid, disposable_id)
    SELECT 1, control.system_identifier, db.oid, :'disposable_id'::uuid
    FROM pg_database AS db CROSS JOIN pg_control_system() AS control
    WHERE db.datname = current_database();

    CREATE FUNCTION fixture.cleanup(reset_intent boolean, expected_disposable_id uuid)
    RETURNS void
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, pg_temp
    AS $$
    BEGIN
        IF reset_intent IS DISTINCT FROM true THEN
            RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'fixture cleanup requires explicit reset intent';
        END IF;
        IF current_database() <> 'source_lab' OR NOT EXISTS (
            SELECT FROM fixture.installation AS installation
            JOIN pg_database AS db ON db.oid = installation.database_oid
            WHERE db.datname = current_database() AND installation.schema_version = 1
              AND installation.system_identifier = (SELECT system_identifier FROM pg_control_system())
              AND installation.disposable_id = expected_disposable_id
        ) THEN
            RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'fixture cleanup refused: disposable database identity mismatch';
        END IF;

        -- Block concurrent fixture writes through the caller's commit while permitting inspection.
        LOCK TABLE fixture.scenario_receipts, fixture.customers, fixture.orders,
            fixture.order_items, fixture.payments IN SHARE ROW EXCLUSIVE MODE;
        DELETE FROM fixture.order_items;
        DELETE FROM fixture.payments;
        DELETE FROM fixture.orders;
        DELETE FROM fixture.customers;
        DELETE FROM fixture.scenario_receipts;
    END;
    $$;

    REVOKE ALL ON FUNCTION fixture.cleanup(boolean, uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION fixture.cleanup(boolean, uuid) TO source_fixture_writer;
    GRANT USAGE ON SCHEMA fixture TO source_fixture_writer, source_fixture_reader;
    GRANT SELECT ON fixture.customers, fixture.orders, fixture.order_items, fixture.payments,
        fixture.scenario_receipts TO source_fixture_writer, source_fixture_reader;
    GRANT INSERT ON fixture.customers, fixture.orders, fixture.order_items, fixture.payments,
        fixture.scenario_receipts TO source_fixture_writer;
    GRANT UPDATE (quantity, updated_at), DELETE ON fixture.order_items TO source_fixture_writer;
\endif

COMMIT;
