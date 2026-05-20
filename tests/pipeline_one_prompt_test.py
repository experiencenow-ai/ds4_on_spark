import dataclasses
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
			"pipeline_argmax_token",
			"batch_head",
			"host_committed[n_tokens - 1u]",
		]:
			self.assertIn(needle, text)
		self.assertNotIn("ds4_pipeline_stage_", text)

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

	def test_stage0_probe_command_uses_row_token_embedding_input(self) -> None:
		session = ps.PipelineSession(stages=ps.default_stages())
		cmd = session.build_stage_probe_command(ps.default_stages()[0], "run", 0, [128822], None, "/tmp/b01.bin")
		self.assertIn("DS4_CUDA_STACK_PROBE_EMBED_INPUT=1", cmd)
		self.assertIn("DS4_CUDA_STACK_PROBE_ROW_TOKEN_IDS=128822,0,0,0", cmd)
		self.assertIn("--cuda-batch-stack-probe", cmd)
		self.assertIn("--cuda-moe-tokens 4", cmd)
		self.assertNotIn("DS4_CUDA_STACK_PROBE_BATCH_HEAD=1", cmd)

	def test_stage2_probe_command_uses_single_row_head_argmax(self) -> None:
		session = ps.PipelineSession(stages=ps.default_stages())
		cmd = session.build_stage_probe_command(ps.default_stages()[2], "run", 0, [7] * 16, "/tmp/b12.bin", None)
		self.assertIn("DS4_CUDA_STACK_PROBE_INPUT_HC_FILE=/tmp/b12.bin", cmd)
		self.assertIn("--cuda-moe-tokens 16", cmd)
		self.assertNotIn("DS4_CUDA_STACK_PROBE_BATCH_HEAD=1", cmd)
		self.assertNotIn("DS4_CUDA_STACK_PROBE_NO_HEAD=1", cmd)

	def test_same_host_handoff_skips_tcp_listener(self) -> None:
		stage = ps.StageConfig(0, "s", "spark1", "/d", "/m", 0, 1, False)
		session = ps.PipelineSession(stages=[stage, dataclasses.replace(stage, stage_id=1)])
		with tempfile.TemporaryDirectory() as d:
			item = session.tcp_transfer_file(stage, stage, "/tmp/a", "/tmp/a", 19000, Path(d), "same", 4)
		self.assertEqual(item["transfer_kind"], "same_host_file")

	def test_missing_probe_hook_blocks_pp3(self) -> None:
		def runner(stage, command, ssh_config, known_hosts, timeout_s):
			if "--dump-tokens" in command:
				return ps.CommandResult(["ssh"], 0, "[1, 2, 3]\n", "")
			return ps.CommandResult(["ssh"], 0, "Usage: ds4\n", "")
		session = ps.PipelineSession(stages=ps.default_stages(), runner=runner)
		with tempfile.TemporaryDirectory() as d:
			with self.assertRaises(ps.PipelineSessionError) as cm:
				session.run_pp3("what is 2+2?", 8, Path(d))
		self.assertIn("missing_cuda_batch_stack_probe", str(cm.exception))

	def test_decode_step_validation_requires_all_stage_hashes(self) -> None:
		step = ps.GeneratedStep(0, 42, "4", [52], ["fnv64:1", "fnv64:2"], [0, 0])
		with self.assertRaises(ps.PipelineSessionError):
			ps.validate_decode_steps([step], stage_count=3)
		good = ps.GeneratedStep(0, 42, "4", [52], ["fnv64:1", "fnv64:2", "fnv64:3"], [0, 0, 0])
		ps.validate_decode_steps([good], stage_count=3)

	def test_pp1_pp3_mismatch_is_rejected(self) -> None:
		with self.assertRaises(ps.PipelineSessionError):
			ps.assert_matching_token_prefix([1, 2, 3], [1, 9, 3], 3)

	def test_committed_token_prefers_pipeline_argmax(self) -> None:
		session = ps.PipelineSession(stages=ps.default_stages())
		self.assertEqual(session.committed_token({"pipeline_argmax_token": 22, "committed_token_ids": [99]}), 22)
		self.assertEqual(session.committed_token({"committed_token_ids": [11, 22]}), 22)


if __name__ == "__main__":
	unittest.main()
