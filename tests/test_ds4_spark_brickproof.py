import importlib.util
import base64
from pathlib import Path
import struct
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ds4_spark_brickproof.py"
ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ds4_spark_brickproof",SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class BrickproofTest(unittest.TestCase):
    RECOVERY = {
        "address":"10.20.0.12",
        "gateway":"10.20.0.1",
        "interface":"enP7s7",
        "netmask":"255.255.255.0",
        "node_id":"spark2",
    }

    def test_grub_policy_preserves_recovery_network_and_serial(self) -> None:
        source = 'GRUB_DEFAULT="ds4-fastboot"\nGRUB_CMDLINE_LINUX_DEFAULT="quiet ip=10.20.0.12::10.20.0.1:255.255.255.0:spark2:enP7s7:none console=tty0 console=ttyS0,921600n8"\n'
        result = MODULE.canonical_grub(source,self.RECOVERY)
        self.assertEqual(MODULE.shell_assignment(result,"GRUB_DEFAULT"),"0")
        tokens = MODULE.shell_assignment(result,"GRUB_CMDLINE_LINUX_DEFAULT").split()
        self.assertIn("fsck.mode=skip",tokens)
        self.assertIn("fsck.repair=no",tokens)
        self.assertTrue(any(token.startswith("ip=") for token in tokens))
        self.assertTrue(any(token.startswith("console=ttyS0") for token in tokens))

    def test_grub_policy_repairs_unrecoverable_entry(self) -> None:
        result = MODULE.canonical_grub('GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"\n',self.RECOVERY)
        tokens = MODULE.shell_assignment(result,"GRUB_CMDLINE_LINUX_DEFAULT").split()
        self.assertIn("console=tty0",tokens)
        self.assertIn("console=ttyS0,921600",tokens)
        self.assertIn(MODULE.recovery_ip_token(self.RECOVERY),tokens)

    def test_grub_policy_is_idempotent(self) -> None:
        source = 'GRUB_DEFAULT=0\nGRUB_CMDLINE_LINUX_DEFAULT="ip=dhcp console=ttyS0 fsck.mode=force fsck.repair=yes"\n'
        once = MODULE.canonical_grub(source,self.RECOVERY)
        self.assertEqual(MODULE.canonical_grub(once,self.RECOVERY),once)
        tokens = MODULE.shell_assignment(once,"GRUB_CMDLINE_LINUX_DEFAULT").split()
        self.assertEqual(tokens.count("fsck.mode=skip"),1)
        self.assertEqual(tokens.count("fsck.repair=no"),1)

    def test_recovery_network_uses_uplink_plan(self) -> None:
        self.assertEqual(MODULE.recovery_network_for_node("spark8"),{
            "address":"10.20.0.18",
            "gateway":"10.20.0.1",
            "interface":"enP7s7",
            "netmask":"255.255.255.0",
            "node_id":"spark8",
        })

    @staticmethod
    def public_key_blob(seed: int) -> str:
        key_type = b"ssh-ed25519"
        payload = struct.pack(">I",len(key_type)) + key_type + bytes([seed]) * 32
        return(base64.b64encode(payload).decode("ascii"))

    def test_public_key_repair_recovers_split_keys_and_deduplicates(self) -> None:
        first = self.public_key_blob(1)
        second = self.public_key_blob(2)
        required = f"ssh-ed25519 {self.public_key_blob(3)} recovery"
        corrupt = f"ssh-ed25519 {first} ceph-anssh-ed25519\n{second}\nceph-b\nssh-ed25519 {first} duplicate\n"
        once = MODULE.canonical_authorized_keys(corrupt,required)
        twice = MODULE.canonical_authorized_keys(once,required)
        self.assertEqual(once,twice)
        self.assertEqual(once.splitlines(),[
            f"ssh-ed25519 {first}",
            f"ssh-ed25519 {second}",
            " ".join(required.split()[:2]),
        ])

    def test_public_key_repair_preserves_options_and_ignores_comments(self) -> None:
        restricted_blob = self.public_key_blob(4)
        comment_blob = self.public_key_blob(5)
        required = f"ssh-ed25519 {self.public_key_blob(6)} recovery"
        restricted = f'from="10.20.0.0/24",no-agent-forwarding ssh-ed25519 {restricted_blob} ceph'
        source = f"# ssh-ed25519 {comment_blob} disabled\n{restricted}\n"
        result = MODULE.canonical_authorized_keys(source,required)
        self.assertEqual(result.splitlines(),[
            restricted,
            " ".join(required.split()[:2]),
        ])

    def test_efi_boot_order_moves_pxe_before_ubuntu(self) -> None:
        source = """BootCurrent: 0007
BootOrder: 0007,0005
Boot0005* UEFI: PXE IPv4 Realtek PCIe 10 GBE Family Controller
Boot0007* ubuntu HD(1,GPT,abc)
"""
        self.assertEqual(MODULE.desired_efi_boot_order(source),["0005","0007"])

    def test_efi_boot_order_moves_pxe_before_dgx_os(self) -> None:
        source = """BootCurrent: 0000
BootOrder: 0000,0002,0003
Boot0000* DGX OS HD(1,GPT,abc)
Boot0002* UEFI: PXE IPv4 Realtek PCIe 10 GBE Family Controller
Boot0003* UEFI:CD/DVD Drive
"""
        self.assertEqual(MODULE.desired_efi_boot_order(source),["0002","0000","0003"])

    def test_efi_boot_order_requires_pxe_ipv4(self) -> None:
        source = """BootOrder: 0001,0002
Boot0001* ubuntu HD(1,GPT,abc)
Boot0002* UEFI:CD/DVD Drive
"""
        with self.assertRaises(MODULE.BrickproofError):
            MODULE.desired_efi_boot_order(source)

    def test_efi_boot_order_rejects_ambiguous_linux_entries(self) -> None:
        source = """BootOrder: 0001,0002
Boot0001* ubuntu HD(1,GPT,abc)
Boot0002* ubuntu HD(1,GPT,def)
"""
        with self.assertRaises(MODULE.BrickproofError):
            MODULE.desired_efi_boot_order(source)

    def test_atomic_write_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.conf"
            self.assertTrue(MODULE.atomic_write(path,"value\n",0o600))
            self.assertFalse(MODULE.atomic_write(path,"value\n",0o600))
            self.assertEqual(path.stat().st_mode & 0o777,0o600)

    def test_fabric_services_are_bounded_and_not_boot_critical(self) -> None:
        for name in ("ds4-switched-fabric","ds4-direct-pair-fabric"):
            service = (ROOT / "deploy" / "systemd" / f"{name}.service").read_text()
            timer = (ROOT / "deploy" / "systemd" / f"{name}.timer").read_text()
            self.assertIn("TimeoutStartSec=60",service)
            self.assertNotIn("Before=network-online.target",service)
            self.assertNotIn("WantedBy=multi-user.target",service)
            self.assertIn("WantedBy=timers.target",timer)

    def test_switched_fabric_runtime_only_applies_local_fabric(self) -> None:
        source = (ROOT / "scripts" / "ds4_switched_fabric_apply.sh").read_text()
        runtime = source.rsplit("\nfi\n",1)[1].strip()
        self.assertEqual(runtime,"apply_switched_fabric")
        install = source.split('if [ "${1:-}" = "--install" ]; then',1)[1].split("\nfi\n",1)[0]
        self.assertIn("configure_management_link",install)
        self.assertIn("retire_legacy_mac_mounts",install)

    def test_apply_restarts_emergency_ssh_and_always_rebuilds_initramfs(self) -> None:
        source = SCRIPT.read_text()
        self.assertIn('run(["systemctl","restart","ssh-emergency.service"])',source)
        self.assertIn('run(["update-initramfs","-u"],timeout=600)',source)
        self.assertIn('line.endswith("/.ssh/authorized_keys")',source)

    def test_persistent_unit_links_only_returns_dependency_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unit = root / "ds4-test.service"
            unit.write_text("[Service]\nExecStart=/bin/true\n")
            wants = root / "multi-user.target.wants"
            wants.mkdir()
            link = wants / unit.name
            link.symlink_to(unit)
            self.assertEqual(MODULE.persistent_unit_links(unit.name,root),[link])


if __name__ == "__main__":
    unittest.main()
