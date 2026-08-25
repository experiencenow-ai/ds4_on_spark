import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ds4_spark_brickproof.py"
SPEC = importlib.util.spec_from_file_location("ds4_spark_brickproof",SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class BrickproofTest(unittest.TestCase):
    def test_grub_policy_preserves_recovery_network_and_serial(self) -> None:
        source = 'GRUB_DEFAULT="ds4-fastboot"\nGRUB_CMDLINE_LINUX_DEFAULT="quiet ip=10.20.0.12::10.20.0.1:255.255.255.0:spark2:enP7s7:none console=tty0 console=ttyS0,921600n8"\n'
        result = MODULE.canonical_grub(source)
        self.assertEqual(MODULE.shell_assignment(result,"GRUB_DEFAULT"),"0")
        tokens = MODULE.shell_assignment(result,"GRUB_CMDLINE_LINUX_DEFAULT").split()
        self.assertIn("fsck.mode=skip",tokens)
        self.assertIn("fsck.repair=no",tokens)
        self.assertTrue(any(token.startswith("ip=") for token in tokens))
        self.assertTrue(any(token.startswith("console=ttyS0") for token in tokens))

    def test_grub_policy_rejects_unrecoverable_entry(self) -> None:
        with self.assertRaises(MODULE.BrickproofError):
            MODULE.canonical_grub('GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"\n')

    def test_grub_policy_is_idempotent(self) -> None:
        source = 'GRUB_DEFAULT=0\nGRUB_CMDLINE_LINUX_DEFAULT="ip=dhcp console=ttyS0 fsck.mode=force fsck.repair=yes"\n'
        once = MODULE.canonical_grub(source)
        self.assertEqual(MODULE.canonical_grub(once),once)
        tokens = MODULE.shell_assignment(once,"GRUB_CMDLINE_LINUX_DEFAULT").split()
        self.assertEqual(tokens.count("fsck.mode=skip"),1)
        self.assertEqual(tokens.count("fsck.repair=no"),1)

    def test_public_key_merge_preserves_keys_and_deduplicates(self) -> None:
        old = "ssh-ed25519 AAAAold operator\n"
        new = "ssh-ed25519 AAAAnew recovery"
        once = MODULE.merge_public_key(old,new)
        twice = MODULE.merge_public_key(once,new)
        self.assertEqual(once,twice)
        self.assertIn(old.strip(),once)
        self.assertIn(new,once)

    def test_atomic_write_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.conf"
            self.assertTrue(MODULE.atomic_write(path,"value\n",0o600))
            self.assertFalse(MODULE.atomic_write(path,"value\n",0o600))
            self.assertEqual(path.stat().st_mode & 0o777,0o600)


if __name__ == "__main__":
    unittest.main()
