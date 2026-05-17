import json
import tempfile
import unittest
from pathlib import Path

from scripts import split_ds4_mtp_repeat_samples as split


def _lines() -> list[str]:
	return [
		"ds4: mtp bench phase=mtp command_sha256=sha256:cmd prompt_sha256=sha256:prompt perf_env_sha256=sha256:env perf_env_keys=DS4_MTP_BENCH_REPEATS,DS4_MTP_BENCH_WARMUP_REPEATS n_predict=126 mtp_draft=2 ctx=2048 seed=1234 spec_disabled=0",
		"ds4: mtp repeat warmup_begin index=1 count=1",
		"ds4: prefill: 0.50 t/s, generation: 9.00 t/s",
		"ds4: mtp repeat warmup_end index=1 count=1 exit_code=0",
		"ds4: mtp repeat sample_begin index=1 count=2",
		"ds4: prefill: 1.00 t/s, generation: 20.00 t/s",
		"ds4: mtp timing suffix2 drafted=2 committed=2 verify=1.0 target=1.0 verifier_calls=1 target_positions=3 target_calls=1 head_calls=1 head_rows=3 full_vocab_rows=1 top1_rows=2 draft_calls=2 emitted=3 total=2.0",
		"ds4: mtp sample_diag direct=1 draft=2 generated=126 emitted=126 serial_steps=0 pending_argmax_hits=0 pending_argmax_misses=0 suffix2_attempts=1 suffix2_full_accepts=1 suffix2_partial_accepts=0 suffix2_rejects=0 suffix2_tail_attempts=0 suffix2_tail_accepts=0 suffix2_tail_rejects=0 suffix2_fallbacks=0 suffix2_first_nonfull_seen=0 suffix2_first_nonfull_pos=0 suffix2_first_nonfull_kind=0 suffix2_first_nonfull_draft0=0 suffix2_first_nonfull_draft1=0 suffix2_first_nonfull_top0=0 suffix2_first_nonfull_top1=0 mtp_cache_advance_calls=1 first_target_calls=0 suffix_target_calls=1 target_positions=3 head_calls=1 full_vocab_rows=1 top1_rows=2 draft_calls=2",
		"ds4: mtp repeat sample_end index=1 count=2 exit_code=0",
		"ds4: mtp repeat sample_begin index=2 count=2",
		"ds4: prefill: 1.00 t/s, generation: 21.00 t/s",
		"ds4: mtp timing suffix2 drafted=2 committed=1 verify=1.0 target=1.0 verifier_calls=1 target_positions=3 target_calls=1 head_calls=1 head_rows=3 full_vocab_rows=1 top1_rows=2 draft_calls=2 emitted=2 total=2.0",
		"ds4: mtp sample_diag direct=1 draft=2 generated=126 emitted=126 serial_steps=0 pending_argmax_hits=0 pending_argmax_misses=0 suffix2_attempts=1 suffix2_full_accepts=0 suffix2_partial_accepts=1 suffix2_rejects=0 suffix2_tail_attempts=0 suffix2_tail_accepts=0 suffix2_tail_rejects=0 suffix2_fallbacks=0 suffix2_first_nonfull_seen=1 suffix2_first_nonfull_pos=40 suffix2_first_nonfull_kind=1 suffix2_first_nonfull_draft0=1 suffix2_first_nonfull_draft1=2 suffix2_first_nonfull_top0=1 suffix2_first_nonfull_top1=3 mtp_cache_advance_calls=1 first_target_calls=0 suffix_target_calls=1 target_positions=3 head_calls=1 full_vocab_rows=1 top1_rows=2 draft_calls=2",
		"ds4: mtp repeat sample_end index=2 count=2 exit_code=0",
	]


class Ds4MtpRepeatSamplesTest(unittest.TestCase):
	def test_split_repeat_samples_by_marker(self) -> None:
		samples = split.split_repeat_samples(_lines(), 2)
		self.assertEqual(sorted(samples), [1, 2])
		self.assertIn("command_sha256=sha256:cmd", samples[1][0])
		self.assertTrue(any("generation: 21.00" in line for line in samples[2]))

	def test_write_split_samples_extracts_per_sample_summary(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			report = split.write_split_samples(_lines(), Path(tmp), 2)
			self.assertEqual(report["sample_count"], 2)
			first = json.loads((Path(tmp) / "sample-001" / "acceptance_summary.json").read_text(encoding="utf-8"))
			second = json.loads((Path(tmp) / "sample-002" / "acceptance_summary.json").read_text(encoding="utf-8"))
		self.assertEqual(first["speed"]["generation_tps"], 20.0)
		self.assertEqual(second["speed"]["generation_tps"], 21.0)
		self.assertEqual(first["sample_diag"]["suffix2_full_accepts"], 1.0)
		self.assertEqual(second["sample_diag"]["suffix2_partial_accepts"], 1.0)

	def test_missing_sample_blocks(self) -> None:
		with self.assertRaises(ValueError):
			split.split_repeat_samples(_lines()[:-1], 2)


if __name__ == "__main__":
	unittest.main()
