# EXP-021 — Phase 2 closeout evidence and compatibility review

- **Date:** 2026-11-27
- **Research question IDs:** R01–R09, R13, R15, R16
- **Status:** Offline review completed. M2 unmet on recorded runtime evidence. S3 writer, independent attachment and continuous cutoff remain open.
- **Operator:** Codex
- **Git base:** `2efb64050ffffe4eb006fbe0c79f880dd89f60ca` on main, planning branch `planning/2.10-phase-2-closeout`
- **Software:** Host CPython 3.12.3. Recorded runtime stock PG16.16 and PG18.4 consumer with DuckPipe 1.0.0, pg_ducklake 0.1.0, pg_duckdb 1.1.0, DuckDB 1.5.1 and DuckLake 0.4.

## Hypothesis

The merged evidence can support exact held checkpoint convergence under the existing runtime scope while failing the full M2 gate. A format-matched client and documented writer path are independently investigable in the next phase. Establish which claims are required, observed, disproven or open before seeking approval.

## Preconditions

Use the merged repository and its checksummed synthetic excerpts, all nine Phase 2 PR discussions and their job scopes, the existing v1 oracle, and the exact public sources and image. This review uses no active lab guest or live database. [Pin provenance](EXP-020-phase-2-cdc-gate.md#artifact-identities-and-review-inputs) · [Issue #47](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/47)

## Procedure and expected results

1. Read `gh issue view 47`, merged PRs #49–57 via reviews and comments, open/closed issue and milestone inventories, and `gh project item-list 3 --owner TiaanViviers --limit 100 --format json`. Match issue and ticket IDs, merge ancestry and current board status. Confirm the candidate numbering has no collisions.
2. Verify committed hashes and compare both recorded sides for all paired checkpoints against the independent fixture. Expect six checkpoints per run, two distinct runs and no differences across 24 side-specific exports. The recorded paired command still fails retention. Review witnessed COPY independently.

   ```bash
   for record in 011 015 017 018 019 020; do
       sha256sum -c "docs/experiments/evidence/EXP-${record}.sha256" || exit 1
   done
   python3 - <<'PY'
   import json
   from pathlib import Path

   from tests.fixture_oracle import compare_checkpoint, load_expectations

   expected = load_expectations()
   records = Path("docs/experiments/evidence/EXP-020-keyed-checkpoints.jsonl")
   rows = [json.loads(line) for line in records.read_text().splitlines()]
   runs = {row["run"] for row in rows}
   assert len(runs) == 2 and len(rows) == 12
   assert {(row["run"], row["checkpoint"]) for row in rows} == {
       (run, f"S{index:02}") for run in runs for index in range(6)
   }
   for row in rows:
       for side in ("source", "target"):
           assert not compare_checkpoint(expected[row["checkpoint"]], row[side])
   print("12 checkpoints, 24 independently verified row sets, zero differences")
   PY
   ```

3. In the paired observations, compare `publisher.active-sparse` and epochs 1–3 for active slot, unchanged confirmed position, declining safe headroom and growing restart span. Compare the explicit S04 versions 12–14 against the three fixture-key visibility flags. In supplemental guests 27, 33 and 34, compare the blocked sessions before/after commit and the last order-items observation, followed by verified release and teardown.
4. Inspect the original consumer OCI archive with `python3 -m scripts.cdc.consumer.image verify /path/to/consumer.tar`, then list extension entries from the selected platform manifest's `layers` with Python `tarfile`. Verify the exact pinned source trees using `git rev-parse HEAD`. Read the SQL API, worker configuration, registration, status, snapshot copy, dispatch, apply and feedback code. Search `drain_and_wait_all\(` across the pinned tree for actual use. Verify 0.4 attach/time-travel documentation and the published versions. Check the registry's SeaweedFS tag metadata and use the DuckDB release assets and extension server to identify a candidate reader set.
5. Run `make help check BASE=origin/main`, `make test-unit`, `sh tests/repository-checks.sh` and check local Markdown links and fences. For the earlier runtime proof, follow the existing gate, COPY hold, recovery and visibility procedures referenced in the closeout. Expected outputs include the exact parity rows and the negative paired-subgate/COPY results at the documented boundaries.

## Actual observations

- On Project 3 all nine implementation issues #38–46 were Done and GitHub showed them closed. Issue #47 was open and In Progress. Phase 2 milestone #3 was open with one open issue. No existing issue or registry row used 2.11–2.13 or 3.1–3.6. Reviewed exact merge revisions and the prior blocking findings and re-reviews. [Review map](../phase-2-closeout.md#merged-record)
- All nine committed evidence checksums for EXP-011/015/017–020 matched. The independent comparison printed `12 checkpoints, 24 independently verified row sets, zero differences`; the canonical SHA-256 values matched all six recorded EXP-020 checkpoint hashes. The review left the original captured data unchanged. Guest 38's recorded Make exit was 2 with a failed paired subgate and a separate full-decision requirement. Three COPY overlap trials missed the committed item 102 within the deadline. [Keyed evidence](evidence/EXP-020-keyed-checkpoints.jsonl) · [Re-run record](evidence/EXP-020-review-rerun.json) · [COPY evidence](EXP-020-phase-2-cdc-gate.md#copy-overlap-repeats)
- Direct comparisons in the paired and supplemental JSONL confirmed both active sparse stalls with declining headroom, all six retained S04 visibility records across versions 12–14, and three identical COPY misses after the witnessed holds. Repository checks passed, all 50 offline unit tests passed, all five repository regression controls passed, and local Markdown links and fences resolved.
- The existing consumer archive verified to the exact index, linux/amd64 manifest and config already recorded in EXP-020. The archive checksum was `91185421b787b82476b65f32abb02f3ae15ae01956214b4b5a12fea87a2fa38c`. The platform layers contain `usr/lib/postgresql/18/lib/ducklake.duckdb_extension`, `libduckdb.so`, `pg_duckdb.so` and `pg_ducklake.so` in the same library directory. No separate httpfs or postgres_scanner extension file appeared in that inventory. The build config includes both as source dependencies. Runtime module availability in each worker/native path still needs testing. [Image pin and build](../phase-3-storage-strategy.md#pin-the-writer-and-reader-separately)
- Upstream sources were checked on 2026-11-27. The SeaweedFS 4.55 GitHub tag and Docker Hub index/platform member matched the draft. The DuckDB 1.5.1 release API reports the CLI archive checksum below. The three DuckDB extension URLs under `https://extensions.duckdb.org/v1.5.1/linux_amd64/` returned HTTP 200 and valid gzip with matching engine/platform strings. The filename `postgres.duckdb_extension.gz` returned 404. Use `postgres_scanner` for the staged artifact. No client was installed or attached in this review. [DuckDB release assets](https://github.com/duckdb/duckdb/releases/tag/v1.5.1) · [SeaweedFS registry metadata](https://hub.docker.com/v2/repositories/chrislusf/seaweedfs/tags/4.55/)

| Candidate artifact | SHA-256 | Evidence |
| --- | --- | --- |
| `duckdb_cli-linux-amd64.zip` | `7414b29d4e77ae833ff170a489a59b74331f96d3fde72aa3bb8437dedbcea180` | [GitHub release API](https://api.github.com/repos/duckdb/duckdb/releases/tags/v1.5.1), archive digest metadata |
| `ducklake.duckdb_extension.gz` | `4931a0aab0cd39245c22fcd038a1fe066a8b28a44fc1ec932eedd0bf41ee014c` | [Official 1.5.1 artifact](https://extensions.duckdb.org/v1.5.1/linux_amd64/ducklake.duckdb_extension.gz), downloaded digest, footer build `67480b1d` |
| `postgres_scanner.duckdb_extension.gz` | `b411f227c5fd1b4392645990875737bacc95a2e656b89ea600df01a9063f319d` | [Official 1.5.1 artifact](https://extensions.duckdb.org/v1.5.1/linux_amd64/postgres_scanner.duckdb_extension.gz), downloaded digest, footer build `c0e9256` |
| `httpfs.duckdb_extension.gz` | `1d7ab919f579892bd708770072c3439d2c03f4d15916939a40c3a4a96d2679ad` | [Official 1.5.1 artifact](https://extensions.duckdb.org/v1.5.1/linux_amd64/httpfs.duckdb_extension.gz), downloaded digest, footer build `7e86e7a` |

The pinned source review located per-table batching, the separate metrics update, oldest tracked feedback, per-table COPY and source commit handling. The public API search found no live transaction-completion mechanism. The internal drain helper has no source call site in the pinned tree. The file path setting and credential loader lead to a credible Phase 3 probe with distinct authorization and runtime checks. [Cutoff source review](../bronze-snapshot-cutoffs.md#positions-and-guarantees) · [Writer path proposal](../phase-3-storage-strategy.md#prove-the-actual-writer-path-early)

## Evidence artifacts

Use the linked committed excerpts and reviewer comments. The closeout's independent checks used the excerpts, the original staged consumer media and public upstream files. Guest/physical file evidence at runtime comes from the merged experiments. [Evidence index](EXP-020-phase-2-cdc-gate.md#evidence-artifacts)

## Interpretation

M2 remains unmet because normal sparse feedback and repeated concurrent COPY have separate failed mandatory outcomes. The recorded partial Bronze states answer the weaker characterization requirement and leave continuous-source safe cutoffs open. Format matching, credentials and API coverage can be investigated separately. A compatibility probe cannot establish a positive M2 or M3.

## Limitations and follow-up

The offline review did not run new guest schedules, attach a reader, test object writes or rehearse migration. The pinned code narrows the plausible COPY failure paths without attributing the missed decoded change. Approval is pending for corrective work, any early compatibility probe and eventual Phase 3 publication. [Corrective backlog](../../backlog/phase-2-corrections.md) · [Draft Phase 3 backlog](../../backlog/phase-3.md)
