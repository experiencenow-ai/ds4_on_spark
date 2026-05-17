#!/usr/bin/env python3
"""Split one in-process DS4 repeat run into per-sample acceptance summaries."""

from __future__ import annotations

import json
import re
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Iterable, Optional

try:
	import extract_antirez_ds4_mtp_conf_log as extractor
except ImportError:
	from scripts import extract_antirez_ds4_mtp_conf_log as extractor


BEGIN_RE = re.compile(r"ds4: mtp repeat sample_begin index=(?P<index>\d+) count=(?P<count>\d+)")
END_RE = re.compile(r"ds4: mtp repeat sample_end index=(?P<index>\d+) count=(?P<count>\d+) exit_code=(?P<exit_code>-?\d+)")
BENCH_RE = re.compile(r"ds4: mtp bench (?P<body>.*)")


def _read_lines(paths: Iterable[Path]) -> list[str]:
	lines: list[str] = []
	for path in paths:
		try:
			lines.extend(path.read_text(encoding="utf-8", errors="replace").splitlines())
		except OSError as e:
			raise RuntimeError(f"failed to read {path}: {e}") from e
	return lines


def _bench_line(line: str) -> bool:
	m = BENCH_RE.search(line)
	if m is None:
		return False
	body = str(m.group("body"))
	return "command_sha256=" in body and "external_wall_s=" not in body


def split_repeat_samples(lines: list[str], expected_count: int) -> dict[int, list[str]]:
	if expected_count <= 0:
		raise ValueError("expected_count must be positive")
	global_prefix: list[str] = []
	samples: dict[int, list[str]] = {}
	current_index: Optional[int] = None
	current_lines: list[str] = []
	for line in lines:
		begin = BEGIN_RE.search(line)
		if begin is not None:
			if current_index is not None:
				raise ValueError(f"nested repeat sample at index {begin.group('index')}")
			current_index = int(begin.group("index"))
			count = int(begin.group("count"))
			if count != expected_count:
				raise ValueError(f"repeat count mismatch: saw {count}, expected {expected_count}")
			current_lines = list(global_prefix)
			current_lines.append(line)
			continue
		if current_index is None:
			if _bench_line(line):
				global_prefix.append(line)
			continue
		current_lines.append(line)
		end = END_RE.search(line)
		if end is not None:
			end_index = int(end.group("index"))
			count = int(end.group("count"))
			if end_index != current_index:
				raise ValueError(f"repeat end index mismatch: begin {current_index}, end {end_index}")
			if count != expected_count:
				raise ValueError(f"repeat end count mismatch: saw {count}, expected {expected_count}")
			if current_index in samples:
				raise ValueError(f"duplicate repeat sample index {current_index}")
			samples[current_index] = current_lines
			current_index = None
			current_lines = []
	if current_index is not None:
		raise ValueError(f"unterminated repeat sample index {current_index}")
	missing = [idx for idx in range(1, expected_count + 1) if idx not in samples]
	if missing:
		raise ValueError(f"missing repeat sample indexes: {missing}")
	return samples


def write_split_samples(lines: list[str], out_dir: Path, expected_count: int) -> dict[str, Any]:
	samples = split_repeat_samples(lines, expected_count)
	out_dir.mkdir(parents=True, exist_ok=True)
	records: list[dict[str, Any]] = []
	for idx in sorted(samples):
		sample_dir = out_dir / f"sample-{idx:03d}"
		sample_dir.mkdir(parents=True, exist_ok=True)
		sample_lines = samples[idx]
		(sample_dir / "remote_probe_log.txt").write_text("\n".join(sample_lines) + "\n", encoding="utf-8")
		summary = extractor.extract_events(sample_lines)
		summary["repeat_sample"] = {
			"index": idx,
			"count": expected_count,
		}
		(sample_dir / "acceptance_summary.json").write_text(
			json.dumps(summary, indent=2, sort_keys=True) + "\n",
			encoding="utf-8",
		)
		records.append(
			{
				"index": idx,
				"dir": str(sample_dir),
				"acceptance_summary": str(sample_dir / "acceptance_summary.json"),
				"generation_tps": ((summary.get("speed") or {}).get("generation_tps")),
				"ok": bool(summary.get("ok", False)),
			}
		)
	report = {
		"format": "ds4-mtp-repeat-split-v1",
		"expected_count": expected_count,
		"sample_count": len(records),
		"samples": records,
	}
	(out_dir / "repeat_split_summary.json").write_text(
		json.dumps(report, indent=2, sort_keys=True) + "\n",
		encoding="utf-8",
	)
	return report


def main(argv: Optional[list[str]] = None) -> int:
	ap = ArgumentParser()
	ap.add_argument("--log", action="append", default=[])
	ap.add_argument("--out-dir", required=True)
	ap.add_argument("--expected-count", type=int, required=True)
	args = ap.parse_args(argv)
	paths = [Path(p) for p in args.log]
	if not paths:
		raise SystemExit("at least one --log is required")
	report = write_split_samples(_read_lines(paths), Path(args.out_dir), int(args.expected_count))
	print(json.dumps(report, indent=2, sort_keys=True))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
