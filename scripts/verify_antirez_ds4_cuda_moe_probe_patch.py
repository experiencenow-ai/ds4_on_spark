#!/usr/bin/env python3
"""Verify the antirez/ds4 CUDA routed-MoE probe patch.

This verifier checks for the upstream ds4 harness used to measure real CUDA
routed-MoE behavior without running the whole decode graph. The probe must use
the real router, real selected experts, real expert weights, and real routed
MoE kernels, then emit JSON with finite-output and optional full-slab compare
metadata.
"""

from __future__ import annotations

import argparse
import sys


def _die(msg: str) -> None:
	print(msg, file=sys.stderr)
	raise SystemExit(2)


def _read_text(path: str) -> str:
	try:
		with open(path, "r", encoding="utf-8") as f:
			return f.read()
	except OSError as e:
		_die(f"failed to read {path}: {e}")
	return ""


def validate_patch_text(patch_text: str) -> list[str]:
	errors: list[str] = []
	added_lines: list[str] = []
	for line in patch_text.splitlines():
		if not line.startswith("+"):
			continue
		if line.startswith("+++ "):
			continue
		added_lines.append(line[1:])
	added_text = "\n".join(added_lines)

	required_substrings = [
		"diff --git a/ds4.c b/ds4.c",
		"diff --git a/ds4.h b/ds4.h",
		"diff --git a/ds4_cli.c b/ds4_cli.c",
		"DS4_CUDA_SKIP_STARTUP_MODEL_CACHE",
		"DS4_CUDA_WEIGHT_PRELOAD_SLEEP_US",
		"int ds4_engine_cuda_moe_probe(ds4_engine *e, uint32_t il, uint32_t n_tokens, uint32_t iterations)",
		"int ds4_engine_cuda_moe_probe(ds4_engine *e, uint32_t layer, uint32_t n_tokens, uint32_t iterations);",
		"int ds4_engine_cuda_layer_probe(ds4_engine *e, uint32_t il, uint32_t n_tokens, uint32_t iterations, bool ffn_only)",
		"int ds4_engine_cuda_layer_probe(ds4_engine *e, uint32_t layer, uint32_t n_tokens, uint32_t iterations, bool ffn_only);",
		"int ds4_engine_cuda_decode_probe(ds4_engine *e, uint32_t il, uint32_t pos, uint32_t iterations)",
		"int ds4_engine_cuda_decode_probe(ds4_engine *e, uint32_t layer, uint32_t pos, uint32_t iterations);",
		"int ds4_engine_cuda_decode_stack_probe(ds4_engine *e, uint32_t pos, uint32_t iterations)",
		"int ds4_engine_cuda_batch_stack_probe(ds4_engine *e, uint32_t n_tokens, uint32_t iterations)",
		"int ds4_engine_cuda_output_head_probe(ds4_engine *e, uint32_t iterations)",
		"--cuda-moe-probe",
		"--cuda-layer-probe",
		"--cuda-ffn-probe",
		"--cuda-decode-probe",
		"--cuda-decode-stack-probe",
		"--cuda-batch-stack-probe",
		"--cuda-output-head-probe",
		"--cuda-decode-pos",
		"--cuda-moe-layer",
		"--cuda-moe-tokens",
		"--cuda-moe-iters",
		"parse_u32_allow_zero",
		"c.engine.backend = DS4_BACKEND_CUDA;",
		"ds4_gpu_matmul_f16_tensor(router,",
		"ds4_gpu_router_select_batch_tensor(selected,",
		"ds4_gpu_routed_moe_batch_tensor(out, gate, up, mid, down,",
		"DS4_CUDA_MOE_PROBE_COMPARE_FULL",
		"unsetenv(\"DS4_CUDA_MOE_BATCHED_EXPERT_SLICE_CACHE\")",
		"setenv(\"DS4_CUDA_MOE_BATCHED_EXPERT_SLICE_CACHE\", saved_slice_env, 1)",
		"cuda_moe_probe\\\":true",
		"active_experts\\\":%u",
		"mean_queue_depth\\\":%.3f",
		"max_queue_depth\\\":%u",
		"best_pairs_per_s\\\":%.3f",
		"out_nonfinite\\\":",
		"full_slab_nonfinite\\\":",
		"metal_graph_encode_layer_attention_batch(g, model, layer, il, 0, n_tokens)",
		"metal_graph_encode_layer_ffn_batch(g, model, layer, il, 0, n_tokens)",
		"cuda_layer_probe\\\":true",
		"cuda_decode_probe\\\":true",
		"cuda_decode_stack_probe\\\":true",
		"cuda_batch_stack_probe\\\":true",
		"cuda_output_head_probe\\\":true",
		"best_tokens_per_s\\\":%.3f",
		"best_layer_tokens_per_s\\\":%.3f",
		"best_rows_per_s\\\":%.3f",
		"best_heads_per_s\\\":%.3f",
	]
	for s in required_substrings:
		if s not in patch_text:
			errors.append(f"missing expected substring: {s!r}")

	required_added_substrings = [
		"static void cuda_moe_probe_fill(float *x, int32_t *tokens, uint32_t n_tokens, uint32_t n_dim)",
		"if (!layer->ffn_gate_inp || !layer->ffn_gate_exps || !layer->ffn_up_exps || !layer->ffn_down_exps)",
		"if (expert_in_dim == 0 || expert_mid_dim == 0 || out_dim == 0)",
		"const uint32_t expert_in_dim = (uint32_t)layer->ffn_gate_exps->dim[0];",
		"const uint32_t expert_mid_dim = (uint32_t)layer->ffn_gate_exps->dim[1];",
		"const uint32_t out_dim = (uint32_t)layer->ffn_down_exps->dim[1];",
		"if (!isfinite(a[i])) out_nonfinite++;",
		"if (!isfinite(b[i])) full_nonfinite++;",
		"max_abs_diff",
		"mean_abs_diff",
		"cfg.gen.cuda_moe_probe",
		"cfg.gen.cuda_layer_probe",
		"cfg.gen.cuda_layer_ffn_only",
		"cfg.gen.cuda_decode_probe",
		"cfg.gen.cuda_decode_stack_probe",
		"cfg.gen.cuda_batch_stack_probe",
		"cfg.gen.cuda_output_head_probe",
		"cfg.gen.cuda_decode_pos",
		"static void accelerator_cuda_preload_pause(void)",
		"static uint64_t cuda_probe_nonfinite_count(const uint8_t *buf, uint64_t bytes)",
		"static bool cuda_decode_probe_run(",
		"static bool cuda_decode_stack_probe_run(",
		"static bool cuda_batch_stack_probe_run(",
		"cuda_stack_probe_include_head()",
		"metal_graph_encode_decode_layer(g,",
		"static bool cuda_layer_probe_run(",
		"ffn_only ? \"ffn\" : \"layer\"",
	]
	for s in required_added_substrings:
		if s not in added_text:
			errors.append(f"missing expected added substring: {s!r}")

	return errors


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--patch", required=True)
	args = ap.parse_args()

	patch_text = _read_text(args.patch)
	errors = validate_patch_text(patch_text)
	if errors:
		for e in errors[:64]:
			print(f"error: {e}", file=sys.stderr)
		raise SystemExit(2)

	print("ok=true")


if __name__ == "__main__":
	main()
