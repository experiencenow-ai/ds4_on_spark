# Baseline Report Template

Date (UTC):

Baseline type:

- [ ] antirez/ds4 (Mac / Metal)
- [ ] llama.cpp (Spark / CUDA)
- [ ] vLLM (Spark / reference)
- [ ] Ling 2.6 Flash target-only (Spark / vLLM or SGLang)
- [ ] Qwen target-only (Spark / vLLM or SGLang)
- [ ] Qwen + DFlash draft (Spark / speculative)
- [ ] other target + DFlash draft (Spark / speculative)
- [ ] ds4_on_spark (future)

## Host

- Hostname:
- OS / kernel:
- CPU:
- RAM:
- GPU:
- Driver / CUDA:

## Repo + Upstream Revisions

- ds4_on_spark commit:
- Upstream commit(s):
  - antirez/ds4:
  - ggml-org/llama.cpp:
  - vLLM:

## Fixture Manifest

(paste one block per artifact; see `docs/baseline-fixtures.md`)

## Command Line

```sh
<exact command>
```

## Results

Quality:

- `public_quality_prior`:
- `public_quality_basis` / `public_quality_source`:
- `passed_tasks`:
- `total_tasks`:
- `local_quality_score`:
- `quality_score`:

TTFT:

- `ttft_s`:

Speed:

- `prefill_tps`:
- `decode_tps`:
- `total_wall_s`:
- `output_tokens`:

Tradeoff:

- `quality_adjusted_decode_tps`:
- `correct_task_rate`:
- `tokens_per_success`:

- `dominated_by` (Pareto):

Memory:

- Max RSS:
- GPU mem (before/after):

## Raw Logs

Attach or paste minimal excerpts (redact secrets / private LAN details).

## Failure Modes (if any)

- Exit code:
- Stderr excerpt:
- Notes / suspected cause:
