import json
import unittest
from pathlib import Path


TOPOLOGY = Path("sparknetwork.json")
RUNBOOK = Path("SPARKNETWORK.md")


def load_topology() -> dict:
    return json.loads(TOPOLOGY.read_text(encoding="utf-8"))


class SparkNetworkClosedRingTest(unittest.TestCase):
    def test_topology_declares_closed_eight_node_ring(self) -> None:
        topo = load_topology()
        ring = topo["ring_200g"]
        self.assertEqual(ring["state"], "closed-routed-ring")
        self.assertEqual(ring["order"], [f"spark{i}" for i in range(8)])
        self.assertNotIn("missing_return_edge", ring)

    def test_all_edges_have_two_rails_including_spark7_return(self) -> None:
        ring = load_topology()["ring_200g"]
        expected_edges = {
            "spark0-spark1",
            "spark1-spark2",
            "spark2-spark3",
            "spark3-spark4",
            "spark4-spark5",
            "spark5-spark6",
            "spark6-spark7",
            "spark7-spark0",
        }
        rails_by_edge: dict[str, set[str]] = {}
        for link in ring["links"]:
            rails_by_edge.setdefault(link["edge"], set()).add(link["rail"])
        self.assertEqual(set(rails_by_edge), expected_edges)
        self.assertEqual(
            {edge: rails for edge, rails in rails_by_edge.items()},
            {edge: {"a", "b"} for edge in expected_edges},
        )

    def test_spark7_return_edge_addresses_are_declared(self) -> None:
        links = [
            link for link in load_topology()["ring_200g"]["links"]
            if link["edge"] == "spark7-spark0"
        ]
        got = sorted((link["a"]["ipv4"], link["b"]["ipv4"]) for link in links)
        self.assertEqual(got, [
            ("10.10.15.1/30", "10.10.15.2/30"),
            ("10.10.16.1/30", "10.10.16.2/30"),
        ])

    def test_loopbacks_and_verification_cover_all_nodes(self) -> None:
        ring = load_topology()["ring_200g"]
        self.assertEqual(set(ring["loopbacks"]), {f"spark{i}" for i in range(8)})
        self.assertEqual(set(ring["local_hostnames"]), {f"spark{i}" for i in range(8)})
        self.assertIn("all 16 /30 links", ring["verification"]["adjacent_links"])
        self.assertIn("all 56 directed", ring["verification"]["all_to_all_loopbacks"])

    def test_runbook_no_longer_claims_open_line(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("closed routed ring", text)
        self.assertIn("spark7 -> spark0", text)
        self.assertNotIn("open-line 200G fabric", text)
        self.assertNotIn("return edge is still missing", text)


if __name__ == "__main__":
    unittest.main()
