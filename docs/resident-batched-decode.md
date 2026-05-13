# Resident Batched Decode

Goal: turn the existing llama-server throughput sweep into a one-command,
resident decode path that can be run from Codex without hand-built SSH command
lines.

This is the first runtime-facing step after the one-token MTP probe. It starts a
single resident `llama-server`, sends concurrent `/completion` waves, and records
aggregate decode throughput (`agg_generated_tok_s`) plus reservation/fallback
signals from the server log.

## Run

Dry run / gated report:

```bash
./scripts/codex_task.py spark-resident-batched-decode
```

Actual Spark0 run:

```bash
./scripts/codex_task.py spark-resident-batched-decode --run
```

Useful short proof run:

```bash
./scripts/codex_task.py spark-resident-batched-decode \
  --run \
  --n-predict 16 \
  --concurrency "1 2 4" \
  --prompt-words 16
```

The wrapper defaults to the staged Spark0 llama.cpp fork and auto-selects the
smallest credible staged DeepSeek V4 Flash trunk GGUF:

- `LLAMA_SERVER=/home/spark0/src/llama.cpp-kamnxt/build-cuda/bin/llama-server`
- `MODEL_GGUF_GLOB=/home/spark0/models/ds4/*.gguf`
- exclude: `MTP|DFlash|draft|sidecar`
- include: `IQ2|Q2_K|IQ3|Q3_K`

Override `--model-gguf` for an exact model path.

## Outputs

Local reports are written under:

```text
/private/tmp/ds4_on_spark_resident_batched_decode/<timestamp>/
```

Key files:

- `summary.json`: top-level `ok`, artifacts, and `best_decode`.
- `resident_batched_decode.md`: human-readable report.
- `resident_batched_decode/<remote-dir>/throughput_sweep.jsonl`: one row per
  concurrency wave.
- `resident_batched_decode/<remote-dir>/throughput_best_decode.json`: best row
  by aggregate decode throughput.
- `remote_stdout.txt` / `remote_stderr.txt`: runner logs.

## Interpretation

This path measures resident server throughput, not MTP acceptance or expert
routing. It is the correct next baseline for user-facing decode because it keeps
the model loaded and exercises concurrent batch entries. Expert routing work
must be gated on real runtime traces that expose selected expert IDs, top-k
scores, and per-expert batch sizes.

## Spark0 Proof Run

Short run on 2026-05-13:

```bash
./scripts/codex_task.py spark-resident-batched-decode \
  --run \
  --port 18086 \
  --n-predict 16 \
  --concurrency "1 2 4" \
  --prompt-words 16 \
  --model-gguf /home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2-imatrix.gguf
```

Best decode row:

- concurrency 1: 7.89 aggregate generated tok/s
- concurrency 2: 11.08 aggregate generated tok/s
- concurrency 4: 11.36 aggregate generated tok/s
- best row: `parallel=8`, `batch=2048`, `ubatch=512`, `ok_count=4`,
  `error_count=0`, `wave_wall_s=5.63`

This proves the resident batched path is live and gives a measurable batching
gain over one active request, but the early plateau also confirms that larger
gains still need MTP acceptance and/or real expert-routing instrumentation.
