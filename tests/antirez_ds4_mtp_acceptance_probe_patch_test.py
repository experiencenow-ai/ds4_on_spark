import unittest
from pathlib import Path


SCRIPT = Path("scripts/antirez_ds4_mtp_acceptance_probe_patch.sh")


class AntirezDs4MtpAcceptanceProbePatchTest(unittest.TestCase):
	def test_conf_log_zero_unsets_env_for_c_getenv(self) -> None:
		text = SCRIPT.read_text(encoding="utf-8")
		self.assertIn('if [ "$DS4_MTP_CONF_LOG" = "0" ]; then', text)
		self.assertIn("unset DS4_MTP_CONF_LOG", text)
		self.assertIn("export DS4_MTP_CONF_LOG", text)

	def test_measured_mode_defaults_logging_and_timing_off(self) -> None:
		text = SCRIPT.read_text(encoding="utf-8")
		self.assertIn('DS4_MTP_MEASURED_MODE="${DS4_MTP_MEASURED_MODE:-0}"', text)
		self.assertIn('if [ "$DS4_MTP_MEASURED_MODE" = "1" ]; then', text)
		self.assertIn('DS4_MTP_CONF_LOG="${DS4_MTP_CONF_LOG:-0}"', text)
		self.assertIn('DS4_MTP_TIMING="${DS4_MTP_TIMING:-0}"', text)
		self.assertIn('"DS4_MTP_MEASURED_MODE"', text)


if __name__ == "__main__":
	unittest.main()
