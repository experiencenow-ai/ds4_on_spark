# ds4_on_spark

Spark local-inference performance lab for NVIDIA DGX Spark / GB10 (repo name is historical shorthand).

Primary tracks:

- DeepSeek V4 Flash target-only throughput + correctness work (keep DeepSeek claims isolated).
- Comparator targets (Qwen/Ling/Gemma/GLM-class) to ground quality/speed tradeoffs (target-only until paired).
- Speculative decoding / MTP / DFlash draft+target pairs (keep DFlash claims isolated; do not mix with target-only wins).
- Spark/Blackwell runtime work (llama.cpp/vLLM/SGLang/CUDA/TE/CUTLASS references as needed).

The repository starts from `docs/implementation-plan.md`; correctness gating remains non-negotiable, but the scope is broader than a single-model bring-up.

## Current Status

- Repo bootstrap: in progress.
- Spark ring map: see root `SPARKNETWORK.md`.
- Spark0 SSH is verified as `spark0@aitopatom-9ab9.local`.
- Spark1 SSH is verified as `spark1@edgexpert-d623.local`.
- Spark2 is verified as `spark2@aitopatom-931a.local` over the 200G ring via
  Spark0/Spark1 jump SSH; its direct Mac Wi-Fi SSH path still needs repair.
- First implementation target: keep the ring inventory and redacted probe
  snapshots current before multi-node Centaur runs.

## Near-Term Work

1. Establish passwordless SSH from the Mac to the Spark.
2. Run `scripts/spark_probe.sh` and commit the redacted probe output.
3. Import upstream references: `antirez/ds4`, DeepSeek V4 HF inference code,
   DeepGEMM, and any Spark-specific llama.cpp experiments.
4. Build the model contract: exact tensors, cache semantics, tokenizer/encoding,
   and correctness oracle fixtures.
5. Spike FP4/FP8 kernel paths on GB10 before committing to custom kernels.

## Repository Layout

- `docs/implementation-plan.md`: phased plan and parallel tracks.
- `docs/automation-loops.md`: proposed 30-minute automation loops.
- `docs/spark-access.md`: current Spark networking and SSH notes.
- `docs/expert-scaling-proof-plan.md`: CUDA expert-queue proof gates.
- `docs/cuda-expert-queue-dummy-benchmark.md`: synthetic CUDA expert movement benchmark.
- `docs/centaur-ds4-prefix-kv-contract.md`: Centaur/DS4 prefix KV boundary.
- `scripts/spark_probe.sh`: remote Spark hardware/software probe.
- `scripts/mac_spark_discovery.sh`: Mac-side Spark discovery helper.

## Design Principle

Correctness comes before speed. Every kernel and scheduling optimization should
be gated by reproducible logits, traces, or benchmark evidence.
