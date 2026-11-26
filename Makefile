BASE ?= HEAD
PYTHON ?= python3
MEDIA ?=
WHITESPACE_CHECK = git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab diff --check --no-ext-diff

.PHONY: help check check-whitespace check-local-files test-unit test-integration test-cdc

help:
	@printf '%s\n' \
		'make help               List developer commands' \
		'make check              Run all repository checks' \
		'make check-whitespace   Check the index against BASE (default HEAD) and check unstaged changes' \
		'make check-local-files  Check ignore rules, indexed paths and the indexed env example' \
		'make test-unit          Run the offline unit tests' \
		'make test-integration   Run the verified disposable source gate' \
		'make test-cdc MEDIA=...  Run the two-project CDC gate in the disconnected guest'

check: check-whitespace check-local-files

check-whitespace:
	$(WHITESPACE_CHECK) --cached "$(BASE)" --
	$(WHITESPACE_CHECK) --

check-local-files:
	@set -eu; \
	for path in .env .env.local config/.env.test secrets/local.txt volumes/db/PG_VERSION \
		artifacts/run.json sample.parquet sample.duckdb sample.duckdb.wal local.pem local.key; do \
		if ! git check-ignore --quiet --no-index -- "$$path"; then \
			printf 'Expected an ignored path: %s\n' "$$path" >&2; exit 1; \
		fi; \
	done; \
	tracked=$$(git ls-files --cached --ignored --exclude-from=.gitignore); \
	if [ -n "$$tracked" ]; then \
		printf 'Tracked paths match .gitignore:\n%s\n' "$$tracked" >&2; exit 1; \
	fi
	@if ! git cat-file -e ':.env.example' 2>/dev/null; then \
		printf '%s\n' '.env.example: expected a file in the Git index' >&2; exit 1; \
	fi
	@git cat-file blob ':.env.example' | awk '/^[[:space:]]*(#|$$)/ { next } \
		/^[A-Z][A-Z0-9_]*=<replace-with-[a-z0-9-]+>$$/ { count++; next } \
		{ print ".env.example:" NR ": expected a placeholder assignment"; invalid = 1 } \
		END { if (count == 0) print ".env.example: expected at least one assignment"; exit (invalid || count == 0) }'
	@printf '%s\n' 'Local file exclusions and environment placeholders passed.'

test-unit:
	$(PYTHON) -m unittest discover -s tests/unit -v

test-integration:
	bash tests/integration/source-gate/run.sh

test-cdc:
	bash tests/integration/cdc-gate/run.sh "$(MEDIA)"
