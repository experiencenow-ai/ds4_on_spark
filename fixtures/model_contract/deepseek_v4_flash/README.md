# DeepSeek V4 Flash fixtures

These files are **small upstream metadata and reference sources** used to derive the DS4 model contract.

Pinned upstream commit: `6976c7ff1b30a1b2cb7805021b8ba4684041f136`

This directory must **never** include large checkpoint shards (`model-00001-of-*.safetensors`).

Included upstream sources (metadata only):

- `config.json`, `generation_config.json`
- `model.safetensors.index.json` (tensor key set; no weight shards)
- `contract_summary.json` (repo-generated, source-derived constants: topology, cache schedule, runtime params, tensor-key invariants (including `tensor_keys.required_top_level` and the `tensor_keys.required_layer_suffixes*` sets), `mtp.trust_gates`, plus `compat` mappings for interpreting external runtimes/configs)
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

Refresh + verify (one-shot):

```bash
scripts/model_contract_refresh_deepseek_v4_flash.sh
```

Pinned GGUF inspections (metadata-only; no full downloads):

- Pinned inspection JSON outputs live under `docs/gguf-inspect-*.json` and are produced by `scripts/model_contract_inspect_quantized_artifact.py --url ... --json` using HTTP Range reads (header + tensor table only).
- Refresh the pinned outputs reproducibly (Range reads only; refuses servers that don’t honor Range):

```bash
scripts/model_contract_refresh_v4flash_gguf_inspects.sh
```

Quantized artifacts (GGUF) are not stored here, but when inspecting a human-provided GGUF conversion note that some communities ship MTP weights as a separate sidecar file. `scripts/model_contract_inspect_quantized_artifact.py` supports passing multiple `--path` values (trunk + MTP sidecar) and emits a combined `mtp_present` summary in `--json` mode.
