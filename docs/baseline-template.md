# Baseline Report Template

Date (UTC):

Baseline type:

- [ ] antirez/ds4 (Mac / Metal)
- [ ] llama.cpp (Spark / CUDA)
- [ ] vLLM (Spark / reference)
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

TTFT:

Prefill throughput:

Generation throughput:

Memory:

- Max RSS:
- GPU mem (before/after):
- GPU poll mem used (min/max/delta):

Token trace / routing (best-effort; when the runtime emits JSON token events):

- Token events:
- Per-token latency (ms p50/p90/p99):
- Routed experts (top5):
- Expert/batch/queue stats:
- MTP counters (draft/accepted/rejected):

## Raw Logs

Attach or paste minimal excerpts (redact secrets / private LAN details).

## Failure Modes (if any)

- Exit code:
- Stderr excerpt:
- Notes / suspected cause:
