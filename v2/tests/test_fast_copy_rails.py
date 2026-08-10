from __future__ import annotations

from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from ds4_transfer import fast_copy
from ds4_transfer.service import TransferTopology


ROOT = Path(__file__).resolve().parents[1]
TOPOLOGY = ROOT / "profiles" / "transfer" / "spark_200g.json"


class FastCopyRailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.topology = TransferTopology.load(TOPOLOGY)

    def test_discover_rails_skips_unbound_configured_rail(self) -> None:
        def run_ssh(topology, node, script, timeout_s):
            del topology, timeout_s
            if "10.10.7.1/32" in script:
                return self._completed(script, "")
            if "10.10.8.1/32" in script and node == "spark3":
                return self._completed(script, "spark3-bound\n")
            if "10.10.8.2/32" in script and node == "spark4":
                return self._completed(script, "spark4-bound\n")
            if script.startswith("ping "):
                return self._completed(script, "ok\n")
            raise AssertionError((node, script))

        with patch.object(fast_copy, "_run_ssh", side_effect=run_ssh):
            rails = fast_copy._discover_rails(
                self.topology,
                "spark3",
                "spark4",
                30,
            )
        self.assertEqual(
            [
                (rail.source_ip, rail.destination_ip)
                for rail in rails
            ],
            [("10.10.8.1", "10.10.8.2")],
        )

    def test_discover_rails_fails_closed_when_none_are_live(self) -> None:
        with patch.object(
            fast_copy,
            "_run_ssh",
            return_value=self._completed("ip", ""),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "no configured 200G rail is live",
            ):
                fast_copy._discover_rails(
                    self.topology,
                    "spark3",
                    "spark4",
                    30,
                )

    @staticmethod
    def _completed(argv, stdout, returncode=0):
        return subprocess.CompletedProcess(
            argv,
            returncode,
            stdout=stdout,
            stderr="",
        )


if __name__ == "__main__":
    unittest.main()
