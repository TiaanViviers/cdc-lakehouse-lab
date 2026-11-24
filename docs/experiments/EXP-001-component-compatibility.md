# EXP-001 — Component compatibility evidence review

- **Date** 2026-11-24
- **Research question IDs** R01, R06, R07, R09, R10, R11, R17, R22
- **Status** Documentation and artifact inspection completed. Runtime hypotheses pending.
- **Operator** Codex
- **Branch** `research/0.1-component-compatibility`
- **Software and image versions** [Compatibility matrix](../compatibility-matrix.md). Metadata inspected with GitHub CLI 2.45.0, curl 8.5.0 and Docker CLI 29.1.3.

## Hypothesis

A public, digest-pinned DuckPipe build can serve as the first remote PG16 test candidate. The build dependency and catalog format determine which downstream clients can attach to the same lake.

## Preconditions

Use public repository and registry metadata. The first runtime experiment will use a disposable source and consumer on an isolated local network with one small deterministic table. Ticket 0.1 covers source and artifact inspection.

## Procedure

1. Check upstream refs and the standalone release assets.

   ```bash
   git ls-remote https://github.com/relytcloud/pg_duckpipe.git HEAD 'refs/tags/*'
   git ls-remote https://github.com/relytcloud/pg_ducklake.git refs/tags/v1.0.3
   gh api repos/relytcloud/pg_ducklake/releases/tags/v1.0.3 \
     --jq '{tag_name,published_at,assets:[.assets[].name]}'
   ```

2. Read the Dockerfile and the catalog initializer at the pinned dependency. Compare with the standalone release's submodule and inspect build history.

   ```bash
   pipe=86d5c248d80370fb2e10ddc1abd780fd94c3a52b
   lake=20d799e673639fb0c36a3b31db413e45057a10ed
   curl -fsSL "https://raw.githubusercontent.com/relytcloud/pg_duckpipe/$pipe/docker/Dockerfile" |
     rg 'PG_VERSION=|PGDUCKLAKE_COMMIT=|shared_preload_libraries'
   curl -fsSL "https://raw.githubusercontent.com/relytcloud/pg_ducklake/$lake/third_party/ducklake/src/storage/ducklake_initializer.cpp" |
     rg 'version !=|catalog version'
   gh api 'repos/relytcloud/pg_ducklake/git/trees/v1.0.3?recursive=1' \
     --jq '.tree[] | select(.mode=="160000") | [.path,.sha] | @tsv'
   serving_lake=93cc490d9b5554f6fd5322dbef23f41d4fa91bb8
   curl -fsSL "https://raw.githubusercontent.com/duckdb/ducklake/$serving_lake/src/storage/ducklake_initializer.cpp" |
     rg 'version !=|catalog version'
   gh api 'repos/relytcloud/pg_duckpipe/actions/runs/26499999069/jobs' \
     --jq '.jobs[] | [.name,.conclusion] | @tsv'
   gh api 'repos/relytcloud/pg_duckpipe/actions/runs/45203850543' \
     --jq '{head_sha,created_at,conclusion}'
   ```

3. Inspect the Docker Hub tag records and the Windmill GHCR manifest. Check package versions and Python requirements in PyPI.

   ```bash
   for ref in library/postgres:16.16-bookworm library/postgres:18.7-bookworm \
       library/postgres:18.7-trixie library/python:3.14.10-slim-trixie \
       chrislusf/seaweedfs:4.55 pgducklake/pipe-ci-builds:18-$pipe \
       pgducklake/pgduckpipe:18-main pgducklake/pgducklake:18-v1.0.3 \
       pgducklake/pgducklake:18-1.0.3 pgducklake/pgducklake:18-main
   do
     curl -sS "https://hub.docker.com/v2/repositories/${ref%:*}/tags/${ref#*:}/" |
       jq -c '{name,digest,last_updated,message,platforms:[.images[]? | select(.os=="linux") | .architecture] | unique}'
   done
   wm_registry=ghcr.io
   wm_repo=windmill-labs/windmill
   wm_registry_token=$(curl -fsSL "https://$wm_registry/token?scope=repository:$wm_repo:pull" | jq -r .token)
   curl -fsSI -H "Authorization: Bearer $wm_registry_token" \
     -H 'Accept: application/vnd.oci.image.index.v1+json' \
     "https://$wm_registry/v2/$wm_repo/manifests/1.883.0" | rg -i '^(HTTP/|docker-content-digest:)'
   curl -fsSL -H "Authorization: Bearer $wm_registry_token" \
     -H 'Accept: application/vnd.oci.image.index.v1+json' \
     "https://$wm_registry/v2/$wm_repo/manifests/1.883.0" |
     jq -c '[.manifests[]?.platform | select(.os=="linux") | .architecture] | unique'
   for spec in duckdb/1.5.1 duckdb/1.5.6 fastapi/0.165.0 uvicorn/0.54.0 psycopg/3.3.9 psycopg-binary/3.3.9
   do
     curl -fsSL "https://pypi.org/pypi/$spec/json" |
       jq -c '{package:(.info | {name,version,requires_python,license_expression}), cp314_linux:[.urls[].filename | select(contains("cp314-cp314-manylinux"))]}'
   done
   for arch in linux_amd64 linux_arm64
   do
     for ext in ducklake postgres_scanner httpfs
     do
       printf '%s/%s ' "$arch" "$ext"
       curl -fsSI "https://extensions.duckdb.org/v1.5.1/$arch/$ext.duckdb_extension.gz" |
         rg '^HTTP/' | tail -1
     done
   done
   ```

4. For the DuckPipe image, use the amd64 member manifest's config to confirm the embedded PostgreSQL package version.

   ```bash
   pipe_repo=pgducklake/pipe-ci-builds
   pipe_registry_token=$(curl -fsSL "https://auth.docker.io/token?service=registry.docker.io&scope=repository:$pipe_repo:pull" | jq -r .token)
   pipe_member=sha256:de0a9036fd11a75eaff23508209c2cea675d081aecea51f60cdca78c0802a5a6
   pipe_config=$(curl -fsSL -H "Authorization: Bearer $pipe_registry_token" \
     -H 'Accept: application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' \
     "https://registry-1.docker.io/v2/$pipe_repo/manifests/$pipe_member" | jq -r .config.digest)
   curl -fsSL -H "Authorization: Bearer $pipe_registry_token" \
     "https://registry-1.docker.io/v2/$pipe_repo/blobs/$pipe_config" |
     jq '{architecture,created,pg:[.config.Env[] | select(startswith("PG_"))]}'
   ```

## Expected results

The Git refs, build configuration and image records identify the same candidate source and artifact. Format requirements are visible in source even when standalone and bundled extension version numbers differ. Each selected image has a digest or an explicit source-build fallback.

## Actual observations

- `git ls-remote` returned a DuckPipe HEAD and zero tag refs. The standalone v1.0.3 release resolved to `9fef142965aa4af3e9da17be7ce210ed90f12ed6`, was published 2026-10-19, and exposed an empty release asset list.
- The DuckPipe tag returned index `sha256:091236d2acecfec1216817aff6e43dc4c036159cebe44a19c73c95c1fe9be348` for amd64 and arm64. The moving `pgducklake/pgduckpipe:18-main` tag resolved to the same index at review time. The amd64 config gave `PG_MAJOR=18`, `PG_VERSION=18.4-1.pgdg12+1`, and a build time of 2026-05-27 10:01 UTC. The registry's last update for the commit tag was 2026-05-27 10:07 UTC, consistent with the successful May workflow. The 2026-11-23 scheduled workflow on the same commit failed, with image merges skipped.
- The Dockerfile's pinned DuckLake initializer requires format `0.4`. The v1.0.3 release's DuckLake submodule initializer requires `1.0`. Current DuckLake migration docs require migrating pre-1.0 catalogs before opening them with the 1.1-capable extension, including read-only use. This comparison predicts a downstream attach failure with the old catalog and migration disabled.
- Docker Hub returned 404 for `pgducklake/pgducklake:18-v1.0.3` and `18-1.0.3`. The documented moving tag `18-main` returned index `sha256:1985a9feebab7af08b118d8c8cce04310af43bfc319d012c78e5141716f2da86`. Anonymous GHCR token retrieval for the standalone CI package returned 401 here. The candidate therefore uses the v1.0.3 source pin.
- GHCR returned HTTP 200 and the image digest recorded in the matrix for Windmill `1.883.0`, with amd64 and arm64 manifest entries. The spelling `v1.883.0` returned HTTP 404. Package metadata confirmed the selected Python package versions and CPython 3.14 Linux wheels on amd64 and arm64 for `psycopg-binary` and the matching DuckDB 1.5.1 candidate.
- The DuckDB extension repository returned HTTP 200 for all six pinned 1.5.1 artifact URLs. The `postgres` SQL extension is published under the `postgres_scanner` filename. [DuckDB PostgreSQL extension documentation](https://duckdb.org/docs/1.5/core_extensions/postgres/overview)
- The new documentation's relative links, whitespace, seven component rows and seven image digests passed local checks. The reproduction commands above ran against the public sources.

## Evidence artifacts

[Compatibility matrix](../compatibility-matrix.md) · [Successful May build](https://github.com/relytcloud/pg_duckpipe/actions/runs/26499999069) · [Failed November build](https://github.com/relytcloud/pg_duckpipe/actions/runs/45203850543) · [DuckLake migration documentation](https://ducklake.select/docs/stable/duckdb/migrations/upgrading_to_ducklake_1_1)

## Interpretation

The registry exposes a concrete input for the first CDC smoke test. The standalone serving tag and the bundled CDC dependency come from different revisions with different expected catalog formats. A current-format all-component deployment is still a hypothesis.

## Limitations and confounders

Checks covered public metadata and source files. Container startup, extension loading, publication grants, WAL capture, row parity, catalog attachment, object reads/writes, Pipeline behavior, FDW access and request durability await their runtime phases. This shell's Docker CLI lacked Buildx, so registry metadata was queried directly. The old CDC image is suitable only as an isolated research candidate pending startup and package review. Pin and inspect the full build inputs before relying on a rebuild.

## Follow-up action

Phase 2 should record the actual `pg_extension` versions and metadata format, source slot and publication, DuckPipe status, and exact source/target row values for a seeded row and committed insert/update/delete. Preserve unexpected grants, errors and slot retention evidence. Only advance to S3 and shared readers after the baseline is understood. The acceptance conditions for the linked research questions stay open.
