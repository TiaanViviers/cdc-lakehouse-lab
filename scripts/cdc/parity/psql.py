"""Bounded PostgreSQL-facing projection. Connector mappings are caller inputs."""

import csv
import io
import math
import re
import subprocess
from collections.abc import Mapping, Sequence

from tests.fixture_oracle import PRIMARY_KEYS

from . import COLUMNS, ROW_LIMIT, Capture, ReadError, ReadTimeout

SOURCE_TABLES = {name: ("fixture", name) for name in COLUMNS}
SEMANTICS = (
    "One PostgreSQL read-only REPEATABLE READ transaction per capture. "
    "DuckLake table snapshot attribution is unverified."
)
NULL = "__CDC_PARITY_NULL__"


def identifier(name: str) -> str:
    # The lab uses simple PostgreSQL identifiers. Reject ambiguous/truncated names.
    if not re.fullmatch(r"[a-z_][a-z_0-9]{0,62}", name):
        raise ValueError("expected a simple PostgreSQL identifier")
    return '"' + name + '"'


def select_rows(
    table: tuple[str, str], columns: tuple[str, ...], key: str
) -> str:
    if len(table) != 2 or key not in columns or len(set(columns)) != len(columns):
        raise ValueError("projection requires a schema/table pair and unique columns including the key")
    relation = ".".join(map(identifier, table))
    fields = ", ".join(map(identifier, columns))
    return f"SELECT {fields} FROM {relation} ORDER BY {identifier(key)} LIMIT {ROW_LIMIT + 1};"


def read_projections(
    command: Sequence[str],
    projections: Mapping[str, tuple[tuple[str, str], tuple[str, ...], str]],
    timeout: float,
) -> Capture:
    """Read simple mapped tables via a psql command prefix with local credentials."""
    if not projections or not command:
        raise ValueError("provide a psql command and at least one projection")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    timeout_ms = max(1, int(min(timeout, 2147483) * 1000))
    sql = [
        "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;",
        f"SET LOCAL statement_timeout = {timeout_ms};",
        f"SET LOCAL idle_in_transaction_session_timeout = {timeout_ms};",
        "SET LOCAL TIME ZONE 'UTC';",
        "SET LOCAL DateStyle = 'ISO, YMD';",
    ]
    # A marker has more CSV fields than any projected row. Parse CSV records
    # before testing for markers so a multiline text value cannot split a block.
    marker = "," * max(len(columns) for _, columns, _ in projections.values())
    for table, columns, key in projections.values():
        sql.extend((f"\\echo {marker}", select_rows(table, columns, key)))
    sql.append("ROLLBACK;")
    try:
        proc = subprocess.run(
            [*command, "-Xq", "--no-password", "--csv", "--pset=footer=off",
             f"--pset=null={NULL}", "--set=ON_ERROR_STOP=1", "--file=-"],
            input="\n".join(sql) + "\n",
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise ReadTimeout("psql client deadline expired") from None
    except (OSError, UnicodeError):
        raise ReadError("could not start psql or decode its output") from None
    if proc.returncode:
        raise ReadError(f"psql read failed (exit {proc.returncode})")

    records = iter(csv.reader(io.StringIO(proc.stdout, newline=""), strict=True))
    delimiter = marker.split(",")
    rows = {}
    try:
        record = next(records, None)
        for name, (_, columns, _) in projections.items():
            if record != delimiter or next(records, None) != list(columns):
                raise ReadError(f"{name}: unexpected psql projection header")
            rows[name] = []
            for record in records:
                if record == delimiter:
                    break
                if len(record) != len(columns):
                    raise ReadError(f"{name}: unexpected psql projection width")
                if len(rows[name]) == ROW_LIMIT:
                    raise ReadError(f"{name}: row overflow (limit {ROW_LIMIT})")
                rows[name].append(dict(zip(
                    columns, (None if value == NULL else value for value in record), strict=True
                )))
            else:
                record = None
        if record is not None:
            raise ReadError("unexpected trailing psql result")
    except csv.Error:
        raise ReadError("invalid psql CSV output") from None
    return Capture(rows, SEMANTICS)


def read_fixture(
    command: Sequence[str], mapping: Mapping[str, tuple[str, str]], timeout: float
) -> Capture:
    """Read the four v1 business tables using an explicit side-specific mapping."""
    if mapping.keys() != COLUMNS.keys() or len(set(mapping.values())) != len(COLUMNS):
        raise ValueError("provide four distinct fixture table mappings")
    return read_projections(command, {
        name: (mapping[name], columns, PRIMARY_KEYS[name])
        for name, columns in COLUMNS.items()
    }, timeout)
