from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "scripts" / "ds4_spark_fleet_audit.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name,path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class SparkFleetAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = load_module(AUDIT,"ds4_spark_fleet_audit_test")

    def row(self,node_id: str,kernel: str = "6.17"):
        return {
            "node_id":node_id,
            "observed":{
                "identity":{
                    "kernel":kernel,
                    "arch":"x86_64",
                    "os_release":{"ID":"ubuntu"},
                    "lscpu":{"available":True,"value":{"lscpu":[
                        {"field":"Model name:","data":"Spark CPU"},
                    ]}},
                },
                "gpu":{"rows":["GB10, 580.159, 128000 MiB, 0000:01:00.0, P0, Default"]},
                "network":{
                    "interfaces":[{
                        "device":"enp1s0f0np0","present":True,"driver":"mlx5_core",
                        "operstate":"up","carrier":"1","speed_mbps":"100000",
                        "duplex":"full","mtu":"9000","mac":"aa:bb",
                        "ipv4":["10.10.100.10/24"],"ethtool":{},
                    }],
                    "routes":{"available":True,"value":[{
                        "dst":"10.10.100.0/24","dev":"enp1s0f0np0",
                        "prefsrc":"10.10.100.10","scope":"link",
                    }]},
                },
                "storage":{
                    "mounts":{"findmnt":{"available":True,"value":{"filesystems":[{
                        "target":"/","source":"/dev/nvme0n1p2","fstype":"ext4",
                        "options":"rw","children":[],
                    }]}},"df":{}},
                    "lsblk":{"available":True,"value":{"blockdevices":[{
                        "name":"nvme0n1","type":"disk","size":"2T","model":"Spark",
                        "serial":"unique","tran":"nvme","children":[],
                    }]}},
                },
                "software":{
                    "packages":{"sha256":"same"},
                    "manual_packages":{"sha256":"same"},
                    "config_hashes":{
                        "/etc/ds4-node-rank":{"sha256":node_id},
                        "/etc/fstab":{"sha256":node_id},
                        "/etc/modprobe.d":{"sha256":"same"},
                    },
                },
            },
        }

    def test_normalization_ignores_identity_addresses(self):
        first = self.row("spark0")
        second = self.row("spark1")
        first["observed"]["network"]["interfaces"][0]["mac"] = "00:00"
        second["observed"]["network"]["interfaces"][0]["mac"] = "ff:ff"
        first["observed"]["network"]["interfaces"][0]["ipv4"] = ["10.10.100.10/24"]
        second["observed"]["network"]["interfaces"][0]["ipv4"] = ["10.10.100.11/24"]
        value_a = self.audit.normalize_field(first["observed"],"network.fabric_interfaces",("network","interfaces"))
        value_b = self.audit.normalize_field(second["observed"],"network.fabric_interfaces",("network","interfaces"))
        self.assertEqual(value_a,value_b)

    def test_expected_kernel_split_but_within_cohort_drift_fails(self):
        rows = [self.row("spark0"),self.row("spark1"),self.row("sparkd","6.18")]
        comparison = self.audit.compare(rows)
        self.assertEqual(comparison["fields"]["identity.kernel"]["status"],"expected_cohort_split")
        rows[1] = self.row("spark1","different")
        comparison = self.audit.compare(rows)
        self.assertIn("identity.kernel",comparison["unexpected_fields"])

    def test_config_comparison_ignores_node_role_files(self):
        rows = [self.row("spark0"),self.row("spark1")]
        comparison = self.audit.compare(rows)
        self.assertEqual(comparison["fields"]["software.config:/etc/modprobe.d"]["status"],"uniform")

    def test_route_source_is_not_a_fleet_drift(self):
        rows = [self.row("spark0"),self.row("spark1")]
        rows[1]["observed"]["network"]["routes"]["value"][0]["prefsrc"] = "10.10.100.11"
        comparison = self.audit.compare(rows)
        self.assertEqual(comparison["fields"]["network.routes"]["status"],"uniform")


if __name__ == "__main__":
    unittest.main()
