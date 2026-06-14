from pathlib import Path
import os
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]


class MacFastInternetGatewayTests(unittest.TestCase):
    def test_local_refresher_uses_mac_gateway_and_fallback(self) -> None:
        text = (REPO_ROOT / "scripts" / "ds4_mac_fast_internet_gateway_local.sh").read_text()

        self.assertIn('LAN_GW="${LAN_GW:-10.20.0.1}"', text)
        self.assertIn('FALLBACK_GW="${FALLBACK_GW:-10.20.0.13}"', text)
        self.assertIn('ip route replace default via "$LAN_GW" dev "$LAN_DEV" metric 50', text)
        self.assertIn('ip route replace default via "$FALLBACK_GW" dev "$LAN_DEV" metric 100', text)
        self.assertIn('resolvectl dns "$LAN_DEV" $DNS_SERVERS', text)
        self.assertIn("spark8|spark9|sparka|sparkb|sparkc", text)

    def test_installer_defaults_to_topology_nodes(self) -> None:
        text = (REPO_ROOT / "scripts" / "ds4_install_mac_fast_internet_gateway_service.sh").read_text()

        self.assertIn("spark_200g.json", text)
        self.assertIn("load_default_nodes()", text)
        self.assertIn("node_ssh_target()", text)
        self.assertIn('scp_opts="${DS4_SCP_OPTS:-}"', text)
        self.assertNotIn("DS4_REMOTE_REPO", text)
        self.assertNotIn("nodes=(spark0 spark1 spark2 spark3 spark4 spark5 spark6 spark7)", text)

    def test_installer_writes_node_id_env_and_systemd_files(self) -> None:
        text = (REPO_ROOT / "scripts" / "ds4_install_mac_fast_internet_gateway_service.sh").read_text()

        self.assertIn("DS4_NODE_ID=$node", text)
        self.assertIn("/etc/ds4-mac-fast-internet-gateway.env", text)
        self.assertIn("printf '%s\\n'", text)
        self.assertNotIn("printf \"%q\"", text)
        self.assertIn("systemctl enable --now ds4-mac-fast-internet-gateway.timer", text)
        self.assertIn("systemctl start ds4-mac-fast-internet-gateway.service", text)

    def test_systemd_timer_reapplies_route_after_boot(self) -> None:
        service = (REPO_ROOT / "deploy" / "systemd" / "ds4-mac-fast-internet-gateway.service").read_text()
        timer = (REPO_ROOT / "deploy" / "systemd" / "ds4-mac-fast-internet-gateway.timer").read_text()

        self.assertIn("EnvironmentFile=-/etc/ds4-mac-fast-internet-gateway.env", service)
        self.assertIn("ExecStart=/usr/local/sbin/ds4-mac-fast-internet-gateway", service)
        self.assertIn("OnBootSec=20s", timer)
        self.assertIn("OnUnitActiveSec=60s", timer)
        self.assertIn("WantedBy=timers.target", timer)

    def test_fleet_scripts_are_executable(self) -> None:
        for path in (
            REPO_ROOT / "scripts" / "ds4_mac_fast_internet_gateway_local.sh",
            REPO_ROOT / "scripts" / "ds4_install_mac_fast_internet_gateway_service.sh",
        ):
            mode = path.stat().st_mode
            self.assertNotEqual(mode & os.X_OK, 0, str(path))


if __name__ == "__main__":
    unittest.main()
