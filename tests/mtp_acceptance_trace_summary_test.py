import unittest

from scripts import summarize_mtp_acceptance_trace as summ


class MtpAcceptanceTraceSummaryTest(unittest.TestCase):
	def test_summarize_accept_len(self) -> None:
		lines = [
			'{"mtp_accept_len": 1}\n',
			'{"mtp_accept_len": 3}\n',
			'{"mtp_accept_len": 2}\n',
		]
		res = summ.summarize_mtp_acceptance_jsonl(lines, draft_len=2, allow_substrings=False)
		self.assertTrue(bool(res.get("ok", False)))
		self.assertEqual(int(res.get("records")), 3)
		self.assertEqual(int(res.get("events")), 3)
		self.assertEqual(res.get("mtp_accept_len", {}).get("min"), 1)
		self.assertEqual(res.get("mtp_accept_len", {}).get("max"), 3)
		h = res.get("mtp_accept_len_hist") or {}
		self.assertEqual(h.get("draft_len"), 2)
		self.assertEqual(h.get("counts"), [1, 1, 1])
		self.assertAlmostEqual(float(res.get("acceptance_rate")), (0.0 + 1.0 + 2.0) / 3.0 / 2.0)

	def test_summarize_accepted_mtp_fallback(self) -> None:
		lines = ['{"accepted_mtp": 0}\n', '{"accepted_mtp": 2}\n']
		res = summ.summarize_mtp_acceptance_jsonl(lines, draft_len=3, allow_substrings=False)
		self.assertTrue(bool(res.get("ok", False)))
		accept = res.get("mtp_accept_len") or {}
		self.assertEqual(accept.get("min"), 1)
		self.assertEqual(accept.get("max"), 3)

	def test_summarize_scans_embedded_json(self) -> None:
		lines = [
			"INFO step=0 route={\"mtp_accept_len\":2} done\n",
			"plain text\n",
		]
		res = summ.summarize_mtp_acceptance_jsonl(lines, draft_len=1, allow_substrings=True)
		self.assertTrue(bool(res.get("ok", False)))
		self.assertEqual(int(res.get("records")), 1)
		self.assertEqual(int(res.get("events")), 1)
		self.assertEqual(res.get("mtp_accept_len", {}).get("p50"), 2)

