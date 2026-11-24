BASE ?= HEAD

.PHONY: help check check-whitespace check-local-files

help:
	@printf '%s\n' \
		'make help               List developer commands' \
		'make check              Run all repository checks' \
		'make check-whitespace   Check changes against BASE (default HEAD)' \
		'make check-local-files  Check ignore rules, tracked paths and the env example'

check: check-whitespace check-local-files

check-whitespace:
	git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab diff --check --no-ext-diff "$(BASE)" --

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
	@awk '/^[[:space:]]*(#|$$)/ { next } \
		/^[A-Z][A-Z0-9_]*=<replace-with-[a-z0-9-]+>$$/ { count++; next } \
		{ print ".env.example:" NR ": expected a placeholder assignment"; invalid = 1 } \
		END { if (count == 0) print ".env.example: expected at least one assignment"; exit (invalid || count == 0) }' .env.example
	@printf '%s\n' 'Local file exclusions and environment placeholders passed.'
