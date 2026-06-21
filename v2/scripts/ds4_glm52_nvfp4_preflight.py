#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path


DEFAULT_PARTITION = [6,4,4,4,4,8,8,8,8,8,4,4,8]


def fail(errors,msg):
    errors.append(msg)


def load_json(path):
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def stage_starts(partition):
    starts = []
    cur = 0
    for width in partition:
        starts.append(cur)
        cur += width
    return starts


def check_model_config(model_dir, partition, errors, warnings):
    cfg_path = model_dir / "config.json"
    if not cfg_path.exists():
        fail(errors,f"missing {cfg_path}")
        return
    cfg = load_json(cfg_path)
    if cfg.get("architectures") != ["GlmMoeDsaForCausalLM"]:
        fail(errors,f"unexpected architectures={cfg.get('architectures')!r}")
    if cfg.get("model_type") != "glm_moe_dsa":
        fail(errors,f"unexpected model_type={cfg.get('model_type')!r}")
    if int(cfg.get("num_hidden_layers", -1)) != sum(partition):
        fail(errors,f"num_hidden_layers={cfg.get('num_hidden_layers')!r} does not match partition sum {sum(partition)}")
    qcfg = cfg.get("quantization_config") or {}
    if str(qcfg.get("quant_method","")).lower() != "modelopt":
        fail(errors,f"quant_method={qcfg.get('quant_method')!r}, expected modelopt")
    if str(qcfg.get("quant_algo","")).upper() != "NVFP4":
        fail(errors,f"quant_algo={qcfg.get('quant_algo')!r}, expected NVFP4")
    group = (qcfg.get("config_groups") or {}).get("group_0") or {}
    for key in ("weights","input_activations"):
        spec = group.get(key) or {}
        if spec.get("type") != "float" or int(spec.get("num_bits", -1)) != 4 or int(spec.get("group_size", -1)) != 16:
            fail(errors,f"quantization_config group_0.{key}={spec!r}, expected float 4-bit group_size 16")
    indexer_types = cfg.get("indexer_types") or []
    for start in stage_starts(partition):
        if start >= len(indexer_types):
            fail(errors,f"stage start {start} is beyond indexer_types length {len(indexer_types)}")
        elif indexer_types[start] != "full":
            fail(errors,f"stage start {start} has indexer_type={indexer_types[start]!r}, expected full")
    if (model_dir / "model-mtp.safetensors").exists():
        warnings.append("model-mtp.safetensors is present; recipe keeps MTP disabled until a separate PP-safe canary passes")


def check_files(model_dir, expect_shards, errors):
    shards = sorted(model_dir.glob("model-*-of-*.safetensors"))
    part_files = sorted(model_dir.glob("*.part"))
    if len(shards) != expect_shards:
        fail(errors,f"found {len(shards)} completed model shards, expected {expect_shards}")
    if part_files:
        fail(errors,f"found partial files: {', '.join(p.name for p in part_files[:5])}")
    for name in ("model.safetensors.index.json","tokenizer.json","tokenizer_config.json"):
        if not (model_dir / name).exists():
            fail(errors,f"missing required file {name}")


def check_vllm_source(source_root, errors, warnings):
    sys.path.insert(0,str(source_root))
    try:
        from vllm.model_executor.layers.quantization import QUANTIZATION_METHODS
        from vllm.model_executor.layers.quantization.modelopt import ModelOptNvFp4Config
    except Exception as exc:
        fail(errors,f"could not import vLLM NVFP4 support from {source_root}: {exc}")
        return
    if "modelopt_fp4" not in QUANTIZATION_METHODS:
        fail(errors,"vLLM QUANTIZATION_METHODS does not contain modelopt_fp4")
    if ModelOptNvFp4Config.get_min_capability() > 121:
        fail(errors,f"ModelOptNvFp4Config min capability {ModelOptNvFp4Config.get_min_capability()} exceeds Spark SM121")
    warnings.append("GLM MLA recipe intentionally keeps fp8_e4m3 KV; do not use nvfp4 KV for this profile")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--vllm-source-root")
    ap.add_argument("--check-files-complete", action="store_true")
    ap.add_argument("--expect-shards", type=int, default=87)
    args = ap.parse_args()
    errors = []
    warnings = []
    model_dir = Path(args.model_dir)
    check_model_config(model_dir, DEFAULT_PARTITION, errors, warnings)
    if args.check_files_complete:
        check_files(model_dir, args.expect_shards, errors)
    if args.vllm_source_root:
        check_vllm_source(Path(args.vllm_source_root), errors, warnings)
    result = {"ok": len(errors) == 0, "errors": errors, "warnings": warnings, "model_dir": str(model_dir)}
    print(json.dumps(result, indent=2, sort_keys=True))
    return(0 if len(errors) == 0 else 1)


if __name__ == "__main__":
    raise SystemExit(main())
