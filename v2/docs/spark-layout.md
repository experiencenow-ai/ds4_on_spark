# Spark Layout

The node Git checkout and mutable model data are separate roles. The checkout
is `/home/<node>/sparkpipe`; model files never live inside that Git tree.

```text
/home/<node>/
├── sparkpipe/                 Git checkout
├── sparkdata/                 rank-local serving payloads
├── srcdata/                   rank-local reference and build inputs
├── extnvme/                   warm full-model storage when attached
└── kvcache/                   bounded rank-local KV backing
```

Every canonical root is a real directory. Symlink compatibility paths are
forbidden. When a node has an external disk, `extnvme` is that filesystem's
exact mount target; on a node without one it is an empty real directory.
`ds4_nvme` is a retired path and is reported as legacy state if it reappears.

## Naming

Use one short model name and an optional topology/encoding suffix:

```text
sparkdata/qwen3.6_27b.fp8.pp13/
sparkdata/dsv4_flash.fp8.pp13/
sparkdata/kimi_k3.mxfp4.pp13/
srcdata/dsv4_flash.fp8.pp13/
extnvme/dsv4_flash/
kvcache/dsv4_flash/pp13.bf16/
```

Rank-local payload directories are one manifest-controlled dataset tree. Do
not add organization, revision, checkpoint, or snapshot directory layers
above or below that dataset merely to preserve an old source layout. If PP13
and PP16 use the same layer files, keep one shared payload and put both
topology manifests beside it; do not duplicate the payload merely because the
topology differs.

The KV suffix names the cache representation, not the model's weight format.
The deployment selects the complete dataset name explicitly, so independent
experiments may coexist, for example `pp13.bf16`, `pp13.fp8`, and
`pp13.bf16.zstd`. A dataset manifest must pin the exact logical KV format and
backing codec. The current SparkPipe file-backed page store persists opaque
driver-native pages without transcoding, so only the driver's native format is
runnable today; a quantized or compressed suffix is a provisioned namespace,
not a claim that its codec has been implemented. Activation must fail loudly
unless both the driver and the generic page store advertise the selected
format.

The per-node internal-storage target is 1,000,000,000,000 bytes total for
`srcdata` plus `sparkdata`, and 2,500,000,000,000 bytes for `kvcache`. These are
end-state allocation ceilings, not permission to overcommit a filesystem.
Before enabling the KV ceiling, use the fleet's minimum measured free space
after canonical cleanup and retain room for the checkout, logs, manifests, and
the operating system.

Full source models belong on `extnvme` or cold storage. A node-local `srcdata`
dataset contains only the checkpoint shards needed for that rank's layers plus
common model metadata, pinned by a manifest. It is not a second full archive.

The contract is `layout/spark_layout.json`. Use the audit script before and
after migration:

```bash
python3 scripts/ds4_layout_audit.py --node-root /home/spark0
```

`ds4_layout_apply.sh` creates missing data roots and verifies that `sparkpipe`
is a real checkout of `sparkpipe/sparkpipe`. It never creates aliases, moves,
or deletes model data. Cleanup must be performed from an explicit, verified manifest.
Mount detection is exact: a path is considered mounted only when the filesystem
mount target is that path, not merely because it resides on the root volume.
Re-run `ds4_layout_apply.sh --apply` after an external-NVMe reconnect; it fails
loudly if any canonical root is a symlink or the checkout origin is wrong.

## Lifecycle policy

`layout/model_storage_policy.json` is the checked-in source of truth for model
roles. In particular, MiniMax H3 is warm full-model data but has no stage
payload until a component-aware runtime adapter exists. QuantTrio GLM-5.2 is
cold-only; its internal copies must not be treated as production inputs.

Inspect a node without changing it:

```bash
python3 scripts/ds4_layout_inventory.py --node-root /home/spark0
```

Stage a rank-local reference or processed payload by hardlinking it on the
same filesystem (or copying across filesystems), then hashing every file into
an immutable canonical manifest:

```bash
python3 scripts/ds4_layout_stage.py \
  --node-root /home/spark0 \
  --root srcdata \
  --dataset dsv4_flash.fp8.pp13 \
  --source /path/to/rank0-stage-source \
  --apply
python3 scripts/ds4_layout_stage.py \
  --node-root /home/spark0 \
  --root srcdata \
  --dataset dsv4_flash.fp8.pp13 \
  --verify
```

The inventory reports both visible path allocation and hardlink-deduplicated
allocation. Use the JSON output to create a per-node cleanup manifest. Cleanup
is then checked against the recorded byte and file counts, refuses canonical
roots, mounts, symlinks, Git trees, and open paths, and writes a receipt under
`sparkdata/.layout/receipts`:

Generate the manifest with the repository tool so its snapshot fields cannot be
forgotten:

```bash
python3 scripts/ds4_layout_manifest.py \
  --node-root /home/spark0 \
  --path /home/spark0/sparkpipe_artifacts \
  --action delete \
  --reason "retired experimental artifacts; no live references"
```

The generator preserves the lexical path while validating it, so a symlink
cannot be resolved into a deletable target.

```bash
python3 scripts/ds4_layout_cleanup.py \
  --node-root /home/spark0 \
  --manifest /path/to/spark0-cleanup.json
python3 scripts/ds4_layout_cleanup.py \
  --node-root /home/spark0 \
  --manifest /path/to/spark0-cleanup.json \
  --apply
```

An archive operation additionally requires an explicit mounted archive root:

```bash
python3 scripts/ds4_layout_cleanup.py \
  --node-root /home/spark0 \
  --manifest /path/to/spark0-archive.json \
  --archive-root /home/spark0/extnvme/archive
```

There is no recursive "clean old models" mode. A model is removed only after
its complete replacement has a verified manifest in warm or cold storage.
