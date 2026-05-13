import os
import unittest

from scripts import verify_antirez_ds4_q4k_dot_math as q4k


class Q4KLlamaCppFixtureTest(unittest.TestCase):
	def test_llamacpp_fixture_matches(self) -> None:
		path = "fixtures/quant/q4k_llamacpp_b9110_rowdot_fixture.json"
		if not os.path.exists(path):
			self.skipTest(f"missing fixture: {path}")
		try:
			q4k.run_llamacpp_fixture(path)
		except SystemExit as e:
			self.fail(f"fixture mismatch: {e}")

