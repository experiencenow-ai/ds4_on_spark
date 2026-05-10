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
- GPU poll util/power (min/p50/p90/max/mean; best-effort):

Token trace / routing (best-effort; when the runtime emits JSON token events):

- Token events:
- Per-token latency (ms p50/p90/p99):
- Routed experts (top5):
- Expert/batch/queue stats:
- MTP counters (draft/accepted/rejected):
- CUDA placement / fallback (best-effort):
  - `fattn_reservation_probe.json` (server sweep) and/or `fattn_cli_probe.json` (one-shot run)
  - `fattn_seen_disabled`, `fattn_seen_sched_reserve_cpu`, `fattn_id_min/max/missing_count`, `node_kind_cpu_top`
- Patch presence (optional, read-only):
  - `fattn_patch_probe.json` (source scan; `pad256_found`, `patch_artifact_sha256`)

## Raw Logs

Attach or paste minimal excerpts (redact secrets / private LAN details).

## Failure Modes (if any)

- Exit code:
- Stderr excerpt:
- Notes / suspected cause:
