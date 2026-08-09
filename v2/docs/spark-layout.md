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
