#!/usr/bin/env sh
set -eu

OUT_DIR="${OUT_DIR:-/tmp/baseline_vllm}"
mkdir -p "$OUT_DIR"

ALLOW_RUN="${ALLOW_RUN:-0}"
VLLM_MODEL="${VLLM_MODEL:-}"
PROMPT="${PROMPT:-Explain Redis streams in one paragraph.}"
MAX_TOKENS="${MAX_TOKENS:-256}"
TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-1}"

echo "== vLLM probe (Spark) =="
date -u +"utc=%Y-%m-%dT%H:%M:%SZ"
echo

echo "== gpu snapshot (pre) =="
GPU_PRE="$OUT_DIR/nvidia_smi_pre.txt"
nvidia-smi >"$GPU_PRE" 2>&1 || true
cat "$GPU_PRE" || true
echo

echo "== python =="
command -v python3 || true
python3 -V || true
echo

echo "== vllm package =="
python3 -m pip show vllm >"$OUT_DIR/pip_show_vllm.txt" 2>&1 || true
cat "$OUT_DIR/pip_show_vllm.txt"
echo

echo "== torch package =="
python3 -m pip show torch >"$OUT_DIR/pip_show_torch.txt" 2>&1 || true
cat "$OUT_DIR/pip_show_torch.txt"
echo

echo "== cuda via torch =="
python3 - <<'PY' >"$OUT_DIR/torch_cuda_probe.txt" 2>&1 || true
try:
    import torch
    print("torch", torch.__version__)
    print("cuda available", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("device", torch.cuda.get_device_name(0))
        print("capability", torch.cuda.get_device_capability(0))
except Exception as e:
    print("torch probe failed:", e)
PY
cat "$OUT_DIR/torch_cuda_probe.txt"

echo
echo "== baseline notes =="
echo "- This script does not install vLLM or download weights."
echo "- TTFT is not measured (Python API returns after generation completes)."

if [ "$ALLOW_RUN" != "1" ]; then
    echo
    echo "== run skipped =="
    echo "set ALLOW_RUN=1 and VLLM_MODEL=/abs/path/to/hf_model_dir (already present on Spark) to run a small generation probe"
    exit 0
fi

if [ "$VLLM_MODEL" = "" ]; then
    echo "VLLM_MODEL is required when ALLOW_RUN=1" >&2
    exit 2
fi

echo
echo "== vLLM generate probe (approx; no streaming TTFT) =="
echo "model=$VLLM_MODEL"
echo "tp=$TENSOR_PARALLEL_SIZE"
echo "max_tokens=$MAX_TOKENS"
echo

LOG_RAW="$OUT_DIR/vllm_generate_probe.txt"
LOG_SUMMARY="$OUT_DIR/vllm_generate_probe.summary.txt"

python3 - <<'PY' "$VLLM_MODEL" "$PROMPT" "$MAX_TOKENS" "$TENSOR_PARALLEL_SIZE" "$LOG_RAW" "$LOG_SUMMARY"
import resource, sys, time

model, prompt, max_tokens_s, tp_s, log_raw, log_summary = sys.argv[1:]
max_tokens = int(max_tokens_s)
tp = int(tp_s)

start = time.monotonic()
utc_start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

rc = 0
load_s = None
generate_wall_s = None
generated_tokens = 0

raw_lines = []
raw_lines.append("utc_start=" + utc_start)
raw_lines.append("model=" + model)
raw_lines.append("tp=%d" % tp)
raw_lines.append("max_tokens=%d" % max_tokens)

try:
    from vllm import LLM, SamplingParams
    sampling = SamplingParams(max_tokens=max_tokens, temperature=0.0)

    llm = LLM(model=model, tensor_parallel_size=tp)
    loaded = time.monotonic()
    load_s = loaded - start

    outs = llm.generate([prompt], sampling)
    end = time.monotonic()
    generate_wall_s = end - loaded

    try:
        o0 = outs[0].outputs[0]
        if hasattr(o0, "token_ids") and o0.token_ids is not None:
            generated_tokens = len(o0.token_ids)
    except Exception:
        pass
except Exception as e:
    rc = 3
    raw_lines.append("error=" + repr(e))

ru = resource.getrusage(resource.RUSAGE_SELF)
max_rss_native = int(ru.ru_maxrss)
max_rss_bytes = max_rss_native
if sys.platform.startswith("linux"):
    max_rss_bytes = max_rss_native * 1024

def _fmt_float(v):
    if v is None:
        return "NA"
    return "%.6f" % float(v)

summary = []
summary.append("exit_code=%d" % rc)
summary.append("model_path=%s" % model)
summary.append("tensor_parallel_size=%d" % tp)
summary.append("max_tokens=%d" % max_tokens)
summary.append("ttft_first_output_s=NA")
summary.append("load_s=" + _fmt_float(load_s))
summary.append("generate_wall_s=" + _fmt_float(generate_wall_s))
summary.append("wall_s=%.6f" % (time.monotonic() - start))
summary.append("generated_tokens=%d" % int(generated_tokens))
if generate_wall_s is not None and generate_wall_s > 0 and generated_tokens > 0:
    summary.append("generation_tps=%.6f" % (generated_tokens / max(1e-9, generate_wall_s)))
summary.append("max_rss_native=%d" % max_rss_native)
summary.append("max_rss_bytes=%d" % max_rss_bytes)

with open(log_raw, "w", encoding="utf-8") as f:
    f.write("\n".join(raw_lines) + "\n")
    f.write("\n".join(summary) + "\n")

with open(log_summary, "w", encoding="utf-8") as sf:
    sf.write("\n".join(summary) + "\n")

print("\n".join(raw_lines))
print("\n== baseline summary (approx) ==")
print("\n".join(summary))
raise SystemExit(rc)
PY

echo
echo "== gpu snapshot (post) =="
GPU_POST="$OUT_DIR/nvidia_smi_post.txt"
nvidia-smi >"$GPU_POST" 2>&1 || true
cat "$GPU_POST" || true
