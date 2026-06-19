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
        self.assertIn("Before=network-pre.target network-online.target ds4-ring-200g.service", text)
        self.assertIn("Restart=on-failure", text)
        self.assertIn("systemctl reset-failed ds4-ring-control-iface.service ds4-ring-200g.service", text)
        self.assertNotIn("ExecStart=/usr/local/sbin/ds4-ring-control-iface-apply", text)
        self.assertNotIn("install -m 0755 \"$tmp_script\" /usr/local/sbin/ds4-ring-control-iface-apply", text)

    def test_local_installer_recreates_control_iface_after_200g_setup(self) -> None:
        text = (REPO_ROOT / "scripts/ds4_install_ring_control_iface_local.sh").read_text()

        self.assertIn("/etc/systemd/system/ds4-ring-200g.service.d", text)
        self.assertIn("zz-ds4-ring-control-iface.conf", text)
        self.assertIn("rm -f \"$override_dir/control-iface.conf\"", text)
        self.assertIn("[ -x /usr/local/sbin/ds4-ring-200g-apply ]", text)
        self.assertIn("/usr/local/sbin/ds4-ring-200g-apply && /usr/local/sbin/ds4-ring-200g-extend13", text)
        self.assertIn("else /usr/local/sbin/ds4-ring-200g; fi", text)
        self.assertIn("fi && /usr/local/sbin/ds4-ring-control-iface", text)

    def test_local_installer_installs_canonical_13_node_route_helpers(self) -> None:
        text = (REPO_ROOT / "scripts/ds4_install_ring_control_iface_local.sh").read_text()

        self.assertIn("tmp_route_apply=", text)
        self.assertIn("while [ \"\\$target_rank\" -lt 13 ]", text)
        self.assertIn("target_ip=\"10.10.100.\\$((10 + target_rank))\"", text)
        self.assertIn("setup_rail \"enp1s0f0np0\"", text)
        self.assertIn("setup_rail \"enp1s0f1np1\"", text)
        self.assertIn("dev=\"enP2p1s0f1np1\"", text)
        self.assertIn("dev=\"enP2p1s0f0np0\"", text)
        self.assertIn("fallback_dev=\"enp1s0f1np1\"", text)
        self.assertIn("fallback_dev=\"enp1s0f0np0\"", text)
        self.assertIn("if rail_up \"\\$primary_dev\"", text)
        self.assertIn("install -m 0755 \"$tmp_route_apply\" /usr/local/sbin/ds4-ring-200g-apply", text)
        self.assertIn("install -m 0755 \"$tmp_route_extend\" /usr/local/sbin/ds4-ring-200g-extend13", text)


if __name__ == "__main__":
    unittest.main()
