# Baseline

> Supersedes: `docs/baseline-git-shim.md`, `docs/baseline-runtime.md`, `docs/baseline-fattn-reservation.md`, `docs/baseline-template.md`, `docs/baseline-batching-throughput.md`, `docs/baseline-vllm-matrix.md`, `docs/baseline-multislot-parallel2.md`, `docs/baseline-fixtures.md`, `docs/baseline-smoke-eval.md`

This is the canonical document for this topic. Update this file instead of adding a new overlapping note.

## Scope

- Consolidates 9 previous document(s) into one non-overlapping reference.
- Preserves stable commands, constraints, and source inventory; removes per-iteration narrative duplication.
- Historical probe/status fragments should live in git history, not as active docs.

## Current Guidance

- `baseline-git-shim.md`: Baseline: Git Shim For Worktree Checkouts (53 lines).
- `baseline-runtime.md`: Baseline Runtime (314 lines).
- `baseline-fattn-reservation.md`: Baseline: DS4 Flash-Attention Reservation Probe (127 lines).
- `baseline-template.md`: Baseline Report Template (88 lines).
- `baseline-batching-throughput.md`: Baseline: llama-server Batching + Concurrency Throughput Sweep (157 lines).
- `baseline-vllm-matrix.md`: Baseline: vLLM Matrix Runner (Ling/Qwen/DFlash) (141 lines).
- `baseline-multislot-parallel2.md`: Baseline: llama.cpp Multi-slot (`--parallel 2`) Reservation Failures (103 lines).
- `baseline-fixtures.md`: Baseline Fixtures (83 lines).
- `baseline-smoke-eval.md`: Baseline: vLLM Smoke Eval (Deterministic) (75 lines).

## Command Inventory

- `baseline-git-shim.md`: `git --git-dir=.codex_git --work-tree=. fetch origin`
- `baseline-git-shim.md`: `git --git-dir=.codex_git --work-tree=. checkout -b codex/loop-baseline-runtime-<suffix> origin/main`
- `baseline-git-shim.md`: `DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local`
- `baseline-runtime.md`: `DS4_DIR=/remote/path/to/ds4 \`
- `baseline-fattn-reservation.md`: `python3 /tmp/benchmark_llamacpp_server_sweep.py`
- `baseline-batching-throughput.md`: `python3 /tmp/benchmark_llamacpp_server_throughput_sweep.py`
- `baseline-fixtures.md`: `sha256: <sha256>`

## Source Map

| Source | Lines | Main heading | Subsections |
|---|---:|---|---|
| `docs/baseline-git-shim.md` | 53 | Baseline: Git Shim For Worktree Checkouts | Create the shim, Use the shim for git commands, Use the shim for baseline reports |
| `docs/baseline-runtime.md` | 314 | Baseline Runtime | Safety Gates (non-negotiable), One-command entrypoint (Mac → Spark), Ling/Qwen/DFlash ladder (Spark0; vLLM), One-command entrypoint (Mac local: antirez/ds4), One-command entrypoint (Spark remote: antirez/ds4) |
| `docs/baseline-fattn-reservation.md` | 127 | Baseline: DS4 Flash-Attention Reservation Probe | Symptom, Root Cause (as observed on Spark0), Narrow Patch, Probe (Regression Check), Non-goals / Next Bottleneck |
| `docs/baseline-template.md` | 88 | Baseline Report Template | Host, Repo + Upstream Revisions, Fixture Manifest, Command Line, Results |
| `docs/baseline-batching-throughput.md` | 157 | Baseline: llama-server Batching + Concurrency Throughput Sweep | Current Spark0 Snapshot (2026-05-12), What It Produces, Canonical Run Shape (Mac → Spark0), Interpreting Results |
| `docs/baseline-vllm-matrix.md` | 141 | Baseline: vLLM Matrix Runner (Ling/Qwen/DFlash) | Defaults (cost control), Example invocation, Matrix TSV format, Recommended measurement order |
| `docs/baseline-multislot-parallel2.md` | 103 | Baseline: llama.cpp Multi-slot (`--parallel 2`) Reservation Failures | Symptom, Local Fixes Under Test (Spark0), Probe: Throughput Sweep Log Scan (Recommended), What To Record, Cheap Source Probe (Patch Presence) |
| `docs/baseline-fixtures.md` | 83 | Baseline Fixtures | Fixture Policy, Fixture Inventory (by baseline), Fixture Manifest Template |
| `docs/baseline-smoke-eval.md` | 75 | Baseline: vLLM Smoke Eval (Deterministic) | How To Run (Mac → Spark), Task Set (Current), CSV Ingestion Behavior |
