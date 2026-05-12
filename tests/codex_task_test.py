import unittest

from scripts import codex_task


class CodexTaskTest(unittest.TestCase):
	def test_expected_tasks_are_registered(self) -> None:
		parser = codex_task.build_parser()
		subparsers = next(action for action in parser._actions if action.dest == "task")
		self.assertEqual(
			set(subparsers.choices),
			{
				"automation-status",
				"mtp-local-verify",
				"pr-status",
				"repo-status",
				"spark-antirez-oracle",
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


if __name__ == "__main__":
	unittest.main()
