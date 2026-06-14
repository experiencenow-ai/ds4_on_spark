from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]


class RingControlInstallerTests(unittest.TestCase):
    def test_fleet_installer_defaults_to_13_nodes(self) -> None:
        text = (REPO_ROOT / "scripts/ds4_install_ring_control_iface_service.sh").read_text()

        self.assertIn("spark8 spark9 sparka sparkb sparkc", text)

    def test_local_installer_supports_13_node_suffixes(self) -> None:
        text = (REPO_ROOT / "scripts/ds4_install_ring_control_iface_local.sh").read_text()

        self.assertIn("sparka)", text)
        self.assertIn("rank=10", text)
        self.assertIn("sparkb)", text)
        self.assertIn("rank=11", text)
        self.assertIn("sparkc)", text)
        self.assertIn("rank=12", text)

    def test_local_installer_uses_current_control_iface_unit(self) -> None:
        text = (REPO_ROOT / "scripts/ds4_install_ring_control_iface_local.sh").read_text()

        self.assertIn("ExecStart=/usr/local/sbin/ds4-ring-control-iface", text)
        self.assertIn("install -m 0755 \"$tmp_script\" /usr/local/sbin/ds4-ring-control-iface", text)
        self.assertNotIn("ExecStart=/usr/local/sbin/ds4-ring-control-iface-apply", text)
        self.assertNotIn("install -m 0755 \"$tmp_script\" /usr/local/sbin/ds4-ring-control-iface-apply", text)

    def test_local_installer_recreates_control_iface_after_200g_setup(self) -> None:
        text = (REPO_ROOT / "scripts/ds4_install_ring_control_iface_local.sh").read_text()

        self.assertIn("/etc/systemd/system/ds4-ring-200g.service.d", text)
        self.assertIn("control-iface.conf", text)
        self.assertIn("ds4-ring-200g-apply && /usr/local/sbin/ds4-ring-200g-extend13 && /usr/local/sbin/ds4-ring-control-iface", text)


if __name__ == "__main__":
    unittest.main()
