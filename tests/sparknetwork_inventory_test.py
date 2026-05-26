import json
import unittest
from pathlib import Path


TOPOLOGY = Path("sparknetwork.json")


def load_topology() -> dict:
    return json.loads(TOPOLOGY.read_text(encoding="utf-8"))


class SparkNetworkInventoryTest(unittest.TestCase):
    def test_inventory_has_eight_nodes_and_spark7_wifi_alias(self) -> None:
        topo = load_topology()
        nodes = {node["id"]: node for node in topo["nodes"]}
        self.assertEqual(set(nodes), {f"spark{i}" for i in range(8)})
        self.assertEqual(topo["ssh_policy"]["direct_wifi_aliases"]["spark7"], "spark7")
        self.assertEqual(nodes["spark7"]["hostname"], "thinkstation-pgx")
        self.assertEqual(nodes["spark7"]["ssh_alias"], "spark7")
        self.assertEqual(nodes["spark7"]["interfaces"]["wifi"]["ipv4"], "192.168.1.236/24")

    def test_spark6_spark7_dual_200g_links_are_declared(self) -> None:
        topo = load_topology()
        self.assertEqual(topo["ring_200g"]["order"][-2:], ["spark6", "spark7"])
        links = [
            link for link in topo["ring_200g"]["links"]
            if link.get("edge") == "spark6-spark7"
        ]
        self.assertEqual(len(links), 2)
        got = sorted((link["a"]["ipv4"], link["b"]["ipv4"]) for link in links)
        self.assertEqual(got, [
            ("10.10.13.1/30", "10.10.13.2/30"),
            ("10.10.14.1/30", "10.10.14.2/30"),
        ])

    def test_rescue_and_agent_inventory_include_spark7(self) -> None:
        topo = load_topology()
        self.assertIn("spark7", topo["centaur_control"]["agent"]["nodes"])
        self.assertEqual(topo["centaur_control"]["agent"]["pending_nodes"], [])
        self.assertIn("spark7", topo["rescue_control"]["deployed_nodes"])
        self.assertEqual(topo["rescue_control"]["not_deployed_nodes"], [])
        self.assertEqual(topo["rescue_control"]["peer_ssh_heartbeat"]["unit"], "ds4-peer-ssh-heartbeat.timer")
        self.assertIn("spark6=spark6@10.20.0.16", topo["rescue_control"]["peer_ssh_heartbeat"]["control_targets"])
        self.assertEqual(topo["rescue_control"]["sshd_watchdog"]["peer_stale_seconds_default"], 300)
        self.assertEqual(topo["rescue_control"]["sshd_watchdog"]["reboot_after_default"], 3)
        self.assertEqual(topo["rescue_control"]["sshd_watchdog"]["external_deadman_seconds_default"], 28800)
        self.assertIn("DS4_WATCHDOG_EXTERNAL_DEADMAN_SECONDS", topo["rescue_control"]["sshd_watchdog"]["memory_hog_fallback"]["tunables"])

    def test_internet_status_matches_current_wired_report(self) -> None:
        topo = load_topology()
        status = topo["internet_status"]
        self.assertEqual(set(status["working_wired_internet"]), {f"spark{i}" for i in range(8)})
        self.assertEqual(status["pending_nodes"], [])
        self.assertEqual(status["reachable_but_no_internet_route"], [])
        self.assertIn("spark7", status["public_ipv4"])
        self.assertTrue(any("wired-side internet" in note for note in status["notes"]))


if __name__ == "__main__":
    unittest.main()
