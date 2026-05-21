#!/usr/bin/env python3
"""Harvest a completed ds4-eval run into committed Lane D artifacts."""

from __future__ import annotations

import argparse
import gzip
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import pipeline_quality_regression as quality
from scripts import pipeline_throughput_truth as truth


def _safe_run_id(run_id: str) -> str:
	if not re.match(r"^[A-Za-z0-9_.-]+$", run_id):
		raise ValueError("run_id may only contain letters, digits, dots, underscores, and hyphens")
	return run_id


def _gzip_copy(src: Path, dst: Path) -> None:
	dst.parent.mkdir(parents=True, exist_ok=True)
	with src.open("rb") as fin, dst.open("wb") as raw:
		with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as fout:
			shutil.copyfileobj(fin, fout)


def _copy_text(src: Path, dst: Path) -> None:
	dst.parent.mkdir(parents=True, exist_ok=True)
	dst.write_text(src.read_text(encoding="utf-8").strip() + "\n", encoding="utf-8")


def harvest(args: argparse.Namespace) -> dict[str, Any]:
	run_id = _safe_run_id(args.run_id)
	out_dir = Path(args.out_dir)
	trace_src = Path(args.trace)
	stdout_src = Path(args.stdout)
	rc_src = Path(args.rc)
	for path in (trace_src, stdout_src, rc_src):
		if not path.exists():
			raise FileNotFoundError(path)
	trace_artifact = out_dir / f"{run_id}.trace.txt.gz"
	stdout_artifact = out_dir / f"{run_id}.stdout.txt.gz"
	rc_artifact = out_dir / f"{run_id}.rc.txt"
	jsonl_artifact = out_dir / f"{run_id}.jsonl"
	summary_artifact = out_dir / f"{run_id}.summary.json"
	throughput_artifact = out_dir / f"{run_id}.throughput.json"
	_gzip_copy(trace_src, trace_artifact)
	_gzip_copy(stdout_src, stdout_artifact)
	_copy_text(rc_src, rc_artifact)
	import_args = argparse.Namespace(
		ds4_eval_trace_artifact=str(trace_artifact),
		ds4_eval_stdout=str(stdout_artifact),
		ds4_eval_rc=str(rc_artifact),
		ds4_eval_rc_artifact=str(rc_artifact),
		ds4_eval_command=args.command,
		baseline=args.baseline,
		run_id=run_id,
		backend_mode=args.backend_mode,
		runner_id=args.runner_id,
	)
	records, summary = quality.load_ds4_eval_trace(trace_src, import_args)
	quality.write_jsonl(jsonl_artifact, records + [summary])
	summary_artifact.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
	throughput = truth.summarize(jsonl_artifact)
	throughput_artifact.write_text(json.dumps(throughput, indent=2, sort_keys=True) + "\n", encoding="utf-8")
	return {
		"run_id": run_id,
		"question_count": summary["question_count"],
		"passed": summary["passed"],
		"failed": summary["failed"],
		"aggregate_output_tokens_per_s": summary["aggregate_output_tokens_per_s"],
		"trace_wall_elapsed_sec": summary["trace_wall_elapsed_sec"],
		"ds4_eval_returncode": summary["ds4_eval_returncode"],
		"domain_breakdown_count": len(summary["domain_breakdown"]),
		"artifacts": {
			"jsonl": str(jsonl_artifact),
			"summary": str(summary_artifact),
			"throughput": str(throughput_artifact),
			"trace": str(trace_artifact),
			"stdout": str(stdout_artifact),
			"rc": str(rc_artifact),
		},
	}


def build_parser() -> argparse.ArgumentParser:
	ap = argparse.ArgumentParser()
	ap.add_argument("--run-id", required=True)
	ap.add_argument("--runner-id", default="spark6-ds4-eval-pp1")
	ap.add_argument("--backend-mode", default="pp1", choices=("pp1", "ppn", "pipeline", "other"))
	ap.add_argument("--trace", required=True)
	ap.add_argument("--stdout", required=True)
	ap.add_argument("--rc", required=True)
	ap.add_argument("--out-dir", default="fixtures/pipeline_quality")
	ap.add_argument("--command", default="")
	ap.add_argument("--baseline", default="")
	return ap


def main(argv: list[str] | None = None) -> int:
	result = harvest(build_parser().parse_args(argv))
	print(json.dumps(result, sort_keys=True))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
