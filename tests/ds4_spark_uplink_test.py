#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "ds4_spark_uplink.py"
SPEC = importlib.util.spec_from_file_location("ds4_spark_uplink",MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import ds4_spark_uplink")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SparkUplinkPlanTest(unittest.TestCase):
    def test_current_and_future_hex_rank_addresses_are_stable(self) -> None:
        expected = {
            "spark0": (0,"10.20.0.10/24","192.168.50.128/24"),
            "sparkc": (12,"10.20.0.22/24","192.168.50.140/24"),
            "sparkf": (15,"10.20.0.25/24","192.168.50.143/24"),
            "spark10": (16,"10.20.0.26/24","192.168.50.144/24"),
            "spark1c": (28,"10.20.0.38/24","192.168.50.156/24"),
        }
        for node_id,(rank,management,wired) in expected.items():
            plan = MODULE.plan_for_node(node_id)
            self.assertEqual(plan.rank,rank)
            self.assertEqual(plan.management_cidr,management)
            self.assertEqual(plan.asus_wired_cidr,wired)

    def test_static_ranges_do_not_overlap_dhcp_or_mac(self) -> None:
        addresses = set()
        for rank in range(32):
            plan = MODULE.plan_for_node(f"spark{rank:x}")
            octet = int(plan.asus_wired_address.rsplit(".",1)[1])
            self.assertGreaterEqual(octet,128)
            self.assertLessEqual(octet,159)
            self.assertNotEqual(plan.asus_wired_address,MODULE.MAC_STATIC_ADDRESS)
            self.assertNotIn(plan.asus_wired_address,addresses)
            addresses.add(plan.asus_wired_address)

    def test_plan_round_trip_preserves_priority_contract(self) -> None:
        plan = MODULE.plan_for_node("spark8")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(MODULE.plan_to_json(plan),encoding="utf-8")
            loaded = MODULE.load_plan(path)
        self.assertEqual(loaded,plan)
        self.assertLess(loaded.wired_metric,loaded.asus_metric)
        self.assertLess(loaded.asus_metric,loaded.tplink_metric)

    def test_plan_json_never_contains_wifi_secret(self) -> None:
        payload = json.loads(MODULE.plan_to_json(MODULE.plan_for_node("spark0")))
        self.assertNotIn("psk",payload)
        self.assertEqual(payload["asus_psk_file"],"/etc/ds4-uplink/asus.psk")

    def test_invalid_or_out_of_range_node_fails_closed(self) -> None:
        for node_id in ("spark","spark-g","node0","spark79"):
            with self.assertRaises(MODULE.UplinkError):
                MODULE.plan_for_node(node_id)


class SparkUplinkMonitorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = MODULE.plan_for_node("spark0")
        self.runner = object()
        self.temporary = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_wired_path_is_selected_before_wifi(self) -> None:
        with (
            mock.patch.object(MODULE,"require_root"),
            mock.patch.object(MODULE,"wired_probe",return_value=True),
            mock.patch.object(MODULE,"set_wired_default") as set_default,
            mock.patch.object(MODULE,"ensure_asus_standby") as standby,
        ):
            MODULE.monitor_uplink(self.runner,self.plan,self.state_dir)
        set_default.assert_called_once_with(self.runner,self.plan,True)
        standby.assert_called_once()
        self.assertEqual((self.state_dir / "path").read_text().strip(),"wired")

    def test_asus_is_selected_when_wired_fails(self) -> None:
        with (
            mock.patch.object(MODULE,"require_root"),
            mock.patch.object(MODULE,"wired_probe",return_value=False),
            mock.patch.object(MODULE,"set_wired_default") as set_default,
            mock.patch.object(MODULE,"current_wifi_profile",return_value=self.plan.asus_profile),
            mock.patch.object(MODULE,"interface_probe",return_value=True),
            mock.patch.object(MODULE,"activate_wifi") as activate,
        ):
            MODULE.monitor_uplink(self.runner,self.plan,self.state_dir)
        set_default.assert_called_once_with(self.runner,self.plan,False)
        activate.assert_not_called()
        self.assertEqual((self.state_dir / "path").read_text().strip(),"asus_wifi")

    def test_tplink_is_used_only_after_asus_fails(self) -> None:
        activations = []

        def activate(_runner: object,_plan: object,profile: str) -> bool:
            activations.append(profile)
            return(profile == self.plan.tplink_profile)

        with (
            mock.patch.object(MODULE,"require_root"),
            mock.patch.object(MODULE,"wired_probe",return_value=False),
            mock.patch.object(MODULE,"set_wired_default"),
            mock.patch.object(MODULE,"current_wifi_profile",return_value=""),
            mock.patch.object(MODULE,"activate_wifi",side_effect=activate),
            mock.patch.object(MODULE,"interface_probe",return_value=True),
        ):
            MODULE.monitor_uplink(self.runner,self.plan,self.state_dir)
        self.assertEqual(activations,[self.plan.asus_profile,self.plan.tplink_profile])
        self.assertEqual((self.state_dir / "path").read_text().strip(),"tplink_wifi")


if __name__ == "__main__":
    unittest.main()
