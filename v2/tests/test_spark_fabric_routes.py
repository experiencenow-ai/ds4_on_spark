from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds4_check_spark_fabric_routes.py"


def load_module():
    spec = importlib.util.spec_from_file_location("ds4_check_spark_fabric_routes", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SparkFabricRouteTests(unittest.TestCase):
    def test_rank_filter_accepts_spark_names(self) -> None:
        module = load_module()
        self.assertEqual(module._parse_rank_filter("spark4,spark6", 8), [4, 6])

    def test_control_iface_commands_create_dummy_bind_iface(self) -> None:
        module = load_module()
        spec = module.ControlIfaceSpec(rank=4, ip="10.10.100.14")
        commands = spec.ip_cmds(sudo=True, remove_loopback=False)
        self.assertEqual(commands[0], "sudo ip link add ds4ring0 type dummy 2>/dev/null || true")
        self.assertEqual(commands[1], "sudo ip addr replace 10.10.100.14/32 dev ds4ring0")
        self.assertEqual(commands[2], "sudo ip link set ds4ring0 up")

    def test_control_iface_commands_can_remove_loopback_alias(self) -> None:
        module = load_module()
        spec = module.ControlIfaceSpec(rank=6, ip="10.10.100.16")
        commands = spec.ip_cmds(sudo=False, remove_loopback=True)
        self.assertEqual(commands[1], "ip addr del 10.10.100.16/32 dev lo 2>/dev/null || true")
        self.assertEqual(commands[2], "ip addr replace 10.10.100.16/32 dev ds4ring0")

    def test_route_check_caches_operstate_per_host_dev(self) -> None:
        module = load_module()
        calls: list[tuple[str, str]] = []

        def fake_run_ssh(host: str, command: str, timeout_s: int) -> subprocess.CompletedProcess[str]:
            calls.append((host, command))
            if "ip route get" in command:
                return subprocess.CompletedProcess(
                    ["ssh"],
                    0,
                    stdout="10.10.100.12 via 10.10.2.2 dev enP2p1s0f1np1 src 10.10.100.10 uid 1000\n",
                    stderr="",
                )
            return subprocess.CompletedProcess(["ssh"], 0, stdout="up\n", stderr="")

        module.run_ssh = fake_run_ssh
        spec_a = module.RouteSpec(
            source_rank=0,
            target_rank=1,
            target_ip="10.10.100.11",
            via="10.10.2.2",
            dev="enP2p1s0f1np1",
            source_ip="10.10.100.10",
            source_host="spark0",
        )
        spec_b = module.RouteSpec(
            source_rank=0,
            target_rank=2,
            target_ip="10.10.100.12",
            via="10.10.2.2",
            dev="enP2p1s0f1np1",
            source_ip="10.10.100.10",
            source_host="spark0",
        )
        failures = module.check_specs([spec_a, spec_b], sudo=True, timeout_s=8, strict_next_hop=True)
        operstate_calls = [command for _, command in calls if "operstate" in command]
        self.assertEqual(failures, 0)
        self.assertEqual(len(operstate_calls), 1)


if __name__ == "__main__":
    unittest.main()
