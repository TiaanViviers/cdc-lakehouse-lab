"""Source connection and transaction operations shared by fixture steps."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from .workload import fixture_time, insert_operations, payload_digest, s04_payload

SECRETS = Path("/run/secrets")
SEQUENTIAL_WRITER_LOCK = (1348076337, 15)


class FixtureError(Exception):
    """A rejected fixture operation."""


def connect(role):
    """Open a bounded connection with no transaction started by default."""
    if role not in ("writer", "reader"):
        raise FixtureError("expected a writer or reader role")
    return psycopg.connect(
        host="source-db", port=5432, dbname="source_lab", user=f"source_fixture_{role}",
        password=(SECRETS / f"source_fixture_{role}_password").read_text().strip(),
        connect_timeout=3, require_auth="scram-sha-256", sslmode="disable",
        gssencmode="disable", application_name=f"fixture-1.5-{role}",
        options=("-c statement_timeout=5000 -c lock_timeout=2000 "
                 "-c idle_in_transaction_session_timeout=15000 -c TimeZone=UTC "
                 "-c search_path=pg_catalog,pg_temp"),
        autocommit=True, row_factory=dict_row,
    )


@contextmanager
def write_transaction(connection):
    """The caller owns the connection and chooses where to commit or raise."""
    with connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        connection.execute("SET LOCAL synchronous_commit = on")
        yield connection


@contextmanager
def sequential_writer(connection):
    """Hold the sequential runner lock through its post-transaction observation."""
    connection.execute("SELECT pg_advisory_lock(%s, %s)", SEQUENTIAL_WRITER_LOCK)
    try:
        yield
    finally:
        connection.execute("SELECT pg_advisory_unlock(%s, %s)", SEQUENTIAL_WRITER_LOCK)


def claim_s04(connection, payload):
    """Return the digest for a new S04 receipt or None if its key is occupied."""
    receipt = connection.execute(
        """
        INSERT INTO fixture.scenario_receipts (fixture_version, seed, scenario_id, payload_sha256)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (fixture_version, seed, scenario_id) DO NOTHING
        RETURNING payload_sha256
        """,
        (payload["fixture_version"], payload["seed"], payload["scenario_id"],
         payload_digest(payload)),
    ).fetchone()
    return receipt["payload_sha256"] if receipt else None


def apply_inserts(connection, operations):
    """Apply the supplied ordered operations with explicitly supplied fields."""
    for operation in operations:
        values = operation["row"].copy()
        for column in ("created_at", "updated_at"):
            values[column] = datetime.fromisoformat(values[column])
        connection.execute(
            sql.SQL("INSERT INTO fixture.{} ({}) VALUES ({})").format(
                sql.Identifier(operation["table"]),
                sql.SQL(", ").join(map(sql.Identifier, values)),
                sql.SQL(", ").join(sql.Placeholder() for _ in values),
            ),
            tuple(values.values()),
        )


def apply_step(connection, scenario):
    """Apply a single step inside the caller's transaction."""
    if scenario == "S04":
        payload = s04_payload()
        if claim_s04(connection, payload) is None:
            raise FixtureError("S04 receipt already exists")
        apply_inserts(connection, payload["operations"])
    elif scenario in ("S00", "S01"):
        apply_inserts(connection, insert_operations(scenario))
    elif scenario == "S02":
        result = connection.execute(
            "UPDATE fixture.order_items SET quantity = 3, updated_at = %s WHERE item_id = 101",
            (fixture_time(scenario),),
        )
        if result.rowcount != 1:
            raise FixtureError("S02 requires item 101")
    elif scenario == "S03":
        result = connection.execute("DELETE FROM fixture.order_items WHERE item_id = 102")
        if result.rowcount != 1:
            raise FixtureError("S03 requires item 102")
    else:
        raise FixtureError(f"unsupported scenario {scenario!r}")


def reset_to_s00(connection, disposable_id, after_cleanup):
    """Clear and seed in the caller's transaction using the 1.3 guard."""
    connection.execute("SELECT fixture.cleanup(%s::boolean, %s::uuid)", (True, disposable_id))
    after_cleanup()
    apply_step(connection, "S00")
