# MTP Dummy Movement Proof

This experiment separates MTP data movement from MTP model math.

The question it answers is:

> If the MTP tensors, draft state, verifier rows, and raw-cache buffers are
> already resident, can the Spark CUDA data path move them fast enough to make
> speculative decode plausible?

It intentionally does **not** load a real trunk model or MTP sidecar. Instead it
compiles a temporary Spark-side CUDA program that allocates dummy buffers with
DeepSeek V4 Flash MTP-like dimensions and runs a draft/verify cadence:

- token embedding: `n_embd = 4096`
- HC stream: `n_hc * n_embd = 4 * 4096`
- MTP raw-cache rows: configurable row count and row bytes
- MTP draft logits row: `n_vocab = 163840`
- verifier logits rows: defaults to `draft_len`
- optional tiny D2H row-top copy per step
- optional cold H2D copy per step to mimic the current lazy tensor-cache
  slowdown seen when `e->mtp_ready` skips trunk startup cache preparation

Run:

```sh
./scripts/run_mtp_dummy_movement_proof_spark.sh spark0@172.16.11.228
```

Useful knobs:

```sh
STEPS=2048 RESIDENT_MIB=4096 ./scripts/run_mtp_dummy_movement_proof_spark.sh
COLD_MIB_PER_STEP=256 RUN_COLD_VARIANT=0 ./scripts/run_mtp_dummy_movement_proof_spark.sh
DRAFT_LEN=3 VERIFY_ROWS=3 ./scripts/run_mtp_dummy_movement_proof_spark.sh
```

Outputs are written under:

```text
/private/tmp/ds4_mtp_dummy_movement_proof/<timestamp>/
```

The important files are:

- `resident.json`: the proof target. This keeps MTP-like buffers resident and
  times only per-token dummy movement.
- `cold*.json`: same loop plus configured host-to-device cold copies per step.
  If resident is fast but cold collapses, the current real-runtime slowdown is
  almost certainly cache/readiness plumbing rather than draft quality.
- `report.md`: command metadata and result summary.

Go/no-go interpretation:

- If `resident.json` can sustain far above the target output rate, MTP data
  movement is not the bottleneck by itself.
- If `cold*.json` collapses in the same way real `--mtp` runs collapse, the next
  implementation target is the CUDA startup/model-cache path, not MTP accuracy.
- If resident is already slow, shrink the dummy movement contract until the
  exact expensive buffer is identified: logits row, raw-cache row, verifier rows,
  HC stream, or host roundtrip.
