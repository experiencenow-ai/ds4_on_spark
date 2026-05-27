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
    def test_safe_removes_path_characters(self) -> None:
        mod = load_module()
        self.assertEqual(mod.safe("../spark6;rm"), "spark6rm")

    def test_parse_peers_excludes_observer_and_duplicates(self) -> None:
        mod = load_module()
        self.assertEqual(mod.parse_peers("spark0,spark1,spark0,spark2", "spark1"), [("spark0", "spark0"), ("spark2", "spark2")])

    def test_quorum_threshold_uses_two_n_over_three(self) -> None:
        mod = load_module()
        self.assertEqual(mod.quorum_threshold(8), 5)
        self.assertEqual(mod.quorum_threshold(3), 2)

    def test_remote_trim_requires_quorum(self) -> None:
        mod = load_module()
        votes = [{"observer": "spark%d" % i, "targets": {"spark4": {"ssh_exec_ok": False}}} for i in range(5)]
        self.assertFalse(mod.quorum("spark4", votes[:4], 8)["met"])
        self.assertTrue(mod.quorum("spark4", votes, 8)["met"])

    def test_trim_urls_use_peer_host_and_trim_memory_endpoint(self) -> None:
        mod = load_module()
        urls = mod.trim_urls("spark4@10.20.0.14", "8000,18110")
        self.assertEqual(urls[0].split("?",1)[0], "http://10.20.0.14:8000/v1/trim_memory")
        self.assertIn("release_offload_memory=true", urls[1])


if __name__ == "__main__":
    unittest.main()
