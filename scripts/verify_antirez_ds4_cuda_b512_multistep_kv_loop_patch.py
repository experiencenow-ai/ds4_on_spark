#!/usr/bin/env python3
"""Verify the antirez/ds4 B=512 multi-step decode/KV-loop patch contract."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def validate_patch_text(text: str) -> list[str]:
	errors: list[str] = []
	added = "\n".join(
		line[1:]
		for line in text.splitlines()
		if line.startswith("+") and not line.startswith("+++ ")
	)
	required = [
		"DS4_CUDA_STACK_PROBE_DECODE_STEPS",
		"static bool cuda_stack_probe_seed_committed_tokens(",
		"ds4_gpu_tensor_write(g->prefill_tokens,",
		"ds4_gpu_embed_tokens_hc_tensor(g->batch_cur_hc,",
		"for (uint32_t step = 0; ok && step < decode_steps; step++)",
		"ok = cuda_batch_stack_probe_run(&g, model, weights, n_tokens, &token_profiles[slot]);",
		"hash_bytes(host_committed,",
		"ok = cuda_stack_probe_seed_committed_tokens(&g, model, weights, host_committed, n_tokens);",
		"kv_update_success",
		"per_step_decode_ms",
		"per_step_token_commit_ms",
		"per_step_token_hashes",
	]
	for needle in required:
		if needle not in added:
			errors.append(f"missing expected added substring: {needle!r}")
	if "row_replacement" in added:
		errors.append("patch must not implement row replacement in this PR")
	return errors


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--patch", required=True)
	args = ap.parse_args()
	errors = validate_patch_text(Path(args.patch).read_text(encoding="utf-8"))
	if errors:
		for error in errors:
			print(f"error: {error}", file=sys.stderr)
		return 2
	print("ok=true")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
