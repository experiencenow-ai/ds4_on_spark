#!/usr/bin/env python3
"""Verify the antirez/ds4 MTP target-suffix verifier architecture patch."""

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
		"const bool use_target_suffix2 =",
		"draft_n == 2 && getenv(\"DS4_MTP_SERIAL_SUFFIX\") == NULL;",
		"static int metal_graph_try_mtp_suffix2_direct(",
		"static int metal_graph_try_mtp_suffix3_direct(",
		"DS4_MTP_DIRECT_DISABLE",
		"DS4_MTP_SESSION",
		"DS4_SUPPRESS_OUTPUT",
		"suppress_output ? suppress_generated_token : print_generated_token",
		"spec_frontier_commit_prefix1_graph(g)",
		"ds4_gpu_tensor *spec_prefix2_attn_state_kv[DS4_N_LAYER];",
		"static bool metal_graph_capture_prefix3_attn_state",
		"static bool spec_frontier_commit_prefix3_graph",
		"raw_cap, (uint32_t)ctx_size, prefill_cap, mtp_ready",
		"const double mtp_entry_t0 = mtp_timing ? now_sec() : 0.0;",
		"const double mtp_after_first_eval = mtp_timing ? now_sec() : 0.0;",
		"token_vec_push(&s->checkpoint, drafts[0]);",
		"token_vec_push(&s->checkpoint, drafts[1]);",
		"metal_graph_verify_suffix_tops(&s->graph",
		"const double snapshot_done = snapshot_t0;",
		"metal_graph_read_spec_logits_row(&s->graph, 1, row_logits)",
		"ds4_gpu_matmul_q8_0_top1_tensor",
		"metal_graph_encode_output_head_suffix2_top1",
		"metal_graph_encode_output_head_suffix3_top2",
		"metal_graph_encode_output_head_suffix3_top3",
		"metal_graph_encode_output_head_suffix4_top3",
		"metal_graph_encode_output_head_mtp_top1",
		"row2_selected = ds4_gpu_tensor_view",
		"metal_graph_read_selected_token(g, 2, next_token_out)",
		"metal_graph_read_selected_token(g, 3, next_token_out)",
		"int pending_argmax = -1;",
		"used_pending_argmax ? pending_argmax : sample_argmax",
		"bool                 need_logits,",
		"if (need_logits) {",
		"const bool read_logits = need_logits || !partial_top1_cont;",
		"*next_token_out = row_tops[1];",
		"*next_token_out = row_tops[0];",
		"if (n_generated >= n_predict) break;",
		"DS4_MTP_DRAFT_FULL_LOGITS",
		"DS4_MTP_SUFFIX_LOCAL_RAW",
		"DS4_MTP_ROW0_FULL_LOGITS",
		"DS4_MTP_ROW2_FULL_LOGITS",
		"const bool continuation_top1_head =",
		"const bool partial_top1_cont =",
		"ds4_gpu_matmul_q8_0_top1_tensor(row2_selected",
		"metal_graph_read_spec_logits_row(g, 2, logits)",
		"readback=%.3f ms",
		"&pending_argmax,\n                                                                trace_top,\n                                                                &mtp_stats",
		"g->spec_capture_prefix1 = capture_prefix1 && n_tokens >= 2;",
		"g->spec_capture_prefix2 = capture_prefix1 && n_tokens >= 3;",
		"g->spec_capture_prefix3 = capture_prefix1 && n_tokens >= 4;",
		"getenv(\"DS4_MTP_ROW0_FULL_LOGITS\") == NULL && row <= 2",
		"row_logits == NULL &&",
		"stats->full_vocab_rows += row0_top1_head ? (continuation_top1_head ? 0 : 1) : 3;",
		"stats->top1_rows += row0_top1_head ? (continuation_top1_head ? 3 : 2) : 0;",
		"metal_graph_commit_batch_hc_row_to_current(g, 2)",
		"metal_graph_commit_batch_hc_row_to_current(g, 1)",
		"metal_graph_commit_batch_hc_row_to_current(g, 0)",
		"spec_frontier_commit_prefix2_graph(g)",
		"metal_graph_verify_suffix_tops(g, model, weights, checkpoint",
		"(uint32_t)start, 2, true",
		"(uint32_t)start, 3, true",
		"(uint32_t)start, 4, true",
		"n_predict - n_generated >= 2",
		"pos = checkpoint.len;",
		"n_predict - n_generated >= 4",
		"DS4_MTP_SAMPLE_DIAG",
		"ds4: mtp sample_diag direct=1",
		"suffix2_full_accepts",
		"suffix2_fallbacks",
		"suffix2_first_nonfull_pos",
		"suffix2_first_nonfull_top0",
		"mtp_cache_advance_calls",
		"need_head = top_id || logits",
		"metal_graph_frontier_snapshot",
		"metal_graph_frontier_restore",
		"ds4_gpu_matmul_q8_0_exact_tensor",
		"q8_0_exact",
		"allow_cublas && g_cublas_ready && n_tok > 1",
		"DS4_MTP_FULL_GPU_TOPK",
		"metal_graph_read_spec_logits_row(g, row, top_logits)",
		"DS4_MTP_INDEXER_EQ_CHECK",
		"ds4: mtp indexer_eq mismatch pos=%u row=%u indexer=%d full=%d",
		"indexer_eq_mismatches",
		"DS4_MTP_TOP1_EQ_CHECK",
		"ds4: mtp top1_eq mismatch pos=%u row=%u top1=%d full=%d",
		"top1_eq_mismatches",
		"n_generated < n_predict",
		"DS4_MTP_BENCH_REPEATS",
		"DS4_MTP_BENCH_WARMUP_REPEATS",
		"ds4: mtp repeat warmup_begin index=%d count=%d",
		"ds4: mtp repeat warmup_end index=%d count=%d exit_code=%d",
		"ds4: mtp repeat sample_begin index=%d count=%d",
		"ds4: mtp repeat sample_end index=%d count=%d exit_code=%d",
		"metal_tensor_fill_f32(g->mtp_raw_cache, 0.0f",
		"serial_decode_steps",
		"first_eval=0.000 ms",
		"suffix2_tail drafted=1 committed=1",
		"suffix2_tail drafted=1 committed=0",
		"verifier_calls=1 target_positions=2 target_calls=1 head_calls=1",
		"committed=1 first_eval=0.000 ms draft=%.3f ms snapshot=0.000 ms verify=%.3f ms prefix=%.3f ms target=%.3f ms head=0.000 ms readback=%.3f ms",
		"committed=0 first_eval=0.000 ms draft=%.3f ms snapshot=0.000 ms verify=%.3f ms prefix=%.3f ms target=%.3f ms head=0.000 ms readback=%.3f ms",
		"verifier_calls=1 target_positions=3 target_calls=1 head_calls=%d",
		"verifier_calls=1 target_positions=4 target_calls=1 head_calls=1",
		"drafted=3 committed=3",
		"drafted=3 committed=2",
		"draft_calls=3",
		"committed=1 first_eval=0.000 ms",
		"committed=0 first_eval=0.000 ms",
		"metal_graph_materialize_suffix_logits_row(&s->graph",
		"metal_graph_read_spec_logits_row(&s->graph, 0, row_logits)",
		"first_eval=%.3f ms",
		"row0_top1_head ? 2 : 3",
		"row0_top1_head ? 1 : 0",
	]
	for needle in required:
		if needle not in added:
			errors.append(f"missing expected added substring: {needle!r}")
	for forbidden in [
		"DS4_MTP_DRAFT=4",
		"draft_n == 4",
		"cross_spark",
		"DS4_CUDA_MOE_SLICE",
		"metal_graph_verify_decode2_exact(g,model,weights,draft0,draft1,start_pos",
		"out->staged_kv_ready = false;",
		"row0_logits = xmalloc",
		"DS4_MTP_ROW2_SKIP_LOGITS_READBACK",
		"trace_top ? NULL : &pending_argmax",
		"spec_frontier_snapshot(&frontier, s)",
		"spec_frontier_free(&frontier)",
		"spec_frontier_restore(&frontier, s)",
	]:
		if forbidden in added:
			errors.append(f"forbidden architecture creep in patch: {forbidden!r}")
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
