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

python3 - <<'PY' "$VLLM_MODEL" "$PROMPT" "$MAX_TOKENS" "$TENSOR_PARALLEL_SIZE" >"$OUT_DIR/vllm_generate_probe.txt" 2>&1 || true
import resource, sys, time

model, prompt, max_tokens_s, tp_s = sys.argv[1:]
max_tokens = int(max_tokens_s)
tp = int(tp_s)

start = time.monotonic()
try:
    from vllm import LLM, SamplingParams
except Exception as e:
    print("vllm import failed:", e)
    raise SystemExit(3)

sampling = SamplingParams(max_tokens=max_tokens, temperature=0.0)

llm = LLM(model=model, tensor_parallel_size=tp)
loaded = time.monotonic()

outs = llm.generate([prompt], sampling)
end = time.monotonic()

gen_tokens = 0
try:
    o0 = outs[0].outputs[0]
    if hasattr(o0, "token_ids") and o0.token_ids is not None:
        gen_tokens = len(o0.token_ids)
except Exception:
    pass

print("utc_start=" + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
print("load_s=%.6f" % (loaded - start))
print("generate_wall_s=%.6f" % (end - loaded))
print("generated_tokens=%d" % gen_tokens)
if gen_tokens > 0:
    print("generation_tps=%.6f" % (gen_tokens / max(1e-9, (end - loaded))))

ru = resource.getrusage(resource.RUSAGE_SELF)
max_rss_native = int(ru.ru_maxrss)
max_rss_bytes = max_rss_native
if sys.platform.startswith("linux"):
    max_rss_bytes = max_rss_native * 1024
print("max_rss_native=%d" % max_rss_native)
print("max_rss_bytes=%d" % max_rss_bytes)
PY

cat "$OUT_DIR/vllm_generate_probe.txt" || true
