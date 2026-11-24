# Local development and engineering guidelines

## Repository validation

From the repository root, use Git, GNU Make, a POSIX shell and its standard tools (including `awk`). The checks run offline and require no Python packages, Docker or environment file.

```sh
make help
make check
```

Stage new files before validation so Git includes them. `make check` runs two targets:

- `make check-whitespace` checks added lines for Git whitespace errors. It compares tracked working-tree content against `HEAD` by default. Run `make check BASE=origin/main` after fetching `main` to include your committed branch changes.
- `make check-local-files` checks representative ignored paths, rejects tracked files that match the repository's ignore rules, and requires every assignment in `.env.example` to use a placeholder of the form `<replace-with-name>`. Review the staged diff for credentials and generated data under other names.

The [Repository checks workflow](../.github/workflows/repository-checks.yml) runs `make help check` on pull requests to `main`. It checks the proposed merge against the pull request's base commit. Unit and integration checks are planned as described below.

### Ticket 0.5 validation record

Verified on 2026-11-24 against the [GNU Make manual](https://www.gnu.org/software/make/manual/html_node/Phony-Targets.html), [Git ignore rules](https://git-scm.com/docs/gitignore), [Git diff options](https://git-scm.com/docs/git-diff), [GitHub Actions syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax), and [Ubuntu 24.04 runner software](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md). The workflow uses [checkout v6.0.3](https://github.com/actions/checkout/releases/tag/v6.0.3), pinned to its release commit.

Observed locally with Git 2.43.0 and GNU Make 4.3:

- `make` and `make help` listed the four developer commands. `make check` and `make help check BASE=origin/main` passed both repository checks.
- `git check-ignore -v --no-index .env config/.env.test volumes/source/PG_VERSION artifacts/run.parquet` identified the repository rules for all four paths. `git ls-files --error-unmatch .env.example` confirmed that the template was tracked.
- In a disposable Git repository, the checks rejected trailing whitespace, a force-staged Parquet file and a sample environment assignment with a non-placeholder value.

See the ticket 0.5 pull request for the hosted run and its logs.

## Planned runtime host

Ubuntu/Linux Docker Engine + Docker Compose v2, Python 3, Git. Start with a laptop-sized configuration (~16 GB RAM). Use one Windmill worker initially and small fixtures; don't enable all services before prerequisites are validated.

## Proposed environment profiles

- `source`: PostgreSQL 16, generator, source SQL inspection.
- `cdc`: DuckPipe-compatible PostgreSQL image and extension configuration.
- `storage`: S3-compatible service with a browser object console.
- `windmill`: Windmill server, scheduler/queue/state PostgreSQL, single worker.
- `reporting`: logically independent PostgreSQL-compatible SQL serving process, catalog/S3 connectivity, synthetic SQL clients.
- `requests`: request API, independent request PostgreSQL, controlled write-back service.
- `batches`: separate S3-compatible operational bucket/namespace, storing prepared CSV/Parquet results.
- `observe`: optional pgAdmin or equivalent, custom diagnostics/dashboard.

These are **planned service groups**, not implemented commands. Compose file/images/ports must be proven and documented in implementation issues.

## Human-first debugging

1. Query source tables and `pg_replication_slots` on the source.
2. Inspect DuckPipe's version-specific status API or SQL views on CDC host.
3. Inspect catalog metadata, snapshots and Parquet objects through independent interfaces.
4. Query Bronze from independent DuckDB.
5. Open Windmill's run view: inspect input, worker logs, pipeline materialisation and failures.
6. Query Gold from an **independent PostgreSQL-compatible reporting endpoint**, verifying both catalog metadata and object-store reads.
7. Inspect durable request statuses, immutable operational S3 artifacts, write-back receipts and the corresponding source records.
8. Query final Gold and validate expected fixture results.

Do not confuse a running container, acknowledged WAL position, presence of an S3 file or successful Windmill status with end-to-end correctness.

## Observability design

Start with pgAdmin (source + CDC/catalog + request DB), storage object console (both buckets), SQL-service client logs, Windmill UI and `docker compose logs` / `docker stats`. Later prototype a lightweight Streamlit dashboard aggregating source state, DuckPipe status, record-level parity, source-to-Gold timestamps and job run IDs. Do not imply that a dashboard proves multi-table snapshot consistency.

## Reproducibility

- Pin compatible images and Python dependencies; record upstream URLs/dates.
- Use fixed random seed and fixture scenario IDs; keep input and expected outputs versioned as small synthetic files.
- Avoid unbounded concurrency or generating millions of rows on a laptop.
- Test idempotent reset and cleanup using explicitly named disposable volumes; warn before data destruction.
- Keep `.env.example` as a placeholder-only reference. Runtime tickets will document which variables their services consume and when to create a local `.env`.
- Store disposable secrets under `secrets/` or in ignored local environment files. Keep services in named Docker volumes as specified in the [local runtime design](local-runtime-design.md). Put local volume exports under `volumes/` and generated experiment outputs under `artifacts/`. Commit only small intentional synthetic inputs and expected results, plus redacted evidence in experiment records.
- Prefer versioned SQL initialization scripts and documented migration paths rather than hand-edited databases.

## Version compatibility checkpoint

Before coding, independently verify: PG source WAL settings; DuckPipe PG host supported version and remote source support; pg_ducklake required extension dependencies; S3-compatible service compatibility; DuckDB DuckLake extension catalog URI syntax; Windmill release/edition and Pipeline feature availability. Record versions in an ADR or experiment, and do not copy untested snippets from old chat discussions.

## Test hierarchy

When the first testable code lands, put service-free tests under `tests/unit/` and add a `make test-unit` target to CI. Put service-dependent tests under `tests/integration/` and add an explicit `make test-integration` target when the relevant disposable local profile and its prerequisites are available. Document exact commands and fixture expectations in the tickets that add those suites.

- Unit: generator input/output, deterministic event sequence.
- Integration: source to CDC, catalog to object store, independent DuckDB read, Windmill to lake, remote SQL endpoint to catalog/S3, request API to request DB to S3 to write-back.
- Invariant: row-level data equality, updates/deletions, expected aggregated results.
- Failure: stopped CDC, replay, delayed flush, killed transformation worker, reporting service/catalog/S3 outage, source outage during write-back, crash after commit before acknowledgement.
- Benchmarks: lag, sizes, memory, CPU, runtime (measurement, not premature acceptance thresholds).

## Development workflow

Start each approved ticket on a dedicated branch from current `main`. Run the repository checks and inspect the staged diff before pushing. Open a focused PR against `main` with the stable ticket ID, GitHub issue link, exact commands, observed results and relevant research questions. Leave merging to the maintainer after review and validation. Follow the [project management conventions](project-management.md) for board status and phase milestones.

## Logical deployment vs physical AWS

Docker services simulate independent EC2 runtime/trust boundaries. A separate reporting SQL service and asynchronous processing system are **required logical PoC components**, but they do **not** require actual separate AWS EC2 instances on the local host. Windmill analytical and operational workers may be different groups on the same Windmill runtime. Document any intentional physical colocation.

A single local S3-compatible storage server can host **two distinct buckets** (DuckLake Parquet vs operational batch artifacts). Keep permissions/paths distinct. Database roles are separate: source, DuckPipe/catalog, Windmill state, query-serving, and operational requests. Do not mix operational pending-job writes into catalog metadata.

## Synthetic end-to-end scenarios

- Source order mutation → DuckPipe → Bronze → Silver/Gold → PostgreSQL reporting SQL endpoint.
- A client submits a synthetic token-generation request while the source is offline; worker persists prepared output and request status; source returns; write-back commits once; source CDC reflects the commit to Bronze.
- Crash after source commits but before request DB acknowledgement; retry verifies source-side batch receipt and does not duplicate output.
- Query-serving service restarted without modifying the lake or catalog; clients reconnect and obtain correct Gold values.

Follow [phase definitions](roadmap.md), [issue numbering](issue-conventions.md), [query-serving](query-serving.md), and [asynchronous processing](async-processing.md).
