# DS4 Multispark Owned Expert Residency

This is the first concrete multispark contract for the DS4 Flash path.

The goal is not to load every model, or every expert, on every Spark. The goal
is to load everything each Spark needs for its assigned work:

- every rank has access to the model file or CPU mmap needed to resolve tensor
  metadata
- only the MoE expert slices owned by that rank should be made GPU-resident
- dense/shared runtime state is handled by the next runtime contract, not by
  duplicating all experts everywhere
- routing is table-driven, so changing from 3 Sparks to 8 Sparks is a generated
  artifact change, not a CUDA rewrite

## Inputs

Build an owner table from `ffn_moe_topk` dumps:

```bash
python3 scripts/build_ds4_expert_owner_table.py \
  --dump-dir /path/to/topk-dump \
  --pos 0 \
  --topk 6 \
  --experts 256 \
  --logical-lanes 32 \
  --sparks 3 \
  --json-out /tmp/ds4-owner-table-sparks3.json
```

Use `--sparks 8` for the projected 8-Spark layout. There should be no
hardcoded Spark count in runtime code.

## Per-Rank Manifests

Turn the owner table into deployable residency manifests:

```bash
python3 scripts/build_ds4_multispark_expert_manifests.py \
  --owner-table-json /tmp/ds4-owner-table-sparks3.json \
  --out-dir /tmp/ds4-owned-experts-sparks3 \
  --emit-binary
```

This writes:

- `manifest.json`: cluster-level index and source hash
- `rank-000.json`, `rank-001.json`, ...: owned expert IDs by layer
- `rank-000.bin`, `rank-001.bin`, ...: optional C/CUDA runtime bitsets

Each rank file contains `owned_experts_by_layer`. The loader should interpret
that as the exact list of MoE expert slices to keep GPU-resident for that rank.
The binary form is a fixed 128-byte little-endian header followed by layer-major
owned-expert bitsets, so runtime code can query ownership without parsing JSON.

The runtime config now has generic fields for this handoff:

```bash
DS4_WORLD_SIZE=3
DS4_RANK=1
DS4_EXPERT_OWNER_TABLE_PATH=/tmp/ds4-owned-experts-sparks3/expert_owner_table_sparks3.json
DS4_EXPERT_MANIFEST_PATH=/tmp/ds4-owned-experts-sparks3/rank-001.json
```

The same variables work for any rank count; only the generated paths and rank
values change.

## Runtime Contract

For layer `L` and expert `E`, `owner_table[L][E]` is the rank that owns the
expert output. The scheduler sends the expert work to that rank and receives the
expert contribution back for the token/batch slot.

The immediate implementation target is expert-parallel residency:

1. all ranks load common metadata and the shared runtime buffers they need
2. each rank GPU-loads only its owned MoE experts from its rank manifest
3. router/topk output is exchanged as compact `(layer, token, expert, weight)`
   work items
4. each rank computes its owned expert work in batches
5. results are reduced back into the post-MoE token buffer

This keeps the number of Sparks generic. Current bring-up uses 3 ranks; the
same table/exporter path should generate the 8-rank owner map later.

## Future Policy: Hot Expert Replicas

The current manifest is a strict primary-owner partition: each expert appears on
exactly one rank per layer. That is the right first contract because it is easy
to validate and route.

If the transition stats show a small set of hot experts is creating avoidable
cross-Spark traffic, a later policy can add secondary replicas. The runtime
should still keep one primary owner for deterministic routing and accounting,
then allow the scheduler to choose a local replica when the extra GPU residency
cost buys measurable throughput.
