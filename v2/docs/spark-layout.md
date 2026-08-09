# Spark Layout

The node Git checkout and mutable model data are separate roles. The checkout
is `/home/<node>/sparkpipe`; model files never live inside that Git tree.

```text
/home/<node>/
├── sparkpipe/                 Git checkout
├── sparkdata/                 rank-local serving payloads
├── srcdata/                   local build inputs only
└── extnvme/                   warm full-model storage when attached
```

`ds4_nvme` is a legacy path. During migration, `extnvme` may be a symlink to a
mounted `ds4_nvme` filesystem so existing services remain readable. The
canonical name in new configuration is `extnvme`.

## Naming

Use one short model name and an optional topology/encoding suffix:

```text
sparkdata/qwen3.6_27b.fp8.pp13/
sparkdata/dsv4_flash.fp8.pp13/
sparkdata/kimi_k3.mxfp4.pp13/
srcdata/dsv4_flash/
extnvme/dsv4_flash/
```

Rank-local payload directories contain flat files and a manifest. Do not add
organization, revision, checkpoint, or snapshot directory layers below the
dataset directory. If PP13 and PP16 use the same layer files, keep one shared
payload and put both topology manifests beside it; do not duplicate the
payload merely because the topology differs.

Full source models belong on `extnvme` or cold storage. A node-local `srcdata`
tree is permitted only when that node is actively building a payload and must
contain the local build input, not a second full archive.

The contract is `layout/spark_layout.json`. Use the audit script before and
after migration:

```bash
python3 scripts/ds4_layout_audit.py --node-root /home/spark0
```

`ds4_layout_apply.sh` only creates roots and aliases. It never moves or deletes
model data. Cleanup must be performed from an explicit, verified manifest.

## Lifecycle policy

`layout/model_storage_policy.json` is the checked-in source of truth for model
roles. In particular, MiniMax H3 is warm full-model data but has no stage
payload until a component-aware runtime adapter exists. QuantTrio GLM-5.2 is
cold-only; its internal copies must not be treated as production inputs.

Inspect a node without changing it:

```bash
python3 scripts/ds4_layout_inventory.py --node-root /home/spark0
```

The inventory reports both visible path allocation and hardlink-deduplicated
allocation. Use the JSON output to create a per-node cleanup manifest. Cleanup
is then checked against the recorded byte and file counts, refuses canonical
roots, mounts, symlinks, Git trees, and open paths, and writes a receipt under
`sparkdata/.layout/receipts`:

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
