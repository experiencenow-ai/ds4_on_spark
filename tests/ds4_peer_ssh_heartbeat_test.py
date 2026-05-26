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

    def test_build_record_carries_failed_ssh_status(self) -> None:
        mod = load_module()
        rec = mod.build_record("spark0", "spark6", {"ok": False, "rc": 255, "stderr": "banner timeout", "seconds": 5.1})
        self.assertEqual(rec["schema"], "ds4.peer_ssh_observation.v1")
        self.assertEqual(rec["observer"], "spark0")
        self.assertEqual(rec["target"], "spark6")
        self.assertFalse(rec["ssh_exec_ok"])
        self.assertEqual(rec["ssh_rc"], 255)
        self.assertIn("banner timeout", rec["ssh_stderr"])


if __name__ == "__main__":
    unittest.main()
