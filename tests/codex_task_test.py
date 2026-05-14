import unittest

from scripts import codex_task


class CodexTaskTest(unittest.TestCase):
	def test_expected_tasks_are_registered(self) -> None:
		parser = codex_task.build_parser()
		subparsers = next(action for action in parser._actions if action.dest == "task")
		self.assertEqual(
			set(subparsers.choices),
			{
				"analyze-moe-log",
				"automation-status",
				"mtp-local-verify",
				"pr-status",
				"repo-status",
				"spark-antirez-oracle",
				"spark-llamacpp-mtp-probe",
				"spark-resident-batched-decode",
				"spark-ring-status",
			},
		)

	def test_antirez_remote_env_quotes_prompt_and_defaults_to_run(self) -> None:
		parser = codex_task.build_parser()
		args = parser.parse_args([
			"spark-antirez-oracle",
			"--prompt",
			"hello there",
			"--ctx",
			"128",
			"--seed",
			"7",
		])
		env = codex_task.build_antirez_remote_env(args)
		self.assertIn("PROMPT='hello there'", env)
		self.assertIn("CTX=128", env)
		self.assertIn("SEED=7", env)
		self.assertIn("ALLOW_RUN=1", env)
		self.assertNotIn("ALLOW_FETCH=1", env)

	def test_llamacpp_remote_env_quotes_prompt_and_weight_gate(self) -> None:
		parser = codex_task.build_parser()
		args = parser.parse_args([
			"spark-llamacpp-mtp-probe",
			"--prompt",
			"hello there",
			"--load-sidecar-weights",
			"--fresh",
		])
		env = codex_task.build_llamacpp_remote_env(args)
		self.assertIn("PROMPT='hello there'", env)
		self.assertIn("LOAD_SIDECAR_WEIGHTS=1", env)
		self.assertIn("ALLOW_FETCH=1", env)
		self.assertIn("ALLOW_PATCH=1", env)
		self.assertIn("ALLOW_BUILD=1", env)
		self.assertIn("ALLOW_RUN=1", env)

	def test_resident_batched_decode_task_defaults_to_gated_run(self) -> None:
		parser = codex_task.build_parser()
		args = parser.parse_args(["spark-resident-batched-decode"])
		self.assertFalse(args.run)
		self.assertEqual(args.parallel_values, "8")
		self.assertEqual(args.batch_values, "2048")
		self.assertEqual(args.ubatch_values, "512")
		self.assertEqual(args.concurrency, "1 2 4 8")


if __name__ == "__main__":
	unittest.main()
