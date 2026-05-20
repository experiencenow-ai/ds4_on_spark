import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import spark_ring_fast_copy as fast_copy


TOPOLOGY = {
    "ring_200g": {
        "order": ["spark0", "spark1", "spark2", "spark3", "spark4"],
        "links": [
            {
                "edge": "spark2-spark3",
                "a": {"node": "spark2", "ipv4": "10.10.5.2/30"},
                "b": {"node": "spark3", "ipv4": "10.10.5.1/30"},
            },
            {
                "edge": "spark2-spark3",
                "a": {"node": "spark2", "ipv4": "10.10.6.2/30"},
                "b": {"node": "spark3", "ipv4": "10.10.6.1/30"},
            },
        ],
    }
}


class SparkRingFastCopyTest(unittest.TestCase):
    def test_ring_dest_ips_uses_both_neighbor_links(self) -> None:
        self.assertEqual(
            fast_copy.ring_dest_ips(TOPOLOGY, "spark2", "spark3", "both"),
            ["10.10.5.1", "10.10.6.1"],
        )
        self.assertEqual(
            fast_copy.ring_dest_ips(TOPOLOGY, "spark3", "spark2", "second"),
            ["10.10.6.2"],
        )

    def test_non_neighbor_rejected_before_remote_stat(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            fast_copy.ring_dest_ips(TOPOLOGY, "spark2", "spark4", "both")
        self.assertIn("not direct 200G neighbors", str(ctx.exception))

    def test_dry_run_can_validate_missing_source_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            topo = Path(tmp) / "sparknetwork.json"
            topo.write_text(json.dumps(TOPOLOGY), encoding="utf-8")
            argv = [
                "spark_ring_fast_copy.py",
                "--topology",
                str(topo),
                "--dry-run",
                "--engine",
                "native",
                "spark2:/tmp/ds4_native_test.bin",
                "spark3:/tmp/",
            ]
            out = io.StringIO()
            with patch("sys.argv", argv), patch.object(
                fast_copy, "remote_stat", side_effect=SystemExit("missing source")
            ), redirect_stdout(out):
                fast_copy.main()
            text = out.getvalue()
            self.assertIn("ring destination IPs: 10.10.5.1,10.10.6.1", text)
            self.assertIn("engine=native", text)
            self.assertIn("dry-run source stat skipped: missing source", text)


if __name__ == "__main__":
    unittest.main()
