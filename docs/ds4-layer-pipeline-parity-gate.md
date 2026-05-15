# DS4 Layer Pipeline Parity Gate

The Spark layer pipeline is not eligible for real DS4 generation work until
PP=1 and PP=N produce matching DS4 outputs under a declared comparison policy.
Fast payload movement and checksum integrity are necessary plumbing, but they
are not model parity.

## Reference Paths

PP=1 reference path:

```text
one runtime instance
full model in one process/device lane
same tokenizer, prompt tokens, model weights, quantization, runtime flags
```

PP=N contiguous stage path:

```text
coordinator
  -> stage 0 contiguous layers
  -> stage 1 contiguous layers
  -> ...
  -> stage N-1 contiguous layers + final head
```

The layer split must be manifest-driven. No parity artifact may encode a fixed
Spark count such as `spark_count`, `num_sparks`, or top-level `world_size`.

## Identity Fields

Every parity run must declare enough identity to make the comparison meaningful:

- `provider_id`
- `pipeline_id`
- `model_id`
- `runtime_id`
- tokenizer identity: either `tokenizer_sha256` or `tokenizer_id` plus
  `tokenizer_hash_status`
- `quantization_id`
- `stage_manifest_sha256`
- `stage_inventory`
- `layer_ranges`
- `boundary_state_layout`
- `boundary_after_layers`
- `input_tokens_sha256`
- `command_sha256`

The stage inventory identifies nodes and stage IDs. The layer ranges describe
contiguous ownership. Boundary state fields are intentionally explicit because
DeepSeek V4 Flash uses Hyper-Connections (`hc_mult=4`) and the actual crossing
state may be more than a simple hidden-state row.

## Comparison Kinds

Allowed `comparison_kind` values:

- `logits`
- `tokens`
- `hidden_state`
- `synthetic_integrity`

Only `logits`, `tokens`, or `hidden_state` may satisfy DS4 quality parity.
`synthetic_integrity` can prove ordering, checksums, callback insertion, and
transport mechanics, but it must not be treated as DS4 model parity.

## Tolerance Policy

Quantized runtimes are not expected to be bit-identical unless the runtime
guarantees deterministic kernels and reduction order. A parity artifact records:

- `tolerance.max_abs_error`
- `tolerance.mean_abs_error`
- `max_abs_error`
- `mean_abs_error`
- `token_match_count`
- `token_total_count`

For `comparison_kind: tokens`, a pass requires all compared tokens to match.
For `logits` and `hidden_state`, a pass requires numeric error metrics within
the declared tolerance and a non-empty token/sample count.

## Status Semantics

`not_run`:

- comparison has not been executed;
- output hashes and metrics may be empty or null;
- telemetry may record this but must not route real DS4 generation to the
  pipeline provider based on it.

`failed`:

- PP=1 and PP=N were compared and did not meet tolerance or token match policy;
- metrics and output hashes should be included when available;
- the telemetry record must include a human-readable detail.

`passed`:

- comparison was actually run;
- synthetic integrity is not enough;
- metrics and output hashes are present;
- the artifact hash validates;
- only then can `spark-layer-pipeline-run-v1` reference it as a quality parity
  artifact.

## Artifact Format

`ds4-layer-pipeline-parity-v1` is the replayable comparison artifact. Validate
with:

```sh
python3 scripts/validate_ds4_pipeline_parity.py fixtures/pipeline_parity/*.json
```

The first DS4 parity fixture is intentionally `not_run`. The synthetic fixture
is allowed to pass as transport integrity, but the validator and telemetry
validator prevent it from satisfying DS4 quality parity.
