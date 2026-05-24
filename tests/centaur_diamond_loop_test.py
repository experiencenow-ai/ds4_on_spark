import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


ORIGINAL = """def coal(x):
    y = x + 1
    return y
"""

CANDIDATE = """def coal(x):
    return x + 1
"""


def _write_candidate_record(
	record_dir: Path,
	target_id: str,
	candidate_id: str,
	candidate_text: str,
	accepted: bool,
	diamond_score: float,
) -> dict:
	target = {
		"target_id": target_id,
		"path": "centaur/module.py",
		"source": ORIGINAL,
		"behavior_contract": "increment by one",
	}
	proposal = {
		"candidate_id": candidate_id,
		"model": "deepseek-ai/DeepSeek-V4-Flash",
		"text": candidate_text,
	}
	verification = {
		"accepted_for_review": accepted,
		"diamond_score": diamond_score,
		"verification_level": "unit-smoke",
	}
	(record_dir / "target.json").write_text(json.dumps(target), encoding="utf-8")
	(record_dir / "proposal.json").write_text(json.dumps(proposal), encoding="utf-8")
	(record_dir / "verification.json").write_text(json.dumps(verification), encoding="utf-8")
	(record_dir / "review_packet.md").write_text("# Review\n", encoding="utf-8")
	return {
		"target_id": target_id,
		"candidate_id": candidate_id,
		"record_dir": str(record_dir),
		"accepted_for_review": accepted,
		"diamond_score": diamond_score,
	}


class CentaurDiamondLoopTest(unittest.TestCase):
	def make_verified(self, tmp: Path) -> Path:
		verified = tmp / "verified"
		records = verified / "records"
		accepted = records / "cand-1"
		rejected = records / "cand-2"
		accepted.mkdir(parents=True)
		rejected.mkdir(parents=True)
		accepted_summary = _write_candidate_record(
			accepted, "module:coal", "cand-1", f"```python\n{CANDIDATE}```", True, 12.5,
		)
		rejected_summary = _write_candidate_record(
			rejected, "module:other", "cand-2", "```python\nbroken\n```", False, -1000.0,
		)
		summary = {
			"format": "centaur-diamond-verification-index-v1",
			"proposal_count": 2,
			"candidate_count": 2,
			"verified_count": 2,
			"accepted_count": 1,
			"rejected_count": 1,
			"accepted": [accepted_summary],
			"records": [accepted_summary, rejected_summary],
		}
		(verified / "verification_summary.json").write_text(json.dumps(summary), encoding="utf-8")
		return verified

	def release_queue(self, tmp: Path) -> tuple[Path, Path]:
		verified = self.make_verified(tmp)
		queue = tmp / "queue"
		cmd = [
			"bash",
			"scripts/centaur_release_review_queue.sh",
			"--verified-dir",
			str(verified),
			"--queue-root",
			str(queue),
			"--run-id",
			"run-1",
			"--spark",
			"spark6",
			"--model",
			"deepseek-ai/DeepSeek-V4-Flash",
			"--started-at",
			"2026-05-24T00:00:00Z",
			"--ended-at",
			"2026-05-24T00:10:00Z",
		]
		result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
		self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
		candidates = list((queue / "pending").glob("*/*/*"))
		self.assertEqual(len(candidates), 1)
		return queue, candidates[0]

	def test_release_review_queue_materializes_candidate_and_stats(self) -> None:
		tmp = Path(tempfile.mkdtemp())
		self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
		queue, candidate_dir = self.release_queue(tmp)
		self.assertEqual((candidate_dir / "original.py").read_text(encoding="utf-8"), ORIGINAL)
		self.assertEqual((candidate_dir / "candidate.py").read_text(encoding="utf-8"), CANDIDATE)
		self.assertIn("-    y = x + 1", (candidate_dir / "diff.patch").read_text(encoding="utf-8"))
		stats = json.loads((queue / "stats.json").read_text(encoding="utf-8"))
		aggregates = stats["aggregates"]
		self.assertEqual(aggregates["per_target"]["module:coal"]["accepted"], 1)
		self.assertEqual(aggregates["per_model"]["deepseek-ai/DeepSeek-V4-Flash"]["proposals"], 2)
		self.assertEqual(aggregates["per_model"]["deepseek-ai/DeepSeek-V4-Flash"]["diamond_score_sum"], 12.5)
		self.assertEqual(aggregates["per_spark"]["spark6"]["model_load_count"], 1)
		self.assertEqual(aggregates["best_models"][0]["model"], "deepseek-ai/DeepSeek-V4-Flash")

	def test_apply_approved_dry_run_and_real_commit(self) -> None:
		tmp = Path(tempfile.mkdtemp())
		self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
		queue, pending = self.release_queue(tmp)
		approved = queue / "approved" / "module_coal" / "2026-05-24" / "cand-1"
		approved.parent.mkdir(parents=True)
		shutil.move(str(pending), str(approved))
		repo = tmp / "centaur"
		(repo / "centaur").mkdir(parents=True)
		(repo / "centaur" / "module.py").write_text(ORIGINAL, encoding="utf-8")
		subprocess.run(["git", "init"], cwd=repo, check=True, text=True, capture_output=True)
		subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
		subprocess.run(["git", "config", "user.name", "Centaur Test"], cwd=repo, check=True)
		subprocess.run(["git", "add", "centaur/module.py"], cwd=repo, check=True)
		subprocess.run(["git", "commit", "-m", "seed"], cwd=repo, check=True, text=True, capture_output=True)
		dry = subprocess.run(
			["bash", "scripts/apply_approved.sh", str(approved), "--centaur-repo", str(repo), "--dry-run"],
			cwd=ROOT,
			text=True,
			capture_output=True,
		)
		self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
		self.assertFalse(json.loads(dry.stdout)["creates_commit"])
		real = subprocess.run(
			["bash", "scripts/apply_approved.sh", str(approved), "--centaur-repo", str(repo)],
			cwd=ROOT,
			text=True,
			capture_output=True,
		)
		self.assertEqual(real.returncode, 0, real.stdout + real.stderr)
		payload = json.loads(real.stdout)
		self.assertIn("commit", payload)
		self.assertTrue(payload["branch"].startswith("centaur-approved/"))
		self.assertEqual((repo / "centaur" / "module.py").read_text(encoding="utf-8"), CANDIDATE)
		subject = subprocess.run(["git", "log", "-1", "--pretty=%s"], cwd=repo, text=True, capture_output=True, check=True).stdout
		self.assertIn("Apply approved Centaur diamond candidate", subject)

	def test_loop_dry_run_uses_skip_list_without_ssh(self) -> None:
		tmp = Path(tempfile.mkdtemp())
		self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
		meta = tmp / "queue" / "pending" / "target" / "2026-05-24" / "cand" / "metadata.json"
		meta.parent.mkdir(parents=True)
		meta.write_text(json.dumps({"target_id": "recent-target", "queued_at": "2026-05-24T00:00:00Z"}), encoding="utf-8")
		cmd = [
			"bash",
			"scripts/centaur_diamond_loop.sh",
			"--dry-run",
			"--queue-root",
			str(tmp / "queue"),
			"--run-id",
			"dry-run",
			"--sparks",
			"spark6",
			"--target-count",
			"2",
			"--prompt-variants",
			"3",
		]
		result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
		self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
		plan = json.loads(result.stdout)
		self.assertEqual(plan["planned_prompts"], 6)
		self.assertEqual(plan["skip_targets"], 1)
		skip = json.loads(Path(plan["skip_file"]).read_text(encoding="utf-8"))
		self.assertEqual(skip["target_ids"], ["recent-target"])

	def test_scripts_parse(self) -> None:
		cmd = [
			"bash",
			"-n",
			"scripts/centaur_diamond_loop.sh",
			"scripts/centaur_release_review_queue.sh",
			"scripts/apply_approved.sh",
		]
		result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
		self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
	unittest.main()
