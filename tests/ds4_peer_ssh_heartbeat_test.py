import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path("scripts/ds4_peer_ssh_heartbeat.py")


def load_module():
    spec = importlib.util.spec_from_file_location("ds4_peer_ssh_heartbeat", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Ds4PeerSshHeartbeatTest(unittest.TestCase):
    def test_safe_name_removes_path_characters(self) -> None:
        mod = load_module()
        self.assertEqual(mod.safe_name("../spark6;rm"), "spark6rm")

    def test_parse_peers_excludes_observer_and_duplicates(self) -> None:
        mod = load_module()
        self.assertEqual(mod.parse_peers("spark0,spark1,spark0,spark2", "spark1"), [("spark0", "spark0"), ("spark2", "spark2")])

    def test_parse_peers_keeps_label_for_ip_target(self) -> None:
        mod = load_module()
        self.assertEqual(mod.parse_peers("spark6=spark6@10.20.0.16", "spark0"), [("spark6", "spark6@10.20.0.16")])

    def test_build_record_carries_fresh_and_control_status(self) -> None:
        mod = load_module()
        rec = mod.build_record("spark0", "spark6", {"ok": False, "rc": 255, "stderr": "banner timeout", "seconds": 5.1}, {"ok": True, "rc": 0, "seconds": 0.2})
        self.assertEqual(rec["schema"], "ds4.peer_ssh_observation.v1")
        self.assertEqual(rec["observer"], "spark0")
        self.assertEqual(rec["target"], "spark6")
        self.assertEqual(rec["probe_mode"], "fresh_ssh_plus_persistent_control")
        self.assertFalse(rec["ssh_exec_ok"])
        self.assertTrue(rec["control_exec_ok"])
        self.assertFalse(rec["remote_rescue_attempted"])
        self.assertEqual(rec["ssh_rc"], 255)
        self.assertIn("banner timeout", rec["ssh_stderr"])

    def test_remote_rescue_requires_owner_control_and_failed_fresh_probe(self) -> None:
        mod = load_module()
        self.assertTrue(mod.should_attempt_remote_rescue("spark0", "spark0", {"ok": False}, {"ok": True}))
        self.assertTrue(mod.should_attempt_remote_rescue("spark1", "any", {"ok": False}, {"ok": True}))
        self.assertTrue(mod.should_attempt_remote_rescue("spark2", "spark0,spark2", {"ok": False}, {"ok": True}))
        self.assertFalse(mod.should_attempt_remote_rescue("spark1", "spark0", {"ok": False}, {"ok": True}))
        self.assertFalse(mod.should_attempt_remote_rescue("spark0", "spark0", {"ok": True}, {"ok": True}))
        self.assertFalse(mod.should_attempt_remote_rescue("spark0", "spark0", {"ok": False}, {"ok": False}))


if __name__ == "__main__":
    unittest.main()
