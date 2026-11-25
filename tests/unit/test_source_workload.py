import unittest

from scripts.source.workload import payload_digest, s04_payload


class SourceWorkloadTests(unittest.TestCase):
    def test_s04_serialization_matches_the_published_receipt(self):
        self.assertEqual(
            payload_digest(s04_payload()),
            "4d2c11bd073069f7a4a9f38ba044d58219fad0c37ab3a2b43b300a97414432f8",
        )
