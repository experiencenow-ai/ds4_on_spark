#!/usr/bin/env bash
set -euo pipefail

usage()
{
  cat <<'EOF' 1>&2
Usage:
  scripts/model_contract_fetch_comparator_metadata.sh --repo-id <org/name> [--rev <rev>] --out-dir <path>

Fetches metadata-only comparator fixtures (no weights) from Hugging Face:
  - config.json (required)
  - generation_config.json (optional)
  - tokenizer_config.json (optional)
  - special_tokens_map.json (optional)
  - chat_template.jinja (optional)

Also writes:
  - upstream_commit.txt (from HF X-Repo-Commit header when available)
  - metadata_summary.json (normalized snapshot used by docs)

Notes:
  - Refuses to download checkpoint shards / weights.
  - Intended for lightweight baseline comparators (Ling/Qwen/etc), not for the
    DeepSeek V4 Flash full contract (use scripts/model_contract_fetch_deepseek_v4_flash.sh).
EOF
}

REPO_ID=""
REV="main"
OUT_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-id)
      REPO_ID="${2:-}"
      shift 2
      ;;
    --rev)
      REV="${2:-}"
      shift 2
      ;;
    --out-dir)
      OUT_DIR="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" 1>&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "$REPO_ID" ]] || [[ -z "$OUT_DIR" ]]; then
  usage
  exit 2
fi

hf_url()
{
  local path="$1"
  printf "https://huggingface.co/%s/resolve/%s/%s" "$REPO_ID" "$REV" "$path"
}

fetch_required()
{
  local path="$1"
  local url
  url="$(hf_url "$path")"

  mkdir -p "$OUT_DIR/$(dirname "$path")"
  curl -LfsS "$url" -o "$OUT_DIR/$path"
}

fetch_optional()
{
  local path="$1"
  local url
  local code
  url="$(hf_url "$path")"

  code="$(curl -sSIL -o /dev/null -w '%{http_code}' "$url" || true)"
  if [[ "$code" == "200" ]]; then
    mkdir -p "$OUT_DIR/$(dirname "$path")"
    curl -LfsS "$url" -o "$OUT_DIR/$path"
    return 0
  fi

  echo "skip: $path (HTTP $code)" 1>&2
  return 0
}

refuse_if_weightish()
{
  local path="$1"
  case "$path" in
    *.safetensors|*.bin|*.pt|*.pth|*.ckpt|*.gguf)
      echo "Refusing to download weight-like file: $path" 1>&2
      return 2
      ;;
  esac
  return 0
}

mkdir -p "$OUT_DIR"

for p in config.json generation_config.json tokenizer_config.json special_tokens_map.json chat_template.jinja; do
  refuse_if_weightish "$p"
done

# Record the upstream commit hash as seen by Hugging Face for this revision.
UPSTREAM_COMMIT="$(curl -sSI "$(hf_url "config.json")" | awk -F': ' 'tolower($1)=="x-repo-commit"{print $2}' | tr -d '\r' | tail -n 1)"
if [[ -n "$UPSTREAM_COMMIT" ]]; then
  printf "%s\n" "$UPSTREAM_COMMIT" > "$OUT_DIR/upstream_commit.txt"
fi

fetch_required "config.json"
fetch_optional "generation_config.json"
fetch_optional "tokenizer_config.json"
fetch_optional "special_tokens_map.json"
fetch_optional "chat_template.jinja"

export OUT_DIR REPO_ID REV
python3 - <<'PY'
import json
import os
from pathlib import Path

out_dir = Path(os.environ["OUT_DIR"])
repo_id = os.environ["REPO_ID"]
rev = os.environ["REV"]

def load_json(path: Path):
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

config = load_json(out_dir / "config.json") or {}
tok_cfg = load_json(out_dir / "tokenizer_config.json") or {}
spec_map = load_json(out_dir / "special_tokens_map.json") or {}
gen_cfg = load_json(out_dir / "generation_config.json") or {}

def pick_model_config(cfg: dict):
    if not isinstance(cfg, dict):
        return {}
    # Common pattern for multimodal checkpoints (e.g. Qwen3.5-27B): topology lives
    # under text_config, while the top-level config holds vision/audio knobs.
    for k in ("text_config", "language_config", "llm_config"):
        v = cfg.get(k)
        if isinstance(v, dict):
            return v
    return cfg

model_cfg = pick_model_config(config)

x_repo_commit = None
up = out_dir / "upstream_commit.txt"
if up.exists():
    x_repo_commit = up.read_text(encoding="utf-8").strip() or None

def first_non_null(*vals):
    for v in vals:
        if v is not None:
            return v
    return None

summary = {
    "repo_id": repo_id,
    "rev": rev,
    "x_repo_commit": x_repo_commit,
    "model": {
        "model_type": first_non_null(model_cfg.get("model_type"), config.get("model_type")),
        "architectures": first_non_null(config.get("architectures"), model_cfg.get("architectures")),
        "hidden_size": model_cfg.get("hidden_size"),
        "num_hidden_layers": model_cfg.get("num_hidden_layers"),
        "num_attention_heads": model_cfg.get("num_attention_heads"),
        "num_key_value_heads": model_cfg.get("num_key_value_heads"),
        "head_dim": first_non_null(model_cfg.get("head_dim"), model_cfg.get("v_head_dim"), config.get("head_dim"), config.get("v_head_dim")),
        "vocab_size": model_cfg.get("vocab_size"),
        "max_position_embeddings": model_cfg.get("max_position_embeddings"),
        "num_nextn_predict_layers": model_cfg.get("num_nextn_predict_layers"),
    },
    "moe": {
        "num_experts": first_non_null(model_cfg.get("num_experts"), model_cfg.get("n_routed_experts"), config.get("num_experts"), config.get("n_routed_experts")),
        "num_shared_experts": first_non_null(model_cfg.get("num_shared_experts"), model_cfg.get("n_shared_experts"), config.get("num_shared_experts"), config.get("n_shared_experts")),
        "num_experts_per_tok": first_non_null(model_cfg.get("num_experts_per_tok"), config.get("num_experts_per_tok")),
        "routed_scaling_factor": first_non_null(model_cfg.get("routed_scaling_factor"), config.get("routed_scaling_factor")),
        "scoring_func": first_non_null(model_cfg.get("scoring_func"), model_cfg.get("score_function"), config.get("scoring_func"), config.get("score_function")),
    },
    "tokenizer": {
        "bos_token_id": first_non_null(model_cfg.get("bos_token_id"), config.get("bos_token_id")),
        "eos_token_id": first_non_null(model_cfg.get("eos_token_id"), config.get("eos_token_id")),
        "pad_token_id": first_non_null(model_cfg.get("pad_token_id"), config.get("pad_token_id")),
        "tokenizer_class": tok_cfg.get("tokenizer_class"),
        "model_max_length": tok_cfg.get("model_max_length"),
        "chat_template_present": (out_dir / "chat_template.jinja").exists() or tok_cfg.get("chat_template") is not None,
        "special_tokens_map_keys": sorted(list(spec_map.keys())) if isinstance(spec_map, dict) else None,
    },
    "generation_defaults": {
        "do_sample": gen_cfg.get("do_sample"),
        "temperature": gen_cfg.get("temperature"),
        "top_p": gen_cfg.get("top_p"),
        "top_k": gen_cfg.get("top_k"),
        "max_new_tokens": gen_cfg.get("max_new_tokens"),
    },
}

(out_dir / "metadata_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

echo "OK: fetched metadata into $OUT_DIR"
