#!/usr/bin/env sh
set -eu

target_note="antirez/ds4 baseline (Mac/Metal)"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
DS4_DIR="${DS4_DIR:-$repo_root/upstreams/ds4}"

MODEL_GGUF="${MODEL_GGUF:-}"
PROMPT="${PROMPT:-Explain Redis streams in one paragraph.}"
CTX="${CTX:-32768}"
N_TOKENS="${N_TOKENS:-256}"
EXTRA_ARGS="${EXTRA_ARGS:---nothink}"

OUT_DIR="${OUT_DIR:-/private/tmp/baseline_ds4_macos}"
ALLOW_FETCH="${ALLOW_FETCH:-0}"
ALLOW_BUILD="${ALLOW_BUILD:-0}"
ALLOW_RUN="${ALLOW_RUN:-0}"

mkdir -p "$OUT_DIR"

echo "== $target_note =="
date -u +"utc=%Y-%m-%dT%H:%M:%SZ"
echo "cwd=$PWD"
echo "out_dir=$OUT_DIR"
echo "ds4_dir=$DS4_DIR"
echo

if [ ! -d "$DS4_DIR" ]; then
    echo "missing DS4_DIR=$DS4_DIR"
    if [ "$ALLOW_FETCH" = "1" ]; then
        (cd "$repo_root" && ./scripts/fetch_upstreams.sh ds4)
    else
        echo "set ALLOW_FETCH=1 to clone antirez/ds4 into $repo_root/upstreams/ds4"
        exit 2
    fi
fi

echo "== ds4 revision =="
if [ -d "$DS4_DIR/.git" ]; then
    (cd "$DS4_DIR" && git rev-parse HEAD) || true
fi
echo

if [ "$ALLOW_BUILD" = "1" ]; then
    echo "== build (make) =="
    (cd "$DS4_DIR" && make)
    echo
else
    echo "== build skipped =="
    echo "set ALLOW_BUILD=1 to compile ds4 locally"
    echo
fi

DS4_BIN="$DS4_DIR/ds4"
if [ "$ALLOW_RUN" != "1" ]; then
    echo "== run skipped =="
    echo "set ALLOW_RUN=1 and MODEL_GGUF=/abs/path/to/ds4flash.gguf (or let it default) to run"
    exit 0
fi

if [ ! -x "$DS4_BIN" ]; then
    echo "ds4 binary not found: $DS4_BIN"
    echo "set ALLOW_BUILD=1 to build first"
    exit 3
fi

if [ "$MODEL_GGUF" = "" ]; then
    if [ -r "$DS4_DIR/ds4flash.gguf" ]; then
        MODEL_GGUF="$DS4_DIR/ds4flash.gguf"
    fi
fi

if [ "$MODEL_GGUF" = "" ]; then
    echo "MODEL_GGUF is required (or place ds4flash.gguf under $DS4_DIR)"
    echo "NOTE: do not run upstream download scripts unless you explicitly intend to fetch large weights."
    exit 4
fi

if [ ! -r "$MODEL_GGUF" ]; then
    echo "MODEL_GGUF not readable: $MODEL_GGUF"
    exit 5
fi

echo "== model artifact =="
ls -lh "$MODEL_GGUF" || true
if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$MODEL_GGUF" || true
elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$MODEL_GGUF" || true
fi
echo

LOG_RAW="$OUT_DIR/ds4.log"
LOG_SUMMARY="$OUT_DIR/ds4.summary.txt"

echo "== run =="
echo "prompt_chars=$(printf %s \"$PROMPT\" | wc -c | tr -d ' ')"
if command -v sha256sum >/dev/null 2>&1; then
    echo "prompt_sha256=$(printf %s \"$PROMPT\" | sha256sum | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
    echo "prompt_sha256=$(printf %s \"$PROMPT\" | shasum -a 256 | awk '{print $1}')"
fi
echo "cmd=$DS4_BIN -m $MODEL_GGUF -p <prompt> -n $N_TOKENS -c $CTX $EXTRA_ARGS"
echo

python3 - <<'PY' "$DS4_BIN" "$MODEL_GGUF" "$PROMPT" "$N_TOKENS" "$CTX" "$EXTRA_ARGS" "$LOG_RAW" "$LOG_SUMMARY"
import hashlib, os, resource, re, subprocess, sys, time, shlex, platform

ds4_bin, model, prompt, n_tokens, ctx, extra_args, log_raw, log_summary = sys.argv[1:]

cmd = [ds4_bin, "-m", model, "-p", prompt, "-n", n_tokens, "-c", ctx]
if extra_args.strip():
    cmd.extend(shlex.split(extra_args))

start = time.monotonic()
first_output_s = None
prefill_tps = None
generation_tps = None
model_size_bytes = None
try:
    model_size_bytes = int(os.stat(model).st_size)
except Exception:
    model_size_bytes = None

prefill_re = re.compile(r"ds4:\\s+prefill:\\s+([0-9]+(?:\\.[0-9]+)?)\\s+t/s,\\s+generation:\\s+([0-9]+(?:\\.[0-9]+)?)\\s+t/s")

with open(log_raw, "w", encoding="utf-8") as f:
    f.write("cmd=" + " ".join(shlex.quote(x) for x in cmd) + "\n")
    f.write("utc_start=" + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\n")
    f.flush()

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in proc.stdout:
        if first_output_s is None and line != "":
            first_output_s = time.monotonic() - start
        m = prefill_re.search(line)
        if m:
            prefill_tps = float(m.group(1))
            generation_tps = float(m.group(2))
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

summary_lines = []
summary_lines.append("exit_code=%d" % rc)
summary_lines.append("ds4_bin=%s" % ds4_bin)
summary_lines.append("model_path=%s" % model)
if model_size_bytes is None:
    summary_lines.append("model_size_bytes=NA")
else:
    summary_lines.append("model_size_bytes=%d" % model_size_bytes)
summary_lines.append("prompt_chars=%d" % len(prompt.encode("utf-8")))
summary_lines.append("prompt_sha256=%s" % hashlib.sha256(prompt.encode("utf-8")).hexdigest())
summary_lines.append("ctx=%s" % ctx)
summary_lines.append("n_tokens=%s" % n_tokens)
summary_lines.append("extra_args=%s" % (extra_args.replace(" ", "_") if extra_args else "NA"))
if first_output_s is None:
    summary_lines.append("ttft_first_output_s=NA")
else:
    summary_lines.append("ttft_first_output_s=%.6f" % first_output_s)
summary_lines.append("wall_s=%.6f" % (end - start))
summary_lines.append("max_rss_native=%d" % max_rss_native)
summary_lines.append("max_rss_bytes=%d" % max_rss_bytes)
if prefill_tps is not None:
    summary_lines.append("prefill_tps=%.6f" % prefill_tps)
if generation_tps is not None:
    summary_lines.append("generation_tps=%.6f" % generation_tps)

with open(log_summary, "w", encoding="utf-8") as sf:
    sf.write("\n".join(summary_lines) + "\n")

print("\\n== baseline summary (approx) ==")
print("\\n".join(summary_lines))
sys.exit(rc)
PY
