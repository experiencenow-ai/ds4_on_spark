# Ds4 Pipeline

> Supersedes: `docs/ds4-mtp-slowpath-status.md`, `docs/ds4-layer-pipeline-parity-gate.md`, `docs/ds4-expert-mod32-ceiling.md`, `docs/ds4-multispark-owned-expert-residency.md`, `docs/ds4-expert-transition-affinity.md`, `docs/ds4-vllm-performance-pause-summary.md`, `docs/ds4-performance-icebergs-current.md`, `docs/ds4-spark-layer-pipeline-plan.md`, `docs/resident-batched-decode.md`, `docs/lane_c_projection.md`, `docs/expert-scaling-proof-plan.md`

This is the canonical document for this topic. Update this file instead of adding a new overlapping note.

## Scope

- Consolidates 11 previous document(s) into one non-overlapping reference.
- Preserves stable commands, constraints, and source inventory; removes per-iteration narrative duplication.
- Historical probe/status fragments should live in git history, not as active docs.

## Current Guidance

- `ds4-mtp-slowpath-status.md`: DS4 MTP Slowpath Status (56 lines).
- `ds4-layer-pipeline-parity-gate.md`: DS4 Layer Pipeline Parity Gate (212 lines).
- `ds4-expert-mod32-ceiling.md`: DS4 Expert Mod-32 Ceiling (112 lines).
- `ds4-multispark-owned-expert-residency.md`: DS4 Multispark Owned Expert Residency (96 lines).
- `ds4-expert-transition-affinity.md`: DS4 Expert Transition Affinity (80 lines).
- `ds4-vllm-performance-pause-summary.md`: DS4 vLLM Performance Pause Summary (190 lines).
- `ds4-performance-icebergs-current.md`: DS4 Performance Icebergs: Current Truth (482 lines).
- `ds4-spark-layer-pipeline-plan.md`: DS4 Spark Layer Pipeline Plan (315 lines).
- `resident-batched-decode.md`: Resident Batched Decode (96 lines).
- `lane_c_projection.md`: Lane C PP=3 K Projection (58 lines).
- `expert-scaling-proof-plan.md`: Expert Scaling Proof Plan (252 lines).

## Command Inventory

- `ds4-layer-pipeline-parity-gate.md`: `python3 scripts/validate_ds4_pipeline_parity.py fixtures/pipeline_parity/*.json`
- `ds4-layer-pipeline-parity-gate.md`: `python3 scripts/ds4_stage_boundary_shape_probe.py \`
- `ds4-layer-pipeline-parity-gate.md`: `python3 scripts/ds4_local_ppn_parity_probe.py \`
- `ds4-layer-pipeline-parity-gate.md`: `python3 scripts/compare_ds4_pp1_ppn_outputs.py export-ppn-from-stage-handoff \`
- `ds4-layer-pipeline-parity-gate.md`: `python3 scripts/compare_ds4_pp1_ppn_outputs.py compare \`
- `ds4-expert-mod32-ceiling.md`: `python3 scripts/ds4_expert_mod32_ceiling.py --show-experts`
- `ds4-expert-mod32-ceiling.md`: `python3 scripts/ds4_expert_mod32_ceiling.py --sparks 10 --show-experts`
- `ds4-multispark-owned-expert-residency.md`: `python3 scripts/build_ds4_expert_owner_table.py \`
- `ds4-multispark-owned-expert-residency.md`: `python3 scripts/build_ds4_multispark_expert_manifests.py \`
- `ds4-multispark-owned-expert-residency.md`: `DS4_WORLD_SIZE=3`
- `ds4-multispark-owned-expert-residency.md`: `DS4_RANK=1`
- `ds4-multispark-owned-expert-residency.md`: `DS4_EXPERT_OWNER_TABLE_PATH=/tmp/ds4-owned-experts-sparks3/expert_owner_table_sparks3.json`
- `ds4-multispark-owned-expert-residency.md`: `DS4_EXPERT_MANIFEST_PATH=/tmp/ds4-owned-experts-sparks3/rank-001.json`
- `ds4-expert-transition-affinity.md`: `python3 scripts/analyze_ds4_expert_transitions.py \`
- `ds4-expert-transition-affinity.md`: `python3 scripts/ds4_topk_dump_recommendations.py \`
- `ds4-expert-transition-affinity.md`: `python3 scripts/build_ds4_expert_owner_table.py \`
- `ds4-spark-layer-pipeline-plan.md`: `python3 scripts/ds4_pipeline_telemetry.py combine \`
- `ds4-spark-layer-pipeline-plan.md`: `python3 scripts/ds4_pipeline_telemetry.py validate \`
- `ds4-spark-layer-pipeline-plan.md`: `python3 scripts/validate_ds4_pipeline_parity.py fixtures/pipeline_parity/*.json`
- `ds4-spark-layer-pipeline-plan.md`: `python3 scripts/ds4_stage_boundary_shape_probe.py --probe-status not_available`
- `ds4-spark-layer-pipeline-plan.md`: `python3 scripts/ds4_stage_boundary_shape_probe.py \`
- `ds4-spark-layer-pipeline-plan.md`: `python3 scripts/ds4_local_ppn_parity_probe.py \`
- `resident-batched-decode.md`: `./scripts/codex_task.py spark-resident-batched-decode`
- `resident-batched-decode.md`: `./scripts/codex_task.py spark-resident-batched-decode --run`
- `resident-batched-decode.md`: `./scripts/codex_task.py spark-resident-batched-decode \`
- `expert-scaling-proof-plan.md`: `DS4_CUDA_MOE_PROFILE=1 \`
- `expert-scaling-proof-plan.md`: `./ds4-bench \`
- `expert-scaling-proof-plan.md`: `DS4_CUDA_MOE_PROFILE=1 DS4_CUDA_MOE_NO_EXPERT_TILES=1 ...`
- `expert-scaling-proof-plan.md`: `DS4_CUDA_MOE_PROFILE=1 DS4_CUDA_MOE_NO_EXPERT_TILES=1 DS4_CUDA_MOE_NO_P2=1 ...`
- `expert-scaling-proof-plan.md`: `python3 scripts/analyze_ds4_moe_profile.py \`
- `expert-scaling-proof-plan.md`: `DS4_DIR=/home/spark0/src/ds4_perf_stack_20260515T080833 \`
- `expert-scaling-proof-plan.md`: `python3 scripts/ds4_topk_dump_to_trace_jsonl.py \`
- `expert-scaling-proof-plan.md`: `python3 sim/scheduler/scheduler_sim.py \`
- `expert-scaling-proof-plan.md`: `python3 scripts/ds4_topk_dump_recommendations.py \`
- `expert-scaling-proof-plan.md`: `python3 scripts/analyze_ds4_moe_profile.py --json /tmp/ds4_decode.err`
- `expert-scaling-proof-plan.md`: `python3 scripts/codex_task.py analyze-moe-log --json /tmp/ds4_decode.err`

## Source Map

| Source | Lines | Main heading | Subsections |
|---|---:|---|---|
| `docs/ds4-mtp-slowpath-status.md` | 56 | DS4 MTP Slowpath Status | 2026-05-18 corrected K=2 status, K=2 direct verifier status, K=3 prefix-frontier status, Prior slow verifier status |
| `docs/ds4-layer-pipeline-parity-gate.md` | 212 | DS4 Layer Pipeline Parity Gate | Reference Paths, Identity Fields, Parity Levels, Comparison Kinds, Tolerance Policy |
| `docs/ds4-expert-mod32-ceiling.md` | 112 | DS4 Expert Mod-32 Ceiling | Assumptions, Ceiling, Expert Map |
| `docs/ds4-multispark-owned-expert-residency.md` | 96 | DS4 Multispark Owned Expert Residency | Inputs, Per-Rank Manifests, Runtime Contract, Future Policy: Hot Expert Replicas |
| `docs/ds4-expert-transition-affinity.md` | 80 | DS4 Expert Transition Affinity | Analyzer, Metrics, Greedy Table |
| `docs/ds4-vllm-performance-pause-summary.md` | 190 | DS4 vLLM Performance Pause Summary | Current Decision, Measured Data, What Worked, What Did Not Work, Runtime Map |
| `docs/ds4-performance-icebergs-current.md` | 482 | DS4 Performance Icebergs: Current Truth | Current Best, MTP Verifier Economics, B/Depth Probe, Split Rebalance, Output Head |
| `docs/ds4-spark-layer-pipeline-plan.md` | 315 | DS4 Spark Layer Pipeline Plan | Throughput Model, Runtime Ownership, Activation Message V1, Distributed Prefix Handle V1, Prefill And Decode |
| `docs/resident-batched-decode.md` | 96 | Resident Batched Decode | Run, Outputs, Interpretation, Spark0 Proof Run |
| `docs/lane_c_projection.md` | 58 | Lane C PP=3 K Projection | Formula, Result |
| `docs/expert-scaling-proof-plan.md` | 252 | Expert Scaling Proof Plan | What Is Already True, New Kernel A/B: Valid Prefill Activations, Direct Routed-MoE Batch Ladder, Artificial But Valid Scaling Fixtures, Full Decode Gate |
