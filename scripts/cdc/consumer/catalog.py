"""Read the local Bronze catalog and verify its live physical references."""

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys


HERE = Path(__file__).resolve().parent
ROOT = PurePosixPath("/var/lib/postgresql/18/docker/pg_ducklake")
DOCKER = ["docker", "--host", "unix:///var/run/docker.sock"]


def local_path(base, value, relative):
    path = PurePosixPath(value)
    if path.is_absolute() == relative or ".." in path.parts:
        raise ValueError("invalid path in catalog")
    path = base / path
    if not path.is_relative_to(ROOT):
        raise ValueError("catalog reference outside the local DuckLake root")
    return path


def inspect(container):
    query = subprocess.run(
        ["bash", str(HERE / "psql.sh"), container],
        input=(HERE / "catalog.sql").read_text(), text=True, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, check=True, timeout=12,
    )
    catalog = json.loads(query.stdout)
    if catalog["catalog_schema"] is None:
        return catalog
    for field in ("options", "tables", "inline_tables", "data_files", "delete_files"):
        if catalog[field] is not None and len(catalog[field]) > 32:
            raise ValueError(f"catalog {field} inventory exceeds 32")
    roots = [row["value"] for row in catalog["options"] if row["key"] == "data_path"]
    if len(roots) != 1 or PurePosixPath(roots[0]) != ROOT:
        raise ValueError("unexpected DuckLake root")

    resolved = {}
    for table in catalog["tables"]:
        schema = local_path(ROOT, table["schema_path"], table["schema_relative"])
        path = local_path(schema, table["table_path"], table["table_relative"])
        table["resolved_path"] = str(path)
        resolved[table["table_id"]] = path

    files = catalog["data_files"] + catalog["delete_files"]
    paths = [str(local_path(resolved[f["table_id"]], f["path"], f["path_is_relative"])) for f in files]
    if not paths:
        return catalog
    result = subprocess.run(
        DOCKER + ["exec", "--user", "postgres", container, "sh", "-ec", """
        test "$(realpath -e -- "$1")" = "$1"
        shift
        for path do
            test "$(realpath -e -- "$path")" = "$path"
            test -f "$path"
            test "$(head -c 4 -- "$path")" = PAR1
            test "$(tail -c 4 -- "$path")" = PAR1
            size=$(stat -c %s -- "$path")
            test "$size" -le 67108864
            sha=$(sha256sum < "$path")
            printf '%s %s\n' "$size" "${sha%% *}"
        done
        """, "sh", str(ROOT), *paths],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=True, timeout=10,
    )
    for file, path, line in zip(files, paths, result.stdout.splitlines(), strict=True):
        size, sha = line.split()
        if int(size) != file["file_size_bytes"]:
            raise ValueError("physical file size differs from the catalog")
        file.update(resolved_path=path, physical_size_bytes=int(size), sha256=sha, magic="PAR1")
    return catalog


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("container", help="full consumer container ID")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{64}", args.container):
        parser.error("expected the full consumer container ID")
    try:
        print(json.dumps(inspect(args.container)))
    except (KeyError, ValueError, subprocess.SubprocessError) as error:
        print(f"consumer catalog inspection failed ({type(error).__name__})", file=sys.stderr)
        sys.exit(1)
