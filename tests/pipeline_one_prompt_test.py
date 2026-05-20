import json
import tempfile
import unittest
from pathlib import Path

from scripts import pipeline_session as ps

PATCH = Path("docs/antirez-patches/ds4-3630e64-cuda-pipeline-session-b1.patch")


class PipelineOnePromptTest(unittest.TestCase):
	def test_pipeline_session_patch_exposes_real_session_ops(self) -> None:
		text = PATCH.read_text(encoding="utf-8")
		for needle in [
			"--pipeline-session-b1-worker",
			"ds4_pipeline_stage_prefill_chunk",
			"ds4_pipeline_stage_decode_one",
			"ds4_session_sync(p->session",
			"ds4_session_eval(p->session",
			"ds4_session_argmax(p->session)",
			"logits_fnv64",
		]:
			self.assertIn(needle, text)

	def test_rendered_prompt_uses_ds4_chat_markers(self) -> None:
		rendered = ps.render_chat_prompt("what is 2+2?", think=False)
		self.assertTrue(rendered.startswith(ps.BOS))
		self.assertIn(ps.USER + "what is 2+2?" + ps.ASSISTANT + ps.NO_THINK, rendered)

	def test_parse_logprob_dump_extracts_ids_and_text(self) -> None:
		raw = json.dumps({
			"steps": [
				{"step": 0, "selected": {"id": 10, "text": " ", "bytes": [32]}},
				{"step": 1, "selected": {"id": 20, "text": "4", "bytes": [52]}},
			]
		})
		ids, text, steps = ps.parse_logprob_dump(raw)
		self.assertEqual(ids, [10, 20])
		self.assertEqual(text, " 4")
		self.assertEqual([s.token_id for s in steps], [10, 20])

	def test_prefill_payload_has_only_row0_real_tokens(self) -> None:
		payload = ps.make_prefill_payload([1, 2, 3], batch_size=512)
		self.assertEqual(payload["real_row"], 0)
		self.assertEqual(payload["row0_token_ids"], [1, 2, 3])
		self.assertEqual(payload["padding_rows"], 511)
		self.assertEqual(payload["padding_token_id"], 0)

	def test_missing_worker_hook_blocks_pp3(self) -> None:
		def runner(stage, command, ssh_config, known_hosts, timeout_s):
			if "--dump-tokens" in command:
				return ps.CommandResult(["ssh"], 0, "[1, 2, 3]\n", "")
			return ps.CommandResult(["ssh"], 0, "Usage: ds4\n", "")
		session = ps.PipelineSession(stages=ps.default_stages(), runner=runner)
		with tempfile.TemporaryDirectory() as d:
			with self.assertRaises(ps.PipelineSessionError) as cm:
				session.run_pp3("what is 2+2?", 8, Path(d))
		self.assertIn("missing_pipeline_session_worker", str(cm.exception))

	def test_decode_step_validation_requires_all_stage_hashes(self) -> None:
		step = ps.GeneratedStep(0, 42, "4", [52], ["fnv64:1", "fnv64:2"], [0, 0])
		with self.assertRaises(ps.PipelineSessionError):
			ps.validate_decode_steps([step], stage_count=3)
		good = ps.GeneratedStep(0, 42, "4", [52], ["fnv64:1", "fnv64:2", "fnv64:3"], [0, 0, 0])
		ps.validate_decode_steps([good], stage_count=3)

	def test_pp1_pp3_mismatch_is_rejected(self) -> None:
		with self.assertRaises(ps.PipelineSessionError):
			ps.assert_matching_token_prefix([1, 2, 3], [1, 9, 3], 3)


if __name__ == "__main__":
	unittest.main()
