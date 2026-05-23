#!/usr/bin/env python3
"""Verify the antirez/ds4 B=512 multi-step decode/KV-loop patch contract."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
	sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._lib.patch_verify import added_patch_text
from scripts._lib.patch_verify import require_substrings
from scripts._lib.patch_verify import run_patch_verifier


def validate_patch_text(text: str) -> list[str]:
	errors: list[str] = []
	added = added_patch_text(text)
	require_substrings(errors, added, [
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
	], "expected added substring")
	if "row_replacement" in added:
		errors.append("patch must not implement row replacement in this PR")
	return errors


if __name__ == "__main__":
	run_patch_verifier(validate_patch_text)
