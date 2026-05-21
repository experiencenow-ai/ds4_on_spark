import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import run_guarded_spark_vllm_recipe as guarded


SAFE_SCRIPT = """#!/bin/bash
vllm serve /models/deepseek-v4-flash \\
  --tokenizer-mode deepseek_v4 \\
  --tensor-parallel-size 2 \\
  --max-model-len 200000 \\
  --max-num-seqs 512 \\
  --max-num-batched-tokens 8192 \\
  --gpu-memory-utilization 0.8 \\
  --no-enable-prefix-caching
"""


BAD_SCRIPT = SAFE_SCRIPT.replace("--no-enable-prefix-caching", "--enable-prefix-caching")


class VllmGuardedRunnerTest(unittest.TestCase):
	def make_runner(self, launch_script: str) -> tuple[Path, Path]:
		tmp = Path(tempfile.mkdtemp())
		runner = tmp / "run-recipe.sh"
		marker = tmp / "executed"
		runner.write_text(f"""#!/bin/sh
for arg in "$@"; do
	if [ "$arg" = "--dry-run" ]; then
		echo "Recipe: fake"
		echo "{guarded.BEGIN}"
		cat <<'EOF'
{launch_script.rstrip()}
EOF
		echo "{guarded.END}"
		exit 0
	fi
done
echo executed > "{marker}"
exit 0
""", encoding="utf-8")
		runner.chmod(0o755)
		return(runner, marker)

	def test_insert_dry_run_before_separator(self) -> None:
		args = ["recipe.yaml", "--no-ray", "--", "--load-format", "safetensors"]
		self.assertEqual(guarded.insert_dry_run_arg(args), ["recipe.yaml", "--no-ray", "--dry-run", "--", "--load-format", "safetensors"])

	def test_extract_launch_script(self) -> None:
		output = f"pre\n{guarded.BEGIN}\n{SAFE_SCRIPT}\n{guarded.END}\npost\n"
		self.assertEqual(guarded.extract_launch_script(output), SAFE_SCRIPT)

	def test_blocked_profile_does_not_execute(self) -> None:
		runner, marker = self.make_runner(BAD_SCRIPT)
		cmd = ["python3", "scripts/run_guarded_spark_vllm_recipe.py", "--runner", str(runner), "recipe.yaml", "--no-ray"]
		result = subprocess.run(cmd, text=True, capture_output=True)
		self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
		self.assertFalse(marker.exists())
		self.assertIn("prefix_cache_c512_rank0_kill_risk", result.stdout)

	def test_safe_profile_executes(self) -> None:
		runner, marker = self.make_runner(SAFE_SCRIPT)
		cmd = ["python3", "scripts/run_guarded_spark_vllm_recipe.py", "--runner", str(runner), "recipe.yaml", "--no-ray"]
		env = os.environ.copy()
		result = subprocess.run(cmd, text=True, capture_output=True, env=env)
		self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
		self.assertTrue(marker.exists())
		self.assertIn('"status": "passed"', result.stdout)

	def test_memory_unsafe_profile_does_not_execute(self) -> None:
		runner, marker = self.make_runner(SAFE_SCRIPT)
		cmd = ["python3", "scripts/run_guarded_spark_vllm_recipe.py", "--runner", str(runner), "--available-kv-gib", "6.07", "recipe.yaml", "--no-ray"]
		result = subprocess.run(cmd, text=True, capture_output=True)
		self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
		self.assertFalse(marker.exists())
		self.assertIn("kv_request_exceeds_available", result.stdout)


if __name__ == "__main__":
	unittest.main()
