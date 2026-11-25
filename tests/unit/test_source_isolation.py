import json
import unittest
from unittest.mock import patch

from scripts.isolation import preflight


class SourceIsolationTests(unittest.TestCase):
    def check_rules(self, change=None, backend="iptables"):
        def listing(args, **kwargs):
            tool, _, chain = args
            expected = {
                "INPUT": "-A INPUT -i lab0 -j DROP",
                "DOCKER-USER": "-A DOCKER-USER -i lab0 ! -o lab0 -j DROP",
                "FORWARD": "-A FORWARD -j DOCKER-USER",
            }[chain]
            if change and (tool, chain) == ("ip6tables", "DOCKER-USER"):
                return change(expected)
            return expected

        with patch.object(preflight, "docker", return_value=backend), patch.object(
                preflight.subprocess, "check_output", side_effect=listing):
            preflight.check_firewall("lab0")

    def test_complete_rules(self):
        self.check_rules()

    def test_missing_or_bypassed_rules(self):
        for change in (lambda rule: "", lambda rule: "-A DOCKER-USER -j ACCEPT\n" + rule,
                       lambda rule: rule.replace("lab0", "other0")):
            with self.subTest(change=change), self.assertRaises(SystemExit):
                self.check_rules(change)

    def test_unsupported_backend(self):
        with self.assertRaisesRegex(SystemExit, "unsupported firewall backend"):
            self.check_rules(backend="nftables")

    def test_probe_error_is_not_evidence_of_denial(self):
        self.assertFalse(preflight.probe_passed(False, 125, "ETIMEDOUT"))
        self.assertFalse(preflight.probe_passed(False, 1, "wrong TCP marker"))
        self.assertFalse(preflight.probe_passed(True, 1, "ETIMEDOUT"))
        self.assertTrue(preflight.probe_passed(False, 1, "ETIMEDOUT"))

    def test_external_network_contract(self):
        identity = "a" * 64
        network = {"external": True, "name": identity}
        model = {"services": {"sentinel": {"networks": {"src": {}}}}, "networks": {"src": network}}
        self.assertEqual(preflight.external_ids(model), [identity])
        for invalid in ({"name": identity}, {"external": True, "name": "source-input"}):
            model["networks"]["src"] = invalid
            with self.assertRaises(SystemExit):
                preflight.external_ids(model)

    def test_failed_second_preflight_blocks_compose_start(self):
        model = {
            "services": {"source": {"networks": {"input": {}, "cdc": {}}}},
            "networks": {
                "input": {"external": True, "name": "1" * 64},
                "cdc": {"external": True, "name": "2" * 64},
            },
        }
        with patch.object(preflight, "docker", return_value=json.dumps(model)), patch.object(
                preflight, "main", side_effect=[None, SystemExit("probe failed")]) as probe, patch.object(
                preflight.subprocess, "run") as start:
            with self.assertRaisesRegex(SystemExit, "probe failed"):
                preflight.start_compose("compose.yaml")
            self.assertEqual([call.args[1] for call in probe.call_args_list], ["1" * 64, "2" * 64])
            start.assert_not_called()
