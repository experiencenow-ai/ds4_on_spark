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

- Public quality prior:
- Public quality basis/source:
- Local quality score:
- Passed tasks:
- Total tasks:
- Quality score:

TTFT:

Prefill throughput:

Generation throughput:

Quality-adjusted generation throughput:

Correct task rate:

Tokens per success:

Pareto dominated by:

Memory:

- Max RSS:
- GPU mem (before/after):

## Raw Logs

Attach or paste minimal excerpts (redact secrets / private LAN details).

## Failure Modes (if any)

- Exit code:
- Stderr excerpt:
- Notes / suspected cause:
