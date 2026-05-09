# DeepSeek V4 Flash fixtures

These files are **small upstream metadata and reference sources** used to derive the DS4 model contract.

Pinned upstream commit: `6976c7ff1b30a1b2cb7805021b8ba4684041f136`

This directory must **never** include large checkpoint shards (`model-00001-of-*.safetensors`).

Included upstream sources (metadata only):

- `config.json`, `generation_config.json`
- `model.safetensors.index.json` (tensor key set; no weight shards)
- `contract_summary.json` (repo-generated, source-derived constants: topology, cache schedule, runtime params, tensor-key invariants, plus a derived `compat.transformers` view for external-runtime field-name mapping)
- `tokenizer.json`, `tokenizer_config.json`
- `encoding/*` (chat/tool/thinking encoder + gold vectors)
- `inference/*` (reference runtime semantics: MLA, CSA/HCA cache compression, MoE, MTP, FP8/FP4 quantization)

Refresh:

```bash
scripts/model_contract_fetch_deepseek_v4_flash.sh
```

Verify:

```bash
python3 scripts/model_contract_verify_deepseek_v4_flash.py
```
