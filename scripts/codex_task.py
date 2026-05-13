#!/usr/bin/env python3
"""Allowlisted Codex task runner for ds4_on_spark.

The goal is to give Codex one stable command prefix for common repo-owned
maintenance tasks without accepting arbitrary shell strings. Each task below
uses fixed subprocess argument arrays and validates the small set of parameters
it accepts.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys

try:
	import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback is rare here.
	tomllib = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = "spark0@aitopatom-9ab9.local"
DEFAULT_TRUNK_GGUF = "/home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2-imatrix.gguf"
DEFAULT_MTP_SIDECAR_GGUF = "/home/spark0/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf"
DEFAULT_LLAMA_DIR = "/home/spark0/src/llama-mtp-probe-94073e2-fixed"
DEFAULT_LLAMA_SERVER = "/home/spark0/src/llama.cpp-kamnxt/build-cuda/bin/llama-server"


def run(cmd: list[str], *, env_extra: dict[str, str] | None = None) -> None:
	env = os.environ.copy()
	if env_extra is not None:
		env.update(env_extra)
	print("+ " + shlex.join(cmd), file=sys.stderr)
	subprocess.run(cmd, cwd=REPO_ROOT, env=env, check=True)


def build_antirez_remote_env(args: argparse.Namespace) -> str:
	parts: list[tuple[str, str]] = [
		("DS4_DIR", args.ds4_dir),
		("TRUNK_GGUF", args.trunk_gguf),
		("MTP_SIDECAR_GGUF", args.mtp_sidecar_gguf),
		("PROMPT", args.prompt),
		("CTX", str(args.ctx)),
		("SEED", str(args.seed)),
	]
	if args.fetch or args.fresh:
		parts.append(("ALLOW_FETCH", "1"))
	if args.patch or args.fresh:
		parts.append(("ALLOW_PATCH", "1"))
	if args.build or args.fresh:
		parts.append(("ALLOW_BUILD", "1"))
	if args.run or args.fresh:
		parts.append(("ALLOW_RUN", "1"))
	if not any(k == "ALLOW_RUN" for k, _ in parts):
		parts.append(("ALLOW_RUN", "1"))
	return " ".join(f"{k}={shlex.quote(v)}" for k, v in parts)


def build_llamacpp_remote_env(args: argparse.Namespace) -> str:
	parts: list[tuple[str, str]] = [
		("LLAMA_DIR", args.llama_dir),
		("LLAMA_COMMIT", args.llama_commit),
		("TRUNK_GGUF", args.trunk_gguf),
		("MTP_SIDECAR_GGUF", args.mtp_sidecar_gguf),
		("PROMPT", args.prompt),
		("SEED", str(args.seed)),
	]
	if args.prompt_file_remote:
		parts.append(("PROMPT_FILE", args.prompt_file_remote))
	if args.load_sidecar_weights:
		parts.append(("LOAD_SIDECAR_WEIGHTS", "1"))
	if args.fetch or args.fresh:
		parts.append(("ALLOW_FETCH", "1"))
	if args.patch or args.fresh:
		parts.append(("ALLOW_PATCH", "1"))
	if args.build or args.fresh:
		parts.append(("ALLOW_BUILD", "1"))
	if args.run or args.fresh:
		parts.append(("ALLOW_RUN", "1"))
	if not any(k == "ALLOW_RUN" for k, _ in parts):
		parts.append(("ALLOW_RUN", "1"))
	return " ".join(f"{k}={shlex.quote(v)}" for k, v in parts)


def task_mtp_local_verify(args: argparse.Namespace) -> None:
	run([sys.executable, "scripts/verify_antirez_ds4_q4k_dot_math.py", "--trials", str(args.trials)])
	run([
		sys.executable,
		"scripts/verify_antirez_ds4_cuda_mtp_q4k_sidecar_patch.py",
		"--patch",
		"docs/antirez-patches/ds4-3630e64-cuda-mtp-q4k-and-sidecar-map.patch",
	])
	run([
		sys.executable,
		"scripts/verify_antirez_ds4_cuda_multi_model_cache_patch.py",
		"--patch",
		"docs/antirez-patches/ds4-3630e64-cuda-multi-model-cache.patch",
	])
	run([
		sys.executable,
		"-m",
		"unittest",
		"tests/q4k_llamacpp_fixture_test.py",
		"tests/mtp_one_token_draft_probe_diff_test.py",
		"tests/antirez_ds4_cuda_mtp_q4k_sidecar_patch_test.py",
		"tests/antirez_ds4_cuda_multi_model_cache_patch_test.py",
	])
	run(["git", "diff", "--check"])


def task_spark_antirez_oracle(args: argparse.Namespace) -> None:
	env_extra = {
		"OUT_ROOT": args.out_root,
		"REMOTE_ANTIREZ_DS4_MTP_ORACLE_ENV": build_antirez_remote_env(args),
	}
	run(["scripts/run_antirez_ds4_mtp_one_token_oracle_probe_spark.sh", args.target], env_extra=env_extra)


def task_spark_llamacpp_mtp_probe(args: argparse.Namespace) -> None:
	env_extra = {
		"OUT_ROOT": args.out_root,
		"LLAMA_COMMIT": args.llama_commit,
		"REMOTE_LLAMA_MTP_ONE_TOKEN_PROBE_ENV": build_llamacpp_remote_env(args),
	}
	if args.prompt_file_local:
		env_extra["PROMPT_FILE_LOCAL"] = args.prompt_file_local
	run(["scripts/run_llamacpp_mtp_one_token_draft_probe_spark.sh", args.target], env_extra=env_extra)


def task_spark_resident_batched_decode(args: argparse.Namespace) -> None:
	env_extra = {
		"OUT_ROOT": args.out_root,
		"ALLOW_RUN": "1" if args.run else "0",
		"LLAMA_SERVER": args.llama_server,
		"MODEL_GGUF": args.model_gguf,
		"MODEL_GGUF_GLOB": args.model_gguf_glob,
		"MODEL_GGUF_EXCLUDE_EGREP": args.model_gguf_exclude_egrep,
		"MODEL_GGUF_INCLUDE_EGREP": args.model_gguf_include_egrep,
		"PORT": str(args.port),
		"CTX": str(args.ctx),
		"N_PREDICT": str(args.n_predict),
		"PROMPT_WORDS": args.prompt_words,
		"CONCURRENCY": args.concurrency,
		"PARALLEL_VALUES": args.parallel_values,
		"BATCH_VALUES": args.batch_values,
		"UBATCH_VALUES": args.ubatch_values,
		"SERVER_ARGS": args.server_args,
		"CACHE_PROMPT": "1" if args.cache_prompt else "0",
		"SCRAPE_METRICS": "1" if args.scrape_metrics else "0",
		"RESTART_PER_COMBO": "1" if args.restart_per_combo else "0",
		"REQUEST_TIMEOUT_S": str(args.request_timeout_s),
		"WAIT_TIMEOUT_S": str(args.wait_timeout_s),
	}
	run(["scripts/run_resident_batched_decode_spark.sh", args.target], env_extra=env_extra)


def task_pr_status(args: argparse.Namespace) -> None:
	run([
		"gh",
		"pr",
		"list",
		"--state",
		args.state,
		"--limit",
		str(args.limit),
		"--json",
		"number,title,headRefName,mergeStateStatus,isDraft,updatedAt,url",
	])


def task_repo_status(_: argparse.Namespace) -> None:
	run(["git", "status", "--short", "--branch"])
	run(["git", "log", "--oneline", "-8", "--decorate"])


def task_automation_status(_: argparse.Namespace) -> None:
	root = Path.home() / ".codex" / "automations"
	if not root.exists():
		print(f"missing automation dir: {root}")
		return
	for path in sorted(root.glob("*/automation.toml")):
		name = path.parent.name
		status = "unknown"
		kind = "unknown"
		model = ""
		if tomllib is not None:
			try:
				data = tomllib.loads(path.read_text(encoding="utf-8"))
				name = str(data.get("name") or name)
				status = str(data.get("status") or status)
				kind = str(data.get("kind") or kind)
				model = str(data.get("model") or "")
			except (OSError, tomllib.TOMLDecodeError):
				pass
		model_suffix = f" model={model}" if model else ""
		print(f"{path.parent.name}: name={name} kind={kind} status={status}{model_suffix}")


def task_spark_ring_status(args: argparse.Namespace) -> None:
	cmd = ["scripts/ops_spark_ring_status.sh"]
	if args.target:
		cmd.append(args.target)
	run(cmd)


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description="Run allowlisted ds4_on_spark Codex maintenance tasks.")
	sub = parser.add_subparsers(dest="task", required=True)

	p = sub.add_parser("mtp-local-verify", help="Run local MTP patch/math/unit checks.")
	p.add_argument("--trials", type=int, default=50)
	p.set_defaults(func=task_mtp_local_verify)

	p = sub.add_parser("spark-antirez-oracle", help="Run the gated antirez/ds4 one-token MTP oracle on Spark.")
	p.add_argument("--target", default=DEFAULT_TARGET)
	p.add_argument("--out-root", default="/private/tmp/ds4_on_spark_antirez_oracle_runs")
	p.add_argument("--ds4-dir", default="$HOME/src/ds4-mtp-oracle-fixed")
	p.add_argument("--trunk-gguf", default=DEFAULT_TRUNK_GGUF)
	p.add_argument("--mtp-sidecar-gguf", default=DEFAULT_MTP_SIDECAR_GGUF)
	p.add_argument("--prompt", default="Explain Redis streams in one paragraph.")
	p.add_argument("--ctx", type=int, default=4096)
	p.add_argument("--seed", type=int, default=1234)
	p.add_argument("--fetch", action="store_true")
	p.add_argument("--patch", action="store_true")
	p.add_argument("--build", action="store_true")
	p.add_argument("--run", action="store_true")
	p.add_argument("--fresh", action="store_true", help="Set fetch+patch+build+run gates.")
	p.set_defaults(func=task_spark_antirez_oracle)

	p = sub.add_parser("spark-llamacpp-mtp-probe", help="Run the gated llama.cpp one-token MTP candidate probe on Spark.")
	p.add_argument("--target", default=DEFAULT_TARGET)
	p.add_argument("--out-root", default="/private/tmp/ds4_on_spark_llamacpp_mtp_one_token_probe")
	p.add_argument("--llama-dir", default=DEFAULT_LLAMA_DIR)
	p.add_argument("--llama-commit", default="94073e2")
	p.add_argument("--trunk-gguf", default=DEFAULT_TRUNK_GGUF)
	p.add_argument("--mtp-sidecar-gguf", default=DEFAULT_MTP_SIDECAR_GGUF)
	p.add_argument("--prompt", default="Explain Redis streams in one paragraph.")
	p.add_argument("--prompt-file-local", default="", help="Local prompt file to upload; one non-empty prompt per line.")
	p.add_argument("--prompt-file-remote", default="", help="Spark-side prompt file path; one non-empty prompt per line.")
	p.add_argument("--seed", type=int, default=1234)
	p.add_argument("--load-sidecar-weights", action="store_true")
	p.add_argument("--fetch", action="store_true")
	p.add_argument("--patch", action="store_true")
	p.add_argument("--build", action="store_true")
	p.add_argument("--run", action="store_true")
	p.add_argument("--fresh", action="store_true", help="Set fetch+patch+build+run gates.")
	p.set_defaults(func=task_spark_llamacpp_mtp_probe)

	p = sub.add_parser("spark-resident-batched-decode", help="Run resident llama-server batched decode throughput on Spark.")
	p.add_argument("--target", default=DEFAULT_TARGET)
	p.add_argument("--out-root", default="/private/tmp/ds4_on_spark_resident_batched_decode")
	p.add_argument("--run", action="store_true", help="Actually start llama-server and issue decode requests.")
	p.add_argument("--llama-server", default=DEFAULT_LLAMA_SERVER)
	p.add_argument("--model-gguf", default="")
	p.add_argument("--model-gguf-glob", default="/home/spark0/models/ds4/*.gguf")
	p.add_argument("--model-gguf-exclude-egrep", default="MTP|DFlash|draft|sidecar")
	p.add_argument("--model-gguf-include-egrep", default="IQ2|Q2_K|IQ3|Q3_K")
	p.add_argument("--port", type=int, default=18084)
	p.add_argument("--ctx", type=int, default=8192)
	p.add_argument("--n-predict", type=int, default=64)
	p.add_argument("--prompt-words", default="16")
	p.add_argument("--concurrency", default="1 2 4 8")
	p.add_argument("--parallel-values", default="8")
	p.add_argument("--batch-values", default="2048")
	p.add_argument("--ubatch-values", default="512")
	p.add_argument("--server-args", default="--cache-ram -1 --fit off --no-warmup --no-webui --cache-prompt --log-verbosity 2 --metrics")
	p.add_argument("--cache-prompt", action="store_true")
	p.add_argument("--scrape-metrics", dest="scrape_metrics", action="store_true", default=True)
	p.add_argument("--no-scrape-metrics", dest="scrape_metrics", action="store_false")
	p.add_argument("--restart-per-combo", action="store_true")
	p.add_argument("--request-timeout-s", type=float, default=900.0)
	p.add_argument("--wait-timeout-s", type=float, default=1200.0)
	p.set_defaults(func=task_spark_resident_batched_decode)

	p = sub.add_parser("pr-status", help="List GitHub PRs with merge-state fields.")
	p.add_argument("--state", choices=["open", "closed", "merged", "all"], default="open")
	p.add_argument("--limit", type=int, default=30)
	p.set_defaults(func=task_pr_status)

	p = sub.add_parser("repo-status", help="Show concise git status and recent history.")
	p.set_defaults(func=task_repo_status)

	p = sub.add_parser("automation-status", help="List local Codex automations.")
	p.set_defaults(func=task_automation_status)

	p = sub.add_parser("spark-ring-status", help="Run the repo Spark ring status helper.")
	p.add_argument("--target", default="")
	p.set_defaults(func=task_spark_ring_status)

	return parser


def main(argv: list[str] | None = None) -> int:
	parser = build_parser()
	args = parser.parse_args(argv)
	args.func(args)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
