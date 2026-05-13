# MTP Acceptance Sweep (Trace Summary)

Before claiming any MTP speedup on Spark/CUDA, run a short **multi-prompt acceptance sweep** and record acceptance statistics in a machine-readable way.

This repo does **not** prescribe the runtime implementation. It only provides a small summarizer that turns a runtime JSONL log into a stable acceptance summary.

## Required per-step fields (runtime log)

Emit (at least) one JSON object per verify step / output token with either:

- `mtp_accept_len` (preferred; integer `>= 1`), or
- `accepted_mtp` (fallback; integer `>= 0`, interpreted as `mtp_accept_len = accepted_mtp + 1`)

Notes:

- `mtp_accept_len` is treated as “accepted tokens including the base token”, so `accepted_draft_tokens = mtp_accept_len - 1`.
- The summarizer can scan for embedded JSON objects inside log lines (default), so both pure JSONL and `INFO ... {json} ...` logs are supported.

## Summarize acceptance

Use `--draft-len` when you know `gamma` (enables histogram + acceptance_rate):

```bash
python3 scripts/summarize_mtp_acceptance_trace.py --in-jsonl /path/to/runtime.log.jsonl --draft-len 2
```

If your logs are strict JSONL already, you can disable substring scanning:

```bash
python3 scripts/summarize_mtp_acceptance_trace.py --in-jsonl /path/to/runtime.log.jsonl --draft-len 2 --extract-substrings 0
```

Recommended: include the resulting JSON blob verbatim in the Spark run report alongside the exact runtime command line, commit, and model artifact hashes.

