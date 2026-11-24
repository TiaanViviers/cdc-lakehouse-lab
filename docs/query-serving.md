# Query-serving research contract — Phase 5

## Why a separate service?

DuckLake stores logical tables as catalog metadata plus data files. Neither PostgreSQL **catalog metadata alone** nor S3 is an external SQL-serving endpoint. Reporting tools need an authenticated, bounded query service with sufficient CPU/memory, SQL protocol compatibility and controlled access to **both** catalog and Gold Parquet data.

## Proposed experiment topology

1. Independent reporting client (`psql`, Python PostgreSQL driver and/or lightweight synthetic BI-style query).
2. Dedicated **logical reporting SQL service**: self-managed PostgreSQL + `pg_ducklake` on a separate Docker service/host, using the documented remote DuckLake catalog/FDW approach where feasible.
3. CDC/catalog PostgreSQL containing DuckLake metadata, and S3-compatible lake bucket containing Parquet.
4. Independent DuckDB client as query correctness oracle.

**Two distinct PostgreSQL roles:** metadata catalog != client query-serving instance. Both may be on one EC2 for the first bootstrap experiment but must be separable for the target proof.

AWS RDS PostgreSQL is a possible **catalog metadata** backend; do not assume a custom `pg_ducklake` extension can be installed on standard RDS. Check supported extensions at the selected release. `pg_ducklake` is a young extension; industry adoption and load characteristics require research.

## Minimum demonstration

- Client connects using the PostgreSQL wire protocol and queries a Gold Reporting table; compare returned values with independent DuckDB query over the same snapshot.
- Show query service accessing **catalog** metadata and **S3** data as separate connections.
- Demonstrate at least one read-only role, restricted schema access, credentials not in source, and absence of unrestricted public exposure.
- Test multiple concurrent clients with a reproducible small workload, observe latency (p50/p95), errors, CPU/memory, catalog connections and S3 activity. The local PoC does not imply production throughput.
- Simulate reporting service restart; Gold files and catalog remain intact; measure reconnect/recovery.
- Test expected behaviour when catalog is unavailable vs object storage unavailable.
- Report SQL/driver incompatibilities, FDW limitations, snapshot visibility and whether DuckDB-native serving merits comparison.

## Decision gate

Pass when a separate service can serve correct query results with documented security and measurement. If `pg_ducklake` cannot support the use case, record negative evidence and an ADR comparing alternatives (DuckDB-native, other OLAP serving). **Do not silently replace the selected candidate.**

## References

- https://github.com/relytcloud/pg_ducklake/blob/main/pg_ducklake/docs/foreign_data_wrapper.md
- https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.FeatureSupport.Extensions.html
- https://ducklake.select/docs/stable/
