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
            "spark1f": (31,"10.20.0.41/24","192.168.50.159/24"),
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


class SparkUplinkRunnerTest(unittest.TestCase):
    def test_nmcli_retries_after_networkmanager_restart(self) -> None:
        failed = MODULE.subprocess.CompletedProcess(
            ["nmcli","general"],
            1,
            "",
            "Error: NetworkManager is not running.",
        )
        passed = MODULE.subprocess.CompletedProcess(
            ["nmcli","general"],0,"running\n",""
        )
        with (
            mock.patch.object(MODULE.subprocess,"run",side_effect=[failed,passed]) as run,
            mock.patch.object(MODULE.time,"sleep") as sleep,
        ):
            result = MODULE.Runner().run(["nmcli","general"],check=False)
        self.assertEqual(result.returncode,0)
        self.assertEqual(run.call_count,2)
        sleep.assert_called_once_with(MODULE.NMCLI_RECOVERY_INTERVAL_SECONDS)

    def test_nmcli_does_not_retry_normal_activation_failure(self) -> None:
        failed = MODULE.subprocess.CompletedProcess(
            ["nmcli","con","up"],
            4,
            "",
            "Error: Connection activation failed: SSID not found.",
        )
        with (
            mock.patch.object(MODULE.subprocess,"run",return_value=failed) as run,
            mock.patch.object(MODULE.time,"sleep") as sleep,
        ):
            result = MODULE.Runner().run(["nmcli","con","up"],check=False)
        self.assertEqual(result.returncode,4)
        run.assert_called_once()
        sleep.assert_not_called()


class SparkUplinkActivationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = MODULE.plan_for_node("spark0")
        self.runner = mock.Mock()

    def test_in_progress_asus_activation_is_not_restarted(self) -> None:
        with (
            mock.patch.object(
                MODULE,"current_wifi_profile",return_value=self.plan.asus_profile
            ),
            mock.patch.object(MODULE,"wait_for_wifi_profile",return_value=True) as wait,
        ):
            MODULE.ensure_asus_active(self.runner,self.plan,"asus-uuid")
        self.runner.run.assert_not_called()
        wait.assert_called_once_with(
            self.runner,
            self.plan,
            self.plan.asus_profile,
            MODULE.WIFI_ACTIVATION_SECONDS,
        )

    def test_inactive_asus_profile_gets_one_bounded_activation(self) -> None:
        result = MODULE.subprocess.CompletedProcess(["nmcli"],0,""," ")
        self.runner.run.return_value = result
        with (
            mock.patch.object(
                MODULE,"current_wifi_profile",return_value=self.plan.tplink_profile
            ),
            mock.patch.object(MODULE,"wait_for_wifi_profile",return_value=True),
        ):
            MODULE.ensure_asus_active(self.runner,self.plan,"asus-uuid")
        self.runner.run.assert_called_once_with([
            "nmcli","--wait",str(MODULE.WIFI_ACTIVATION_SECONDS),
            "con","up","uuid","asus-uuid","ifname",self.plan.wifi_interface,
        ],check=False,timeout=MODULE.WIFI_ACTIVATION_SECONDS + 10)


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
