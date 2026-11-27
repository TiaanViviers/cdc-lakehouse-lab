#!/usr/bin/env bash
# Run on the staging host, outside the guest and without a Docker daemon.
set -euo pipefail
suite=$(cd "$(dirname "$0")" && pwd)
repo=$(realpath "$suite/../../../..")
upstream=$(realpath "${1:?local upstream worktree after applying the selected patch series}")
image=$(realpath "${2:?pinned consumer OCI tar}")
base=$(realpath -m "${3:?dedicated build output directory}")
mkdir -p "$base"
git -C "$upstream" merge-base --is-ancestor 86d5c248d80370fb2e10ddc1abd780fd94c3a52b HEAD
test -z "$(git -C "$upstream" status --porcelain)"
export PGRX_PG_CONFIG_PATH="$base/pg_config"
export CARGO_TARGET_DIR="$base/target" DUCKDB_LIB_DIR="$base" LD_LIBRARY_PATH="$base" LIBRARY_PATH="$base"
export LIBCLANG_PATH=/usr/lib/llvm-18/lib
export CFLAGS="-isystem $base/libc6-dev/usr/include -isystem $base/libc6-dev/usr/include/x86_64-linux-gnu"
(
    cd "$base"
    curl -fLsS --retry 2 'https://apt-archive.postgresql.org/pub/repos/apt/pool/main/p/postgresql-18/postgresql-server-dev-18_18.4-1.pgdg12+1_amd64.deb' -o pg18-dev.deb
    curl -fLsS --retry 2 'https://deb.debian.org/debian/pool/main/g/glibc/libc6-dev_2.36-9+deb12u14_amd64.deb' -o libc6-dev.deb
    sha256sum -c <<'SUMS'
bb45f27f6072e8109b9a67e390ff0139ab493f681ec05d1cfed139b101187c00  pg18-dev.deb
0218fc2befcd784c1b0c6292c0a137ce89fad054efaa579ad083bee0f2c01aae  libc6-dev.deb
SUMS
    dpkg-deb -x pg18-dev.deb pg18-dev
    dpkg-deb -x libc6-dev.deb libc6-dev
)
PYTHONPATH="$repo" python3 "$suite/extract.py" "$image" "$base"
cat > "$PGRX_PG_CONFIG_PATH" <<'PGCONFIG'
#!/bin/bash
set -euo pipefail
base=$(dirname "$(realpath "$0")")
case "${1:-}" in
    --includedir-server) echo "$base/pg18-dev/usr/include/postgresql/18/server" ;;
    *) exec "$base/pg_config.real" "$@" ;;
esac
PGCONFIG
chmod 0755 "$PGRX_PG_CONFIG_PATH"
test "$("$PGRX_PG_CONFIG_PATH" --version)" = 'PostgreSQL 18.4 (Debian 18.4-1.pgdg12+1)'
cd "$upstream"
git rev-parse HEAD
sha256sum Cargo.lock
cargo +1.95.0 fmt --all --check
cargo +1.95.0 build --locked --jobs 5 --release -p pg_duckpipe --lib
library="$CARGO_TARGET_DIR/release/libpg_duckpipe.so"
max_glibc=$(readelf --version-info "$library" | awk '/Name: GLIBC_[0-9]/ { print $3 }' | sort -Vu | tail -1)
test -n "$max_glibc"
test "$(printf '%s\n' "$max_glibc" GLIBC_2.36 | sort -V | tail -1)" = GLIBC_2.36
if git log -1 --format=%s | grep -Fxq 'Use pgoutput commit position for COPY catch-up admission'; then
    cargo +1.95.0 test --locked --jobs 5 --release -p duckpipe-core --lib copy_boundary_tests
fi
install -m 0644 "$library" "$base/pg_duckpipe.so"
sha256sum "$base/pg_duckpipe.so"
