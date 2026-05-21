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
			"pipeline_session_step",
			"DS4_PIPELINE_SESSION_TOKEN_OUT_FILE",
			"metal_graph_encode_decode_layer",
			"pipeline_emit_output_head",
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

	def test_stage0_probe_command_uses_canonical_prompt_token_file(self) -> None:
		session = ps.PipelineSession(stages=ps.default_stages())
		cmd = session.build_stage_probe_command(ps.default_stages()[0], "run", 0, "/tmp/prompt.bin", None, "/tmp/stage0_out_%u.bin", 16)
		self.assertIn("DS4_CUDA_STACK_PROBE_EMBED_INPUT=1", cmd)
		self.assertIn("DS4_CUDA_MOE_SLICE_TILE8=1", cmd)
		self.assertIn("DS4_CUDA_SKIP_STARTUP_MODEL_CACHE=1", cmd)
		self.assertIn("DS4_CUDA_STACK_PROBE_PRELOAD_STAGE=1", cmd)
		self.assertIn("--cuda-batch-stack-probe", cmd)
		self.assertIn("--cuda-moe-tokens 16", cmd)
		self.assertIn("--cuda-moe-iters 1", cmd)
		self.assertIn("--ctx 128", cmd)
		self.assertIn("--prompt-tokens-file /tmp/prompt.bin", cmd)
		self.assertNotIn("--emit-output-head-argmax", cmd)
		self.assertNotIn("DS4_CUDA_STACK_PROBE_BATCH_HEAD=1", cmd)

	def test_stage2_probe_command_uses_single_row_head_argmax(self) -> None:
		session = ps.PipelineSession(stages=ps.default_stages())
		cmd = session.build_stage_probe_command(ps.default_stages()[2], "run", 0, "/tmp/prompt.bin", "/tmp/stage2_in_%u.bin", None, 17)
		self.assertIn("DS4_CUDA_STACK_PROBE_INPUT_HC_FILE=/tmp/stage2_in_%u.bin", cmd)
		self.assertIn("--cuda-moe-tokens 17", cmd)
		self.assertIn("--emit-output-head-argmax", cmd)
		self.assertNotIn("--prompt-tokens-file", cmd)
		self.assertNotIn("DS4_CUDA_STACK_PROBE_BATCH_HEAD=1", cmd)
		self.assertNotIn("DS4_CUDA_STACK_PROBE_NO_HEAD=1", cmd)

	def test_session_worker_command_keeps_resident_decode_state(self) -> None:
		session = ps.PipelineSession(stages=ps.default_stages())
		cmd = session.build_session_worker_command(ps.default_stages()[2], "run", "/tmp/run/prompt.bin", 8)
		self.assertIn("--pipeline-session-b1-worker", cmd)
		self.assertIn("DS4_PIPELINE_SESSION_PROMPT_TOKENS_FILE=/tmp/run/prompt.bin", cmd)
		self.assertIn("DS4_PIPELINE_SESSION_TOKEN_OUT_FILE=", cmd)
		self.assertIn("DS4_CUDA_STACK_PROBE_LAYER_BEGIN=29", cmd)
		self.assertIn("DS4_CUDA_STACK_PROBE_LAYER_END=43", cmd)
		self.assertNotIn("--cuda-batch-stack-probe", cmd)

	def test_same_host_handoff_skips_tcp_listener(self) -> None:
		stage = ps.StageConfig(0, "s", "spark1", "/d", "/m", 0, 1, False)
		session = ps.PipelineSession(stages=[stage, dataclasses.replace(stage, stage_id=1)])
		with tempfile.TemporaryDirectory() as d:
			item = session.tcp_transfer_file(stage, stage, "/tmp/a", "/tmp/a", 19000, Path(d), "same")
		self.assertEqual(item["transfer_kind"], "same_host_file")

	def test_pp3_worker_steps_require_real_stage_events(self) -> None:
		session = ps.PipelineSession(stages=ps.default_stages())
		events = {
			0: [{"event": "pipeline_session_step", "step": 0, "hc_or_logits_fnv64": "1", "nonfinite": 0}],
			1: [{"event": "pipeline_session_step", "step": 0, "hc_or_logits_fnv64": "2", "nonfinite": 0}],
			2: [
				{"event": "pipeline_session_step", "step": 0, "hc_or_logits_fnv64": "3", "nonfinite": 0},
				{"event": "pipeline_session_token", "step": 0, "token_bytes": [52]},
			],
		}
		steps = session.build_session_steps(events, [20])
		self.assertEqual(steps[0].stage_logits_hashes, ["fnv64:1", "fnv64:2", "fnv64:3"])
		self.assertEqual(steps[0].text, "4")

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
