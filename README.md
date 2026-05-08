# ds4_on_spark

Purpose-built DeepSeek V4 Flash inference work for NVIDIA DGX Spark / GB10.

This repository starts from the design review in `docs/implementation-plan.md`:
a narrow engine, correctness-gated first, optimized for 2x Spark before any
4x topology or broader model support.

## Current Status

- Repo bootstrap: in progress.
- Spark discovery: one Spark is visible as `aitopatom-9ab9.local`.
- SSH transport: port 22 is reachable by hostname/link-local IPv6.
- SSH authentication: blocked until the `spark0` account password or key is fixed.
- First implementation target: collect hardware and kernel compatibility data.

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
- `scripts/spark_probe.sh`: remote Spark hardware/software probe.
- `scripts/mac_spark_discovery.sh`: Mac-side Spark discovery helper.

## Design Principle

Correctness comes before speed. Every kernel and scheduling optimization should
be gated by reproducible logits, traces, or benchmark evidence.

