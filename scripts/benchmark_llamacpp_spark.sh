#!/usr/bin/env sh
set -eu

target_note="llama.cpp baseline (Spark/CUDA)"

LLAMA_DIR="${LLAMA_DIR:-$HOME/src/llama.cpp}"
LLAMA_CLI="${LLAMA_CLI:-}"
RUNTIME_LABEL="${RUNTIME_LABEL:-llama.cpp-compatible}"
MODEL_SOURCE="${MODEL_SOURCE:-unknown}"
MODEL_QUANT="${MODEL_QUANT:-unknown}"
MODEL_GGUF="${MODEL_GGUF:-}"
PROMPT="${PROMPT:-Explain Redis streams in one paragraph.}"
CTX="${CTX:-8192}"
N_TOKENS="${N_TOKENS:-256}"
N_GPU_LAYERS="${N_GPU_LAYERS:-99}"
EXTRA_ARGS="${EXTRA_ARGS:-}"

OUT_DIR="${OUT_DIR:-/tmp/baseline_llamacpp}"
ALLOW_FETCH="${ALLOW_FETCH:-0}"
ALLOW_BUILD="${ALLOW_BUILD:-0}"
ALLOW_RUN="${ALLOW_RUN:-0}"

mkdir -p "$OUT_DIR"

echo "== $target_note =="
date -u +"utc=%Y-%m-%dT%H:%M:%SZ"
echo "cwd=$PWD"
echo "out_dir=$OUT_DIR"
echo "runtime_label=$RUNTIME_LABEL"
echo "model_source=$MODEL_SOURCE"
echo "model_quant=$MODEL_QUANT"
echo

echo "== gpu snapshot (pre) =="
GPU_PRE="$OUT_DIR/nvidia_smi_pre.txt"
nvidia-smi >"$GPU_PRE" 2>&1 || true
cat "$GPU_PRE" || true
echo

if [ "$LLAMA_CLI" = "" ] && [ ! -d "$LLAMA_DIR" ]; then
    echo "missing LLAMA_DIR=$LLAMA_DIR"
    if [ "$ALLOW_FETCH" = "1" ]; then
        mkdir -p "$(dirname "$LLAMA_DIR")"
        git clone https://github.com/ggml-org/llama.cpp.git "$LLAMA_DIR"
    else
        echo "set ALLOW_FETCH=1 to clone llama.cpp on Spark (or set LLAMA_CLI=/abs/path/to/llama-cli)"
        exit 2
    fi
fi

echo "== llama.cpp revision =="
if [ -d "$LLAMA_DIR/.git" ]; then
    (cd "$LLAMA_DIR" && git rev-parse HEAD) || true
fi
if [ "$LLAMA_CLI" != "" ]; then
    echo "llama_cli_override=$LLAMA_CLI"
fi
echo

if [ "$ALLOW_BUILD" = "1" ]; then
    if [ "$LLAMA_CLI" != "" ]; then
        echo "LLAMA_CLI is set; skipping build under LLAMA_DIR"
        echo
    else
    echo "== build (cuda) =="
    (cd "$LLAMA_DIR" && cmake -B build -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release)
    (cd "$LLAMA_DIR" && cmake --build build --config Release)
    echo
    fi
else
    echo "== build skipped =="
    echo "set ALLOW_BUILD=1 to compile llama.cpp on Spark"
    echo
fi

if [ "$LLAMA_CLI" = "" ]; then
    if [ -x "$LLAMA_DIR/build/bin/llama-cli" ]; then
        LLAMA_CLI="$LLAMA_DIR/build/bin/llama-cli"
    elif [ -x "$LLAMA_DIR/build/bin/main" ]; then
        LLAMA_CLI="$LLAMA_DIR/build/bin/main"
    fi
fi

if [ "$ALLOW_RUN" != "1" ]; then
    echo "== run skipped =="
    echo "set ALLOW_RUN=1 and MODEL_GGUF=/abs/path/to/model.gguf to run"
    exit 0
fi

if [ "$LLAMA_CLI" = "" ]; then
    echo "llama-cli not found under $LLAMA_DIR/build/bin"
    echo "set ALLOW_BUILD=1 to build first, or set LLAMA_DIR to an existing build"
    exit 3
fi

if [ "$MODEL_GGUF" = "" ]; then
    echo "MODEL_GGUF is required"
    exit 4
fi

if [ ! -r "$MODEL_GGUF" ]; then
    echo "MODEL_GGUF not readable: $MODEL_GGUF"
    exit 5
fi

echo "== model artifact =="
echo "model_source=$MODEL_SOURCE"
echo "model_quant=$MODEL_QUANT"
ls -lh "$MODEL_GGUF" || true
wc -c "$MODEL_GGUF" || true
if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$MODEL_GGUF" || true
elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$MODEL_GGUF" || true
fi
echo

LOG_RAW="$OUT_DIR/llama_cli.log"
LOG_SUMMARY="$OUT_DIR/llama_cli.summary.txt"

echo "== run =="
echo "prompt_chars=$(printf %s \"$PROMPT\" | wc -c | tr -d ' ')"
if command -v sha256sum >/dev/null 2>&1; then
    echo "prompt_sha256=$(printf %s \"$PROMPT\" | sha256sum | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
    echo "prompt_sha256=$(printf %s \"$PROMPT\" | shasum -a 256 | awk '{print $1}')"
fi
echo "cmd=$LLAMA_CLI -m $MODEL_GGUF -p <prompt> -n $N_TOKENS -c $CTX -ngl $N_GPU_LAYERS --timings $EXTRA_ARGS"
echo

LLAMA_CLI_SHA256=""
LLAMA_CLI_VERSION=""
if command -v sha256sum >/dev/null 2>&1; then
    LLAMA_CLI_SHA256="$(sha256sum "$LLAMA_CLI" 2>/dev/null | awk '{print $1}' || true)"
elif command -v shasum >/dev/null 2>&1; then
    LLAMA_CLI_SHA256="$(shasum -a 256 "$LLAMA_CLI" 2>/dev/null | awk '{print $1}' || true)"
fi
LLAMA_CLI_VERSION="$("$LLAMA_CLI" --version 2>/dev/null | head -n 1 | tr -s ' ' | sed 's/[[:space:]]*$//' || true)"

python3 - <<'PY' "$LLAMA_CLI" "$MODEL_GGUF" "$PROMPT" "$N_TOKENS" "$CTX" "$N_GPU_LAYERS" "$EXTRA_ARGS" "$LOG_RAW" "$LOG_SUMMARY" "$RUNTIME_LABEL" "$MODEL_SOURCE" "$MODEL_QUANT" "$LLAMA_CLI_SHA256" "$LLAMA_CLI_VERSION"
import hashlib, os, resource, re, subprocess, sys, time, shlex

llama_cli, model, prompt, n_tokens, ctx, ngl, extra_args, log_raw, log_summary, runtime_label, model_source, model_quant, llama_cli_sha256, llama_cli_version = sys.argv[1:]

cmd = [llama_cli, "-m", model, "-p", prompt, "-n", n_tokens, "-c", ctx, "-ngl", ngl, "--timings"]
if extra_args.strip():
    cmd.extend(shlex.split(extra_args))

start = time.monotonic()
model_size_bytes = None
try:
    model_size_bytes = int(os.stat(model).st_size)
except Exception:
    model_size_bytes = None

timings_lines = []
with open(log_raw, "w", encoding="utf-8") as f:
    f.write("cmd=" + " ".join(shlex.quote(x) for x in cmd) + "\n")
    f.write("utc_start=" + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\n")
    f.write("runtime_label=" + runtime_label + "\n")
    f.write("model_source=" + model_source + "\n")
    f.write("model_quant=" + model_quant + "\n")
    f.write("llama_cli_sha256=" + llama_cli_sha256 + "\n")
    f.write("llama_cli_version=" + llama_cli_version + "\n")
    f.flush()

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    first_output_s = None
    for line in proc.stdout:
        if first_output_s is None and line != "":
            first_output_s = time.monotonic() - start
        if "prompt eval time" in line or ("eval time" in line and "prompt eval time" not in line):
            timings_lines.append(line.strip())
        f.write(line)
        f.flush()
        sys.stdout.write(line)
        sys.stdout.flush()
    rc = proc.wait()

end = time.monotonic()

ru = resource.getrusage(resource.RUSAGE_CHILDREN)
max_rss_native = int(ru.ru_maxrss)
max_rss_bytes = max_rss_native
if sys.platform.startswith("linux"):
    max_rss_bytes = max_rss_native * 1024

def _last_float_before(haystack: str, needle: str):
    if needle not in haystack:
        return None
    prefix = haystack.split(needle, 1)[0]
    floats = re.findall(r"([0-9]+(?:\\.[0-9]+)?)", prefix)
    if not floats:
        return None
    return float(floats[-1])

prefill_tps = None
prefill_ms_per_tok = None
gen_tps = None
gen_ms_per_tok = None
for tl in timings_lines:
    if "prompt eval time" in tl:
        prefill_tps = _last_float_before(tl, "tokens per second")
        prefill_ms_per_tok = _last_float_before(tl, "ms per token")
    elif tl.startswith("eval time") or " eval time" in tl:
        gen_tps = _last_float_before(tl, "tokens per second")
        gen_ms_per_tok = _last_float_before(tl, "ms per token")

summary_lines = []
summary_lines.append("exit_code=%d" % rc)
summary_lines.append("runtime_label=%s" % runtime_label)
summary_lines.append("model_source=%s" % model_source)
summary_lines.append("model_quant=%s" % model_quant)
summary_lines.append("prompt_chars=%d" % len(prompt.encode("utf-8")))
summary_lines.append("prompt_sha256=%s" % hashlib.sha256(prompt.encode("utf-8")).hexdigest())
summary_lines.append("llama_cli=%s" % llama_cli)
summary_lines.append("llama_cli_sha256=%s" % (llama_cli_sha256 or "NA"))
summary_lines.append("llama_cli_version=%s" % (llama_cli_version.replace(" ", "_") if llama_cli_version else "NA"))
summary_lines.append("model_path=%s" % model)
if model_size_bytes is None:
    summary_lines.append("model_size_bytes=NA")
else:
    summary_lines.append("model_size_bytes=%d" % model_size_bytes)
summary_lines.append("ctx=%s" % ctx)
summary_lines.append("n_tokens=%s" % n_tokens)
summary_lines.append("n_gpu_layers=%s" % ngl)
if first_output_s is None:
    summary_lines.append("ttft_first_output_s=NA")
else:
    summary_lines.append("ttft_first_output_s=%.6f" % first_output_s)
summary_lines.append("wall_s=%.6f" % (end - start))
summary_lines.append("max_rss_native=%d" % max_rss_native)
summary_lines.append("max_rss_bytes=%d" % max_rss_bytes)
if prefill_tps is not None:
    summary_lines.append("prefill_tps=%.6f" % prefill_tps)
if prefill_ms_per_tok is not None:
    summary_lines.append("prefill_ms_per_token=%.6f" % prefill_ms_per_tok)
if gen_tps is not None:
    summary_lines.append("generation_tps=%.6f" % gen_tps)
if gen_ms_per_tok is not None:
    summary_lines.append("generation_ms_per_token=%.6f" % gen_ms_per_tok)

with open(log_summary, "w", encoding="utf-8") as sf:
    sf.write("\n".join(summary_lines) + "\n")

print("\n== baseline summary (approx) ==")
print("\n".join(summary_lines))
sys.exit(rc)
PY

echo
echo "== gpu snapshot (post) =="
GPU_POST="$OUT_DIR/nvidia_smi_post.txt"
nvidia-smi >"$GPU_POST" 2>&1 || true
cat "$GPU_POST" || true
