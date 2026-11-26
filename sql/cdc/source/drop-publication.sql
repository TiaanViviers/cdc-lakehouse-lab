BEGIN;
SELECT EXISTS (
    SELECT FROM pg_publication AS p
    JOIN pg_roles AS r ON r.oid = p.pubowner
    WHERE p.pubname = :'publication' AND p.oid = :'created_publication_oid'::oid
      AND r.rolname = :'publisher'
      AND NOT p.puballtables AND NOT p.pubviaroot
      AND p.pubinsert AND p.pubupdate AND p.pubdelete AND p.pubtruncate
      AND NOT EXISTS (SELECT FROM pg_publication_namespace WHERE pnpubid = p.oid)
      AND ARRAY(
          SELECT schemaname || '.' || tablename
          FROM pg_publication_tables WHERE pubname = p.pubname ORDER BY 1
      ) = ARRAY['fixture.customers', 'fixture.order_items', 'fixture.orders', 'fixture.payments']
      AND NOT EXISTS (
          SELECT FROM pg_publication_rel
          WHERE prpubid = p.oid AND (prattrs IS NOT NULL OR prqual IS NOT NULL)
      )
      AND NOT EXISTS (SELECT FROM pg_replication_slots)
) AS expected_publication \gset
\if :expected_publication
    DROP PUBLICATION :"publication";
\else
    DO $$ BEGIN RAISE EXCEPTION 'refusing publication drop: unexpected identity, definition or remaining slot'; END $$;
\endif
COMMIT;
