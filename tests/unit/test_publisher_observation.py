import json
import subprocess
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from scripts.cdc.wal.observe import Observer, Source


def source(*, empty=False):
    names = () if empty else ("slot_24", "pub_24", ("fixture.orders",))
    return Source("p24", "a" * 64, "b" * 64, "1234", *names)


def database_sample(*, empty=False):
    return {
        "server_version_num": 160016,
        "positions": {"insert_lsn": "0/1234", "write_lsn": "0/1234", "flush_lsn": "0/1234",
                      "checkpoint_timeline_id": 1, "postmaster_started_at": "2026-11-26T01:00:00+00:00"},
        "slot_inventory_count": int(not empty),
        "publication_inventory_count": int(not empty),
        "publication": None if empty else {
            "pubname": "pub_24", "puballtables": False, "schema_wide": False,
        },
        "members": [] if empty else [{"schema": "fixture", "table": "orders", "filtered": False}],
        "slot": None if empty else {
            "slot_name": "slot_24", "database": "source_lab", "slot_type": "logical",
            "plugin": "pgoutput", "temporary": False, "active": False, "active_pid": None,
            "restart_lsn": "0/1214", "confirmed_flush_lsn": "0/1218",
            "wal_status": "reserved", "safe_wal_size": None,
        },
        "feedback": None,
        "wal_bytes": {"insert_since_previous": None,
                      "insert_to_restart": None if empty else 32,
                      "insert_to_confirmed_flush": None if empty else 28},
    }


def responses(*samples):
    for sample in samples:
        yield f'p24 source-db 1 {"b" * 64} volume p24_source-pg'.encode()
        yield json.dumps(sample).encode()
        yield b"100000\n32000\n3000000\n"


class PublisherObservationTests(unittest.TestCase):
    def test_empty_baseline_keeps_absent_values(self):
        observer = Observer(source(empty=True), "run-24", 10, 1)
        with patch.object(observer, "command", side_effect=responses(database_sample(empty=True))):
            row = observer.sample("2.4", "empty")
        self.assertIsNone(row["error"])
        self.assertIsNone(row["ownership"]["slot"])
        self.assertIsNone(row["postgresql"]["slot"])
        self.assertIsNone(row["postgresql"]["feedback"])
        self.assertIsNone(row["postgresql"]["wal_bytes"]["insert_to_restart"])
        self.assertEqual(row["postgresql"]["members"], [])
        self.assertEqual(row["storage"]["wal_kib"], 32000)
        self.assertIsNone(row["commit_lsn"])
        self.assertIsNone(row["end_lsn"])

    def test_inactive_slot_and_before_after_positions_on_monotonic_timeline(self):
        observer = Observer(source(), "run-24", 10, 2)
        before, after = database_sample(), database_sample()
        after["positions"]["insert_lsn"] = "0/1244"
        after["wal_bytes"]["insert_since_previous"] = 16
        with (patch.object(observer, "command", side_effect=responses(before, after)) as command,
              patch("scripts.cdc.wal.observe.datetime") as wall):
            wall.now.side_effect = [
                datetime(2026, 11, 26, 2, tzinfo=timezone.utc),
                datetime(2026, 11, 26, 1, tzinfo=timezone.utc),
            ]
            first = observer.sample("2.4", "before")
            second = observer.sample("2.4", "after")
        self.assertIsNone(first["error"])
        self.assertIsNone(second["error"])
        self.assertFalse(second["postgresql"]["slot"]["active"])
        self.assertIsNone(second["postgresql"]["slot"]["safe_wal_size"])
        self.assertIsNone(second["postgresql"]["feedback"])
        self.assertEqual(second["postgresql"]["wal_bytes"]["insert_since_previous"], 16)
        self.assertIn("previous_insert=0/1234", command.call_args_list[4].args[0])
        self.assertLess(second["utc"], first["utc"])
        self.assertLessEqual(first["monotonic_elapsed_ns"], second["sample_started_elapsed_ns"])
        self.assertLessEqual(second["sample_started_elapsed_ns"], second["monotonic_elapsed_ns"])

    def test_active_feedback_preserves_missing_lags_and_commit_evidence(self):
        observer = Observer(source(), "run-24", 10, 1)
        payload = database_sample()
        payload["slot"].update(active=True, active_pid=174)
        payload["feedback"] = {
            "pid": 174, "state": "streaming", "sent_lsn": "0/1234",
            "write_lsn": "0/1218", "flush_lsn": "0/1218", "replay_lsn": None,
            "write_lag": None, "flush_lag": None, "replay_lag": None, "reply_time": None,
        }
        with patch.object(observer, "command", side_effect=responses(payload)):
            row = observer.sample("2.4", "streaming")
        self.assertIsNone(row["error"])
        self.assertEqual(row["postgresql"]["feedback"], payload["feedback"])
        self.assertIsNone(row["commit_lsn"])
        self.assertIsNone(row["end_lsn"])

    def test_unexpected_slot_is_rejected_without_leaking_name_or_reading_disk(self):
        for field, value in (("slot_name", "unrelated"), ("plugin", "wrong"),
                             ("database", "wrong"), ("temporary", True)):
            with self.subTest(field=field):
                payload = database_sample()
                payload["slot"][field] = value
                observer = Observer(source(), "run-24", 10, 1)
                with patch.object(observer, "command", side_effect=responses(payload)) as command:
                    row = observer.sample("2.4", "wrong-slot")
                self.assertEqual(row["error"], "slot_identity")
                self.assertIsNone(row["postgresql"])
                self.assertEqual(command.call_count, 2)

        payload = database_sample()
        payload["slot_inventory_count"] = 2
        observer = Observer(source(), "run-24", 10, 1)
        with patch.object(observer, "command", side_effect=responses(payload)):
            self.assertEqual(observer.sample("2.4", "extra-slot")["error"], "slot_identity")

    def test_wrong_source_and_publication_stop_before_disk(self):
        observer = Observer(source(), "run-24", 10, 1)
        with patch.object(observer, "command", return_value=b"wrong identity") as command:
            self.assertEqual(observer.sample("2.4", "wrong-source")["error"], "container_identity")
        command.assert_called_once()

        observer = Observer(source(), "run-24", 10, 1)
        payload = database_sample()
        payload["members"][0]["table"] = "wrong_table"
        with patch.object(observer, "command", side_effect=responses(payload)) as command:
            self.assertEqual(observer.sample("2.4", "wrong-member")["error"], "publication_identity")
        self.assertEqual(command.call_count, 2)

    def test_exhausted_deadline_never_invokes_docker(self):
        with patch("scripts.cdc.wal.observe.time.monotonic_ns", return_value=0):
            observer = Observer(source(), "run-24", 1, 1)
        with (patch("scripts.cdc.wal.observe.time.monotonic_ns", return_value=1_000_000_000),
              patch("scripts.cdc.wal.observe.subprocess.run") as run):
            row = observer.sample("2.4", "late")
        self.assertEqual(row["error"], "deadline_exhausted")
        self.assertIsNone(row["postgresql"])
        run.assert_not_called()

    def test_timeout_is_redacted(self):
        timeout = subprocess.TimeoutExpired(["docker", "sensitive"], 1, output=b"sensitive")
        observer = Observer(source(), "run-24", 1, 1)
        with patch("scripts.cdc.wal.observe.subprocess.run", side_effect=timeout):
            row = observer.sample("2.4", "timeout")
        self.assertEqual(row["error"], "capture_timeout")
        self.assertNotIn("sensitive", json.dumps(row))

    def test_sample_cap_stops_before_invoking_docker_again(self):
        observer = Observer(source(empty=True), "run-24", 10, 1)
        with patch.object(observer, "command", side_effect=responses(database_sample(empty=True))) as command:
            self.assertIsNone(observer.sample("2.4", "empty")["error"])
            self.assertEqual(observer.sample("2.4", "over-cap")["error"], "sample_budget_exhausted")
        self.assertEqual(command.call_count, 3)
