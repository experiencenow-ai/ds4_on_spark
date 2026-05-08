#!/usr/bin/env python3

import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures" / "model_contract" / "deepseek_v4_flash"


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    cfg = load_json(FIX / "config.json")
    inf = load_json(FIX / "inference" / "config.json")
    tok_cfg = load_json(FIX / "tokenizer_config.json")
    idx = load_json(FIX / "model.safetensors.index.json")

    compress_ratios = cfg["compress_ratios"]
    n_layers = int(cfg["num_hidden_layers"])
    main_ratios = compress_ratios[:n_layers]
    mtp_ratios = compress_ratios[n_layers:]

    c = Counter(main_ratios)

    weight_map = idx.get("weight_map", {})
    keys = list(weight_map.keys())
    top = Counter(k.split(".", 1)[0] for k in keys)

    tid2eid = [k for k in keys if k.endswith("ffn.gate.tid2eid")]
    gate_bias = [k for k in keys if k.endswith("ffn.gate.bias")]

    print("DeepSeek V4 Flash contract summary")
    print(f"- upstream_commit: {(FIX / 'upstream_commit.txt').read_text(encoding='utf-8').strip() if (FIX / 'upstream_commit.txt').exists() else '(missing)'}")
    print(f"- vocab_size: {cfg['vocab_size']}")
    print(f"- hidden_size: {cfg['hidden_size']}")
    print(f"- num_hidden_layers: {cfg['num_hidden_layers']}")
    print(f"- num_attention_heads: {cfg['num_attention_heads']}")
    print(f"- head_dim: {cfg['head_dim']}")
    if 'qk_rope_head_dim' in cfg:
        print(f"- qk_rope_head_dim: {cfg['qk_rope_head_dim']}")
    print(f"- num_key_value_heads: {cfg['num_key_value_heads']}")
    print(f"- sliding_window: {cfg['sliding_window']}")
    print(f"- n_routed_experts: {cfg['n_routed_experts']}")
    print(f"- n_shared_experts: {cfg['n_shared_experts']}")
    print(f"- num_experts_per_tok: {cfg['num_experts_per_tok']}")
    print(f"- moe_intermediate_size: {cfg['moe_intermediate_size']}")
    print(f"- scoring_func: {cfg['scoring_func']}")
    print(f"- routed_scaling_factor: {cfg['routed_scaling_factor']}")
    print(f"- num_hash_layers: {cfg['num_hash_layers']}")
    print(f"- num_nextn_predict_layers: {cfg['num_nextn_predict_layers']}")
    print("")
    print("Reference runtime config (inference/config.json)")
    print(f"- dim: {inf.get('dim')}")
    print(f"- moe_inter_dim: {inf.get('moe_inter_dim')}")
    print(f"- rope_head_dim: {inf.get('rope_head_dim')}")
    print(f"- original_seq_len: {inf.get('original_seq_len')}")
    print(f"- rope_theta: {inf.get('rope_theta')}")
    print(f"- compress_rope_theta: {inf.get('compress_rope_theta')}")
    print(f"- rope_factor: {inf.get('rope_factor')}")
    print("")
    print("Attention schedule (from compress_ratios)")
    print(f"- compress_ratios_len: {len(compress_ratios)} (main={n_layers} mtp={len(mtp_ratios)})")
    print(f"- main_ratio_counts: {dict(c)}")
    print(f"- mtp_ratios: {mtp_ratios}")
    print("")
    print("Tokenizer")
    print(f"- tokenizer_class: {tok_cfg.get('tokenizer_class')}")
    print(f"- model_max_length: {tok_cfg.get('model_max_length')}")
    print(f"- bos_token: {tok_cfg.get('bos_token', {}).get('content')}")
    print(f"- eos_token: {tok_cfg.get('eos_token', {}).get('content')}")
    print("")
    print("Checkpoint tensor keys (from model.safetensors.index.json)")
    print(f"- tensor_key_count: {len(keys)}")
    print(f"- top_level_prefix_counts: {dict(top)}")
    print(f"- gate.tid2eid_count: {len(tid2eid)} ({sorted(tid2eid)})")
    layer_gate_bias = [k for k in gate_bias if k.startswith("layers.")]
    mtp_gate_bias = [k for k in gate_bias if k.startswith("mtp.")]
    if layer_gate_bias:
        layer_ids = sorted(int(k.split(".", 2)[1]) for k in layer_gate_bias)
        span = f"layers.{layer_ids[0]}..layers.{layer_ids[-1]}"
    else:
        span = "n/a"
    print(f"- gate.bias_count: {len(gate_bias)} (layers={len(layer_gate_bias)} mtp={len(mtp_gate_bias)} span {span})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
