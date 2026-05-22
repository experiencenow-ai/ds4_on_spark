import json
import unittest
from pathlib import Path


TOPOLOGY = Path("sparknetwork.json")


def load_topology() -> dict:
    return json.loads(TOPOLOGY.read_text(encoding="utf-8"))


class SparkNetworkInventoryTest(unittest.TestCase):
    def test_inventory_has_eight_reachable_ssh_aliases(self) -> None:
        topo = load_topology()
        nodes = {node["id"]: node for node in topo["nodes"]}
        self.assertEqual(set(nodes), {f"spark{i}" for i in range(8)})
        self.assertIn("spark7", topo["ssh_policy"]["mac_config_verified_aliases"])
        self.assertEqual(nodes["spark7"]["hostname"], "thinkstation-pgx")
        self.assertEqual(nodes["spark7"]["ssh_alias"], "spark7")
        self.assertEqual(nodes["spark7"]["interfaces"]["wifi"]["state"], "ssh_verified")

    def test_spark6_spark7_dual_200g_links_are_declared(self) -> None:
        topo = load_topology()
        order = topo["ring_200g"]["order"]
        self.assertEqual(order[-2:], ["spark6", "spark7"])
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

    def test_internet_status_matches_wifi_only_offline_report(self) -> None:
        topo = load_topology()
        status = topo["internet_status"]
        self.assertEqual(status["working_wifi_internet"], [])
        self.assertEqual(status["pending_nodes"], [])
        self.assertIn("spark7", status["reachable_but_no_internet_route"])
        self.assertTrue(any("offline" in note for note in status["notes"]))


if __name__ == "__main__":
    unittest.main()
