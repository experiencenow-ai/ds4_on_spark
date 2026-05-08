#!/usr/bin/env sh
set -eu

target_note="llama.cpp baseline (Spark/CUDA)"

LLAMA_DIR="${LLAMA_DIR:-$HOME/src/llama.cpp}"
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
echo

echo "== gpu snapshot (pre) =="
GPU_PRE="$OUT_DIR/nvidia_smi_pre.txt"
nvidia-smi >"$GPU_PRE" 2>&1 || true
cat "$GPU_PRE" || true
echo

if [ ! -d "$LLAMA_DIR" ]; then
    echo "missing LLAMA_DIR=$LLAMA_DIR"
    if [ "$ALLOW_FETCH" = "1" ]; then
        mkdir -p "$(dirname "$LLAMA_DIR")"
        git clone https://github.com/ggml-org/llama.cpp.git "$LLAMA_DIR"
    else
        echo "set ALLOW_FETCH=1 to clone llama.cpp on Spark"
        exit 2
    fi
fi

echo "== llama.cpp revision =="
if [ -d "$LLAMA_DIR/.git" ]; then
    (cd "$LLAMA_DIR" && git rev-parse HEAD) || true
fi
echo

if [ "$ALLOW_BUILD" = "1" ]; then
    echo "== build (cuda) =="
    (cd "$LLAMA_DIR" && cmake -B build -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release)
    (cd "$LLAMA_DIR" && cmake --build build --config Release)
    echo
else
    echo "== build skipped =="
    echo "set ALLOW_BUILD=1 to compile llama.cpp on Spark"
    echo
fi

LLAMA_CLI=""
if [ -x "$LLAMA_DIR/build/bin/llama-cli" ]; then
    LLAMA_CLI="$LLAMA_DIR/build/bin/llama-cli"
elif [ -x "$LLAMA_DIR/build/bin/main" ]; then
    LLAMA_CLI="$LLAMA_DIR/build/bin/main"
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
ls -lh "$MODEL_GGUF" || true
command -v sha256sum >/dev/null 2>&1 && sha256sum "$MODEL_GGUF" || true
echo

LOG_RAW="$OUT_DIR/llama_cli.log"
LOG_SUMMARY="$OUT_DIR/llama_cli.summary.txt"

echo "== run =="
echo "cmd=$LLAMA_CLI -m $MODEL_GGUF -p <prompt> -n $N_TOKENS -c $CTX -ngl $N_GPU_LAYERS --timings $EXTRA_ARGS"
echo

python3 - <<'PY' "$LLAMA_CLI" "$MODEL_GGUF" "$PROMPT" "$N_TOKENS" "$CTX" "$N_GPU_LAYERS" "$EXTRA_ARGS" "$LOG_RAW" "$LOG_SUMMARY"
import os, resource, re, subprocess, sys, time, shlex

llama_cli, model, prompt, n_tokens, ctx, ngl, extra_args, log_raw, log_summary = sys.argv[1:]

cmd = [llama_cli, "-m", model, "-p", prompt, "-n", n_tokens, "-c", ctx, "-ngl", ngl, "--timings"]
if extra_args.strip():
    cmd.extend(shlex.split(extra_args))

start = time.monotonic()

timings_lines = []
with open(log_raw, "w", encoding="utf-8") as f:
    f.write("cmd=" + " ".join(shlex.quote(x) for x in cmd) + "\n")
    f.write("utc_start=" + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\n")
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
if first_output_s is None:
    summary_lines.append("ttft_first_output_s=NA")
else:
    summary_lines.append("ttft_first_output_s=%.6f" % first_output_s)
summary_lines.append("wall_s=%.6f" % (end - start))
summary_lines.append("max_rss_kb=%d" % int(ru.ru_maxrss))
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
