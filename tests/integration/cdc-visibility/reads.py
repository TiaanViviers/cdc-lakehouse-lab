"""Read the selected lake through the pinned consumer, never through inline storage tables."""

import csv
import io
import json
import os
import select
import subprocess
import time
from itertools import chain

from scripts.cdc.parity import COLUMNS, ROW_LIMIT, fixture_rows
from scripts.cdc.parity.psql import select_rows
from tests.fixture_oracle import PRIMARY_KEYS

TARGET = {table: ("bronze", table) for table in COLUMNS}
BEGIN = """
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL idle_in_transaction_session_timeout = '25s';
SET LOCAL TIME ZONE 'UTC';
SET LOCAL DateStyle = 'ISO, YMD';
"""
PG_IDENTITY = """
SELECT json_build_object('backend_pid', pg_backend_pid(),
    'pg_snapshot', pg_current_snapshot()::text, 'catalog_head',
    (SELECT max(snapshot_id) FROM ducklake.ducklake_snapshot));
"""
END_CAPTURE = "@@end-of-capture"
OUTPUT_LIMIT = 262144


def duckdb_select(query):
    return f"SELECT * FROM duckdb.query($ducklake$ {query} $ducklake$);"


def engine_capture(version=None):
    """One DuckDB statement touches all four relations and the snapshot function."""
    if version is not None and (type(version) is not int or version < 0):
        raise ValueError("snapshot ID must be a nonnegative integer")
    qualifier = "" if version is None else f" AT (VERSION => {version})"
    tables = []
    for table, columns in COLUMNS.items():
        key = PRIMARY_KEYS[table]
        tables.append(f"""'{table}', (
            SELECT coalesce(to_json(list(t ORDER BY "{key}")), '[]'::JSON)
            FROM (SELECT {", ".join(columns)} FROM pgducklake.bronze."{table}"{qualifier}
                  ORDER BY "{key}" LIMIT {ROW_LIMIT + 1}) AS t
        )""")
    return duckdb_select(f"""
        SELECT CAST(json_object(
            'engine_snapshot', (SELECT id FROM ducklake_current_snapshot('pgducklake')),
            'requested_version', {version if version is not None else "NULL"},
            'rows', json_object({", ".join(tables)})
        ) AS VARCHAR) AS observation
    """)


def engine_identity():
    return duckdb_select("SELECT id FROM ducklake_current_snapshot('pgducklake')")


def native_capture():
    sql = [PG_IDENTITY, engine_identity(), "\\pset format csv", "\\pset tuples_only off"]
    for table, columns in COLUMNS.items():
        sql.extend((f"\\echo @@{table}", select_rows(TARGET[table], columns, PRIMARY_KEYS[table])))
    sql.extend(("\\pset format unaligned", "\\pset tuples_only on", engine_identity(), PG_IDENTITY))
    return "\n".join(sql)


def decode_native(lines):
    before, first_id, *relations, last_id, after = lines
    records = iter(csv.reader(io.StringIO("\n".join(relations)), strict=True))
    raw = {}
    for table, columns in COLUMNS.items():
        if next(records, None) != [f"@@{table}"] or next(records, None) != list(columns):
            raise RuntimeError(f"unexpected native projection for {table}")
        raw[table] = []
        # Stop on the next marker without consuming it for the next relation.
        for record in records:
            if len(record) == 1 and record[0].startswith("@@"):
                records = chain((record,), records)
                break
            raw[table].append(dict(zip(columns, record, strict=True)))
    if next(records, None) is not None:
        raise RuntimeError("unexpected trailing native projection")
    return dict(rows=fixture_rows(raw), pg_before=json.loads(before), pg_after=json.loads(after),
                engine_before=int(first_id), engine_after=int(last_id))


def decode_engine(lines, requested):
    (line,) = lines
    result = json.loads(line)
    snapshot = result["engine_snapshot"]
    if type(snapshot) is not int or snapshot < 0 or result["requested_version"] != requested:
        raise RuntimeError("invalid DuckLake snapshot identity")
    if requested is not None and requested > snapshot:
        raise RuntimeError("historical read goes beyond the engine transaction snapshot")
    result["rows"] = fixture_rows(result["rows"])
    result["snapshot_id"] = snapshot if requested is None else requested
    return result


class LineSession:
    """Bounded stdin/stdout protocol for local psql and the one-shot fixture runner."""

    def __init__(self, args, *, stderr):
        self.args = args
        self.stderr = stderr
        self.buffer = b""
        self.output_bytes = 0

    def __enter__(self):
        self.process = subprocess.Popen(
            self.args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr, bufsize=0,
        )
        return self

    def __exit__(self, *_):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)
        self.process.stdout.close()

    def send(self, data):
        self.process.stdin.write(data.encode())

    def line(self, deadline):
        while b"\n" not in self.buffer:
            remaining = max(0, deadline - time.monotonic())
            if not select.select([self.process.stdout], [], [], remaining)[0]:
                raise RuntimeError("interactive client deadline expired")
            block = os.read(self.process.stdout.fileno(), 4096)
            if not block:
                if self.buffer:
                    raise RuntimeError("interactive client returned a truncated line")
                return None
            self.output_bytes += len(block)
            if self.output_bytes > OUTPUT_LIMIT:
                raise RuntimeError("interactive client output exceeded bound")
            self.buffer += block
        if time.monotonic() > deadline:
            raise RuntimeError("interactive client deadline expired")
        line, self.buffer = self.buffer.split(b"\n", 1)
        return line.decode("utf-8")

    def packet(self, sql, deadline):
        self.send(f"{sql}\n\\echo {END_CAPTURE}\n")
        lines = []
        while (line := self.line(deadline)) != END_CAPTURE:
            if line is None:
                raise RuntimeError("target psql stopped before completing the capture")
            lines.append(line)
        return lines
