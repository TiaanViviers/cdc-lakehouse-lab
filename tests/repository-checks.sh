#!/bin/sh
set -eu
unset BASE

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
repo=$(mktemp -d)
trap 'rm -rf -- "$repo"' EXIT
cd "$repo"

git init -q
git config user.name 'Repository checks test'
git config user.email 'repository-checks@example.invalid'
cp "$root/Makefile" "$root/.gitignore" "$root/.env.example" .
printf '# Fixture\n' > README.md
git add -- Makefile .gitignore .env.example README.md
git -c commit.gpgsign=false commit -qm 'Add clean fixtures'
base=$(git rev-parse HEAD)

expect_failure() {
    label=$1
    expected=$2
    shift 2
    if output=$(make check "$@" 2>&1); then
        printf 'FAIL %s (make check succeeded)\n' "$label" >&2
        return 1
    fi
    if ! printf '%s\n' "$output" | grep -Fq -- "$expected"; then
        printf 'FAIL %s (missing diagnostic: %s)\n%s\n' "$label" "$expected" "$output" >&2
        return 1
    fi
    printf 'PASS %s\n' "$label"
}

make check

printf 'SOURCE_DB_PASSWORD=synthetic-invalid-value\n' > .env.example
git add -- .env.example
git restore --worktree --source=HEAD -- .env.example
expect_failure 'staged non-placeholder with clean working tree' \
    '.env.example:1: expected a placeholder assignment'
git restore --staged -- .env.example

printf '# Fixture\nChanged line \n' > README.md
git add -- README.md
git restore --worktree --source=HEAD -- README.md
expect_failure 'staged trailing whitespace with clean working tree' \
    'README.md:2: trailing whitespace.'
git restore --staged -- README.md

git rm -q --cached -- .env.example
expect_failure 'staged template deletion with untracked replacement' \
    '.env.example: expected a file in the Git index'
git restore --staged -- .env.example

printf '# Fixture\nChanged line \n' > README.md
expect_failure 'unstaged trailing whitespace' 'README.md:2: trailing whitespace.'
git add -- README.md
git -c commit.gpgsign=false commit -qm 'Add committed whitespace fixture'
make check
expect_failure 'committed trailing whitespace against explicit BASE' \
    'README.md:2: trailing whitespace.' "BASE=$base"
