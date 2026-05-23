# Quantized

> Supersedes: `docs/quantized-performance-path.md`, `docs/quantized-single-spark.md`, `docs/baseline-quantized-single-spark0-2026-05-13T080107Z-quantized-single-spark0-smallest-credible.md`, `docs/baseline-quantized-single-spark0-2026-05-13T003043Z-smallest.md`, `docs/baseline-quantized-single-spark0-2026-05-12T141651Z-smallest.md`

This is the canonical document for this topic. Update this file instead of adding a new overlapping note.

## Scope

- Consolidates 5 previous document(s) into one non-overlapping reference.
- Preserves stable commands, constraints, and source inventory; removes per-iteration narrative duplication.
- Historical probe/status fragments should live in git history, not as active docs.

## Current Guidance

- `quantized-performance-path.md`: Quantized Performance Path (Scheduler + MTP) (394 lines).
- `quantized-single-spark.md`: Quantized Single-Spark Milestone (412 lines).
- `baseline-quantized-single-spark0-2026-05-13T080107Z-quantized-single-spark0-smallest-credible.md`: Baseline: Quantized Single-Spark Spark0 (DeepSeek V4 Flash auto: smallest_by_size_bytes (exclude: MTP|DFlash|draft|sidecar; include: IQ2|Q2_K|IQ3|Q3_K)) (162 lines).
- `baseline-quantized-single-spark0-2026-05-13T003043Z-smallest.md`: Baseline: Quantized Single-Spark Spark0 (DeepSeek V4 Flash IQ2XXS smallest trunk (chat-v2)) (158 lines).
- `baseline-quantized-single-spark0-2026-05-12T141651Z-smallest.md`: Baseline: Quantized Single-Spark Spark0 (DeepSeek V4 Flash IQ2XXS auto-select smallest) (153 lines).

## Command Inventory

- `quantized-performance-path.md`: `python3 scripts/diff_mtp_one_token_draft_probe.py --a /path/to/oracle_probe.json --b /path/to/candidate_probe.json --json`
- `quantized-performance-path.md`: `python3 scripts/verify_mtp_one_token_draft_probe_captures.py --probe-json /path/to/oracle_probe.json --json`
- `quantized-performance-path.md`: `python3 scripts/verify_mtp_one_token_draft_probe_captures.py --probe-json /path/to/candidate_probe.json --json`
- `quantized-performance-path.md`: `python3 scripts/summarize_mtp_one_token_draft_probe_diff.py --a /path/to/oracle_probe.json --b /path/to/candidate_probe.json --json`
- `quantized-performance-path.md`: `python3 scripts/summarize_mtp_acceptance_trace.py --in-jsonl /path/to/runtime.log.jsonl --draft-len <gamma>`
- `quantized-performance-path.md`: `python3 sim/scheduler/scheduler_sim.py --trace-jsonl /path/to/route.jsonl --trace-summary --json`
- `quantized-performance-path.md`: `python3 sim/scheduler/scheduler_sim.py --trace-jsonl /path/to/route.jsonl --num-experts 0 --json   # 0 = infer from trace/meta`
- `quantized-performance-path.md`: `python3 sim/scheduler/scheduler_sim.py --trace-jsonl /path/to/route.jsonl --num-experts 0 --summary-json`
- `quantized-performance-path.md`: `python3 sim/scheduler/trace_sweep.py --trace-jsonl /path/to/route.jsonl --trace-input-format runtime --trace-non-route skip --num-experts 0 --max-tokens 5000`
- `quantized-performance-path.md`: `python3 sim/scheduler/trace_sweep.py --trace-jsonl /path/to/route.jsonl --trace-input-format runtime --trace-non-route skip --trace-default-cls batch --num-experts 0 --max-tokens 5000`
- `quantized-performance-path.md`: `python3 sim/scheduler/recommendations.py --trace-jsonl /path/to/route.jsonl --trace-input-format runtime --trace-non-route skip > /tmp/runtime_mtp_ablation.json`
- `quantized-performance-path.md`: `python3 sim/scheduler/recommendations.py --trace-jsonl /path/to/route.jsonl --trace-input-format runtime --trace-non-route skip --trace-derive-cost-scale kv_tokens_p50 > /tmp/runtime_mtp_ablation.json`
- `quantized-single-spark.md`: `python3 scripts/render_quantized_single_spark_report.py "$OUT_DIR" --write "docs/baseline-quantized-single-spark0-YYYY-MM-DD.md"`
- `quantized-single-spark.md`: `ssh spark0@aitopatom-9ab9.local "ls -lh /home/spark0/models/ds4/*.gguf 2>/dev/null | sort -k5 -h"`
- `quantized-single-spark.md`: `ssh spark0@aitopatom-9ab9.local "for f in /home/spark0/models/ds4/*.gguf; do [ -r \"$f\" ] || continue; wc -c \"$f\"; done | sort -n | head"`
- `quantized-single-spark.md`: `python3 scripts/model_contract_inspect_quantized_artifact.py --path /abs/path/to/model.gguf`
- `quantized-single-spark.md`: `python3 scripts/model_contract_inspect_quantized_artifact.py --path /abs/path/to/model.gguf --json --require-mtp-complete`
- `quantized-single-spark.md`: `python3 scripts/model_contract_inspect_quantized_artifact.py --url https://huggingface.co/<repo>/resolve/<rev>/<file>.gguf --json`
- `baseline-quantized-single-spark0-2026-05-13T080107Z-quantized-single-spark0-smallest-credible.md`: `sha256: 31598c67c8b8744d3bcebcd19aa62253c6dc43cef3b8adf9f593656c9e86fd8c`
- `baseline-quantized-single-spark0-2026-05-13T003043Z-smallest.md`: `sha256: 31598c67c8b8744d3bcebcd19aa62253c6dc43cef3b8adf9f593656c9e86fd8c`
- `baseline-quantized-single-spark0-2026-05-12T141651Z-smallest.md`: `sha256: 31598c67c8b8744d3bcebcd19aa62253c6dc43cef3b8adf9f593656c9e86fd8c`

## Source Map

| Source | Lines | Main heading | Subsections |
|---|---:|---|---|
| `docs/quantized-performance-path.md` | 394 | Quantized Performance Path (Scheduler + MTP) | Thesis, Gate 0: MTP sidecar + one-token wiring (no full downloads), Gate 1: Real Quantized Generation, Gate 2: Runtime Instrumentation, Phase 0: Simulator-Only |
| `docs/quantized-single-spark.md` | 412 | Quantized Single-Spark Milestone | Definition of Done, Candidate Artifacts, MTP (multi-token prediction) expectations, MTP / tensor-key compatibility, First Run Shape |
| `docs/baseline-quantized-single-spark0-2026-05-13T080107Z-quantized-single-spark0-smallest-credible.md` | 162 | Baseline: Quantized Single-Spark Spark0 (DeepSeek V4 Flash auto: smallest_by_size_bytes (exclude: MTP/DFlash/draft/sidecar; include: IQ2/Q2_K/IQ3/Q3_K)) | Host, Repo + Upstream Revisions, Fixture Manifest, Command Line, Results |
| `docs/baseline-quantized-single-spark0-2026-05-13T003043Z-smallest.md` | 158 | Baseline: Quantized Single-Spark Spark0 (DeepSeek V4 Flash IQ2XXS smallest trunk (chat-v2)) | Host, Repo + Upstream Revisions, Fixture Manifest, Command Line, Results |
| `docs/baseline-quantized-single-spark0-2026-05-12T141651Z-smallest.md` | 153 | Baseline: Quantized Single-Spark Spark0 (DeepSeek V4 Flash IQ2XXS auto-select smallest) | Host, Repo + Upstream Revisions, Fixture Manifest, Command Line, Results |
