#!/usr/bin/env python3
"""Summarize DS4 CUDA MoE batch-ladder probe outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def pair_rate(row: dict[str, Any]) -> float:
	return float(row.get("expert_pairs_per_s") or row.get("best_pairs_per_s") or 0.0)


def load_rows(path: Path) -> list[dict[str, Any]]:
	rows: list[dict[str, Any]] = []
	for item in sorted(path.glob("moe_*.out")):
		text = item.read_text(encoding="utf-8", errors="replace").strip()
		if not text:
			continue
		for line in text.splitlines():
			line = line.strip()
			if not line.startswith("{"):
				continue
			try:
				row = json.loads(line)
			except json.JSONDecodeError:
				continue
			if isinstance(row, dict) and row.get("cuda_moe_probe") is True:
				row["source"] = str(item)
				rows.append(row)
	return sorted(rows, key=lambda r: int(r.get("tokens") or 0))


def write_markdown(rows: list[dict[str, Any]], out: Path) -> None:
	base = 0.0
	for row in rows:
		base = pair_rate(row)
		if base > 0.0:
			break
	lines = [
		"| tokens | pairs | active experts | mean queue | max queue | best ms | expert-pairs/s | gain vs first ok |",
		"| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
	]
	for row in rows:
		pairs_s = pair_rate(row)
		gain = (pairs_s / base) if base > 0.0 else 0.0
		lines.append(
			f"| {int(row.get('tokens') or 0)} "
			f"| {int(row.get('pairs') or 0)} "
			f"| {int(row.get('active_experts') or 0)} "
			f"| {float(row.get('mean_queue_depth') or 0.0):.3f} "
			f"| {int(row.get('max_queue_depth') or 0)} "
			f"| {float(row.get('best_ms') or 0.0):.3f} "
			f"| {pairs_s:.1f} "
			f"| {gain:.2f}x |"
		)
	out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
	parser = argparse.ArgumentParser(description="Summarize DS4 CUDA MoE batch-ladder JSON outputs.")
	parser.add_argument("--dir", required=True, help="Directory containing moe_<tokens>.out files.")
	parser.add_argument("--json-out", default="", help="Optional JSON summary path.")
	parser.add_argument("--md-out", default="", help="Optional Markdown table path.")
	args = parser.parse_args()
	rows = load_rows(Path(args.dir))
	payload = {
		"ok": len(rows) > 0,
		"rows": rows,
	}
	if args.json_out:
		Path(args.json_out).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
	if args.md_out:
		write_markdown(rows, Path(args.md_out))
	print(json.dumps(payload, indent=2, sort_keys=True))
	return 0 if rows else 1


if __name__ == "__main__":
	raise SystemExit(main())
