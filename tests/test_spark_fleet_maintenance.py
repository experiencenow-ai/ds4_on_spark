from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "scripts" / "ds4_spark_fleet_preflight.py"
PROXY = ROOT / "scripts" / "ds4_spark_fleet_proxy.py"
PACKAGE_ALIGN = ROOT / "scripts" / "ds4_spark_package_align.py"
SWITCHED_APPLY = ROOT / "scripts" / "ds4_switched_fabric_apply.sh"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name,path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class SparkFleetMaintenanceTests(unittest.TestCase):
    def test_package_alignment_excludes_platform_and_role_cohorts(self) -> None:
        module = load_module(PACKAGE_ALIGN,"ds4_spark_package_align_test")
        self.assertTrue(module.is_protected("linux-image-6.17.0-1026-nvidia"))
        self.assertTrue(module.is_protected("librados2"))
        self.assertTrue(module.is_protected("podman"))
        self.assertTrue(module.is_protected("libcublas-13-0"))
        self.assertFalse(module.is_protected("python3-numpy"))

    def test_switched_fabric_script_has_one_canonical_network_baseline(self) -> None:
        source = SWITCHED_APPLY.read_text(encoding="utf-8")
        self.assertIn("/etc/sysctl.d/99-ds4-fleet.conf",source)
        self.assertIn("ethtool -G \"${FABRIC_DEVICE}\" rx 8192 tx 8192",source)
        self.assertIn("ethtool -K \"${FABRIC_DEVICE}\" tx-tcp-mangleid-segmentation off",source)
        self.assertIn("99-ds4-rescue.conf",source)
        self.assertIn("retire_legacy_mac_mounts",source)
        self.assertIn("/home/mac-volumes",source)
        self.assertIn("systemd-escape --path",source)
        self.assertIn("retire_legacy_nat",source)
        self.assertIn("iptables -P FORWARD ACCEPT",source)
        self.assertNotIn("zz-retired-switched-fabric.conf",source)

    def test_proxy_reads_addresses_from_topology(self) -> None:
        module = load_module(PROXY,"ds4_spark_fleet_proxy_test")
        records = module.load_topology(str(ROOT / "v2/profiles/transfer/spark_200g.json"))
        candidates = module.route_candidates("sparkd","auto",records)
        self.assertEqual(candidates[0],("fabric","10.10.100.23",0.75))
        self.assertEqual(candidates[1],("mgmt","10.20.0.23",0.75))

    def test_preflight_passes_qualified_idle_node(self) -> None:
        module = load_module(PREFLIGHT,"ds4_spark_fleet_preflight_test")
        node = module.Node("sparkd",13,"sparkd@10.20.0.23","sparkd-200g","10.10.100.23","10.20.0.23")
        observed = {
            "hostname":"sparkd",
            "rank_file":"13",
            "legacy_rank_file":"",
            "all_ipv4":["10.20.0.23/24","10.10.100.23/24"],
            "fabric_links":[{
                "device":"enp1s0f1np1",
                "operstate":"up",
                "duplex":"full",
                "speed_mbps":"100000",
                "ipv4":["10.10.100.23/24"],
            }],
            "units": {
                unit:{"enabled":"enabled","active":"active"}
                for unit in module.REQUIRED_UNITS
            },
            "tailscale":{"state":"Running","ip_present":True},
            "workload_processes":{name:[] for name in module.WORKLOAD_PROCESSES},
            "gpu":{"compute_apps":[]},
            "extnvme_mounted":False,
            "recent_xid":"",
        }
        failures,warnings = module.evaluate_node(
            node,observed,require_fabric=True,require_tailscale=True,
            strict_hostname=True,allow_workload=False,
        )
        self.assertEqual(failures,[])
        self.assertEqual(warnings,["extnvme_not_mounted"])

    def test_preflight_rejects_degraded_link_and_workload(self) -> None:
        module = load_module(PREFLIGHT,"ds4_spark_fleet_preflight_test_degraded")
        node = module.Node("sparkd",13,"sparkd@10.20.0.23","sparkd-200g","10.10.100.23","10.20.0.23")
        observed = {
            "hostname":"sparkd",
            "rank_file":"13",
            "legacy_rank_file":"",
            "all_ipv4":["10.20.0.23/24","10.10.100.23/24"],
            "fabric_links":[{
                "operstate":"up",
                "duplex":"full",
                "speed_mbps":"10000",
                "ipv4":["10.10.100.23/24"],
            }],
            "units": {
                unit:{"enabled":"enabled","active":"active"}
                for unit in module.REQUIRED_UNITS
            },
            "tailscale":{"state":"Running","ip_present":True},
            "workload_processes":{"sparkpipe_gateway":["1234"]},
            "gpu":{"compute_apps":[]},
            "extnvme_mounted":True,
            "recent_xid":"",
        }
        failures,_warnings = module.evaluate_node(
            node,observed,require_fabric=True,require_tailscale=True,
            strict_hostname=True,allow_workload=False,
        )
        self.assertIn("no_100g_full_duplex_link",failures)
        self.assertIn("stale_workload=sparkpipe_gateway",failures)

    def test_preflight_rejects_legacy_rank_until_migrated(self) -> None:
        module = load_module(PREFLIGHT,"ds4_spark_fleet_preflight_test_legacy_rank")
        node = module.Node("spark0",0,"spark0@10.20.0.10","spark0-200g","10.10.100.10","10.20.0.10")
        observed = {
            "hostname":"spark0",
            "rank_file":"",
            "legacy_rank_file":"0",
            "all_ipv4":["10.20.0.10/24","10.10.100.10/24"],
            "fabric_links":[{
                "operstate":"up",
                "duplex":"full",
                "speed_mbps":"100000",
                "ipv4":["10.10.100.10/24"],
            }],
            "units": {
                unit:{"enabled":"enabled","active":"active"}
                for unit in module.REQUIRED_UNITS
            },
            "tailscale":{"state":"Running","ip_present":True},
            "workload_processes":{name:[] for name in module.WORKLOAD_PROCESSES},
            "gpu":{"compute_apps":[]},
            "extnvme_mounted":True,
            "recent_xid":"",
        }
        failures,warnings = module.evaluate_node(
            node,observed,require_fabric=True,require_tailscale=True,
            strict_hostname=True,allow_workload=False,
        )
        self.assertIn("rank_file='' expected=0",failures)
        self.assertIn("legacy_ds4-ring-rank_present",failures)


if __name__ == "__main__":
    unittest.main()
