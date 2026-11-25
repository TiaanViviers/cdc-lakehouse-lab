FROM docker.io/library/python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
WORKDIR /app
ENV PSYCOPG_IMPL=binary
COPY scripts/source/runner.requirements.txt .
RUN python -m pip install --disable-pip-version-check --no-cache-dir --only-binary=:all: \
    --require-hashes -r runner.requirements.txt && python -m pip check
COPY scripts/source/*.py scripts/source/
COPY tests/__init__.py tests/fixture_oracle.py tests/
COPY tests/fixtures/v1/expected.json tests/fixtures/v1/
ENTRYPOINT ["timeout", "--kill-after=2s", "45s", "python", "-B", "-m", "scripts.source.runner"]
