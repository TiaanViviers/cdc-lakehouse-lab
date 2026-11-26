-- Only the fresh overlap trial installs this barrier. Writer/reader policies
-- preserve the unmodified Phase 1 runner's visibility and write contract.
CREATE FUNCTION fixture.exp017_copy_gate() RETURNS boolean
LANGUAGE plpgsql VOLATILE AS $$
BEGIN
    PERFORM pg_advisory_xact_lock_shared(17026, 1);
    RETURN true;
END;
$$;
REVOKE ALL ON FUNCTION fixture.exp017_copy_gate() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION fixture.exp017_copy_gate() TO :"publisher";
ALTER TABLE fixture.order_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE fixture.order_items FORCE ROW LEVEL SECURITY;
CREATE POLICY exp017_copy_gate ON fixture.order_items FOR SELECT TO :"publisher"
USING (fixture.exp017_copy_gate());
CREATE POLICY exp017_fixture_io ON fixture.order_items
TO source_fixture_reader, source_fixture_writer USING (true) WITH CHECK (true);
