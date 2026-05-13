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
        echo "set ALLOW_FETCH=1 to clone llama.cpp on Spark"
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
    if [ ! -d "$LLAMA_DIR" ]; then
        echo "LLAMA_DIR is required for ALLOW_BUILD=1: $LLAMA_DIR"
        exit 6
    fi
    echo "== build (cuda) =="
    (cd "$LLAMA_DIR" && cmake -B build -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release)
    (cd "$LLAMA_DIR" && cmake --build build --config Release)
    echo
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
MODEL_SHA256=""
MODEL_SHA256_LINE=""
if command -v sha256sum >/dev/null 2>&1; then
    MODEL_SHA256_LINE="$(sha256sum "$MODEL_GGUF" 2>/dev/null || true)"
    if [ "$MODEL_SHA256_LINE" != "" ]; then
        echo "$MODEL_SHA256_LINE"
        MODEL_SHA256="$(printf %s "$MODEL_SHA256_LINE" | awk '{print $1}' || true)"
    fi
fi
echo

LOG_RAW="$OUT_DIR/llama_cli.log"
LOG_SUMMARY="$OUT_DIR/llama_cli.summary.txt"

echo "== run =="
echo "runtime_label=$RUNTIME_LABEL"
echo "cmd=$LLAMA_CLI -m $MODEL_GGUF -p <prompt> -n $N_TOKENS -c $CTX -ngl $N_GPU_LAYERS <timings-flags> $EXTRA_ARGS"
echo

python3 - <<'PY' "$LLAMA_CLI" "$MODEL_GGUF" "$PROMPT" "$N_TOKENS" "$CTX" "$N_GPU_LAYERS" "$EXTRA_ARGS" "$LOG_RAW" "$LOG_SUMMARY" "$RUNTIME_LABEL" "$MODEL_SOURCE" "$MODEL_QUANT" "$MODEL_SHA256" "$LLAMA_DIR"
import json, os, resource, re, subprocess, sys, time, shlex

llama_cli, model, prompt, n_tokens, ctx, ngl, extra_args, log_raw, log_summary, runtime_label, model_source, model_quant, model_sha256, llama_dir = sys.argv[1:]

help_text = ""
try:
    hr = subprocess.run([llama_cli, "--help"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=10)
    help_text = (hr.stdout or "")
except Exception:
    help_text = ""

perf_flags = []
if "--timings" in help_text:
    perf_flags.append("--timings")
elif "--show-timings" in help_text:
    perf_flags.append("--show-timings")
if "--perf" in help_text:
    perf_flags.append("--perf")

fixed_flags = []
for flag in ["--single-turn", "--simple-io", "--no-display-prompt", "--no-warmup"]:
    if flag in help_text:
        fixed_flags.append(flag)

cmd = [llama_cli, "-m", model, "-p", prompt, "-n", n_tokens, "-c", ctx, "-ngl", ngl] + perf_flags + fixed_flags
if extra_args.strip():
    cmd.extend(shlex.split(extra_args))

start = time.monotonic()

timings_lines = []
fattn_ids = set()
fattn_lines = 0
llama_commit = ""
try:
    if llama_dir and os.path.isdir(llama_dir):
        gr = subprocess.run(["git", "-C", llama_dir, "rev-parse", "HEAD"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5)
        sha = (gr.stdout or "").strip()
        if re.fullmatch(r"[0-9a-f]{40}", sha):
            llama_commit = sha
except Exception:
    llama_commit = ""
with open(log_raw, "w", encoding="utf-8") as f:
    f.write("cmd=" + " ".join(shlex.quote(x) for x in cmd) + "\n")
    f.write("utc_start=" + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\n")
    f.write("runtime_label=" + runtime_label + "\n")
    f.write("model_source=" + model_source + "\n")
    f.write("model_quant=" + model_quant + "\n")
    f.flush()

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    first_output_s = None
    for line in proc.stdout:
        if first_output_s is None and line != "":
            first_output_s = time.monotonic() - start
        if "__fattn__" in line:
            fattn_lines += 1
            m = re.search(r"__fattn__-([0-9]+)", line)
            if m is not None:
                fattn_ids.add(int(m.group(1)))
        if ("load time" in line) or ("sample time" in line) or ("total time" in line) or ("prompt eval time" in line) or ("eval time" in line and "prompt eval time" not in line) or ("[ Prompt:" in line and "Generation:" in line and "t/s" in line):
            timings_lines.append(line.strip())
        f.write(line)
        f.flush()
        sys.stdout.write(line)
        sys.stdout.flush()
    rc = proc.wait()

end = time.monotonic()

ru = resource.getrusage(resource.RUSAGE_CHILDREN)

def scan_fattn_cli(log_path: str):
    out = {
        "log_path": log_path,
        "seen_fattn_disabled": False,
        "seen_sched_reserve_cpu_fattn": False,
        "seen_sched_reserve_fallback": False,
        "seen_sched_reserve_failure": False,
        "sched_reserve_fallback_line_count": 0,
        "sched_reserve_failure_line_count": 0,
        "fattn_line_count": 0,
        "fattn_node_unique": 0,
        "fattn_id_min": None,
        "fattn_id_max": None,
        "fattn_id_span": None,
        "fattn_id_missing_count": None,
        "fattn_expected_id_0_42_ok": None,
        "fattn_backend_counts": {},
        "fattn_backend_unique": 0,
        "fattn_backend0_only": False,
        "fattn_expected_backend0_ok": None,
        "fattn_cuda_device_counts": {},
        "fattn_cuda_device_unique": 0,
        "fattn_cuda_device0_only": False,
        "fattn_expected_cuda_device0_ok": None,
        "fattn_cpu_line_count": 0,
        "fattn_cuda_line_count": 0,
        "sched_reserve_line_count": 0,
        "sched_reserve_graph_nodes": None,
        "sched_reserve_graph_splits": None,
        "sched_reserve_took_ms": None,
        "node_kind_unique": 0,
        "node_kind_cpu_top": [],
        "node_kind_cuda_top": [],
        "match_lines": [],
        "fattn_nodes_sample": [],
        "node_kinds_sample": [],
    }
    if not log_path or not os.path.exists(log_path):
        return out
    nodes = set()
    fattn_ids = set()
    fattn_backend = {}
    fattn_cuda_dev = {}
    kind_nodes = set()
    kind_cpu = {}
    kind_cuda = {}
    match_lines = []
    rx_fattn_disabled = re.compile(r"flash attention.*disabl", flags=re.IGNORECASE)
    rx_sched_reserve_fallback = re.compile(r"\bfallback\b|\bfall back\b", flags=re.IGNORECASE)
    rx_sched_reserve_failure = re.compile(r"\bfail(?:ed|ure)?\b|\berror\b|\bunable\b|\bnot supported\b", flags=re.IGNORECASE)
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                ln = line.rstrip("\n")
                is_match = False
                if ln.startswith("sched_reserve:"):
                    out["sched_reserve_line_count"] += 1
                    if rx_sched_reserve_fallback.search(ln) is not None:
                        out["seen_sched_reserve_fallback"] = True
                        out["sched_reserve_fallback_line_count"] += 1
                        is_match = True
                    if rx_sched_reserve_failure.search(ln) is not None:
                        out["seen_sched_reserve_failure"] = True
                        out["sched_reserve_failure_line_count"] += 1
                        is_match = True
                    m = re.search(r"graph nodes\\s*=\\s*(\\d+)", ln)
                    if m is not None:
                        try:
                            out["sched_reserve_graph_nodes"] = int(m.group(1))
                        except ValueError:
                            pass
                    m = re.search(r"graph splits\\s*=\\s*(\\d+)", ln)
                    if m is not None:
                        try:
                            out["sched_reserve_graph_splits"] = int(m.group(1))
                        except ValueError:
                            pass
                    m = re.search(r"reserve took\\s*([0-9]+(?:\\.[0-9]+)?)\\s*ms", ln)
                    if m is not None:
                        try:
                            out["sched_reserve_took_ms"] = float(m.group(1))
                        except ValueError:
                            pass
                if rx_fattn_disabled.search(ln) is not None:
                    out["seen_fattn_disabled"] = True
                    is_match = True
                if "Flash Attention tensor is assigned to device CPU" in ln:
                    out["seen_sched_reserve_cpu_fattn"] = True
                    is_match = True
                if "__fattn__" in ln:
                    low = ln.lower()
                    if "fallback" in low or "fall back" in low:
                        out["seen_sched_reserve_fallback"] = True
                        out["sched_reserve_fallback_line_count"] += 1
                        is_match = True
                    out["fattn_line_count"] += 1
                    for m in re.finditer(r"__fattn__-(\\d+)", ln):
                        nodes.add("__fattn__-" + m.group(1))
                        try:
                            fattn_ids.add(int(m.group(1)))
                        except ValueError:
                            pass
                    m = re.search(r"(?:cuda\\s+backend|backend)\\s*(?:=|:)?\\s*([0-9]+)", ln, flags=re.IGNORECASE)
                    if m is not None:
                        try:
                            bid = int(m.group(1))
                            fattn_backend[bid] = fattn_backend.get(bid, 0) + 1
                        except ValueError:
                            pass
                    m = re.search(r"CUDA([0-9]+)", ln)
                    if m is not None:
                        try:
                            did = int(m.group(1))
                            fattn_cuda_dev[did] = fattn_cuda_dev.get(did, 0) + 1
                        except ValueError:
                            pass
                    if "cpu" in low:
                        out["fattn_cpu_line_count"] += 1
                    if "cuda" in low:
                        out["fattn_cuda_line_count"] += 1
                    is_match = True
                for m in re.finditer(r"(__[A-Za-z0-9_]+__)-\\d+", ln):
                    kind_nodes.add(m.group(1))
                    low = ln.lower()
                    if "cpu" in low:
                        kind_cpu[m.group(1)] = kind_cpu.get(m.group(1), 0) + 1
                    if "cuda" in low:
                        kind_cuda[m.group(1)] = kind_cuda.get(m.group(1), 0) + 1
                    is_match = True
                if is_match and len(match_lines) < 50:
                    match_lines.append(ln[:4000])
    except Exception:
        pass
    out["fattn_node_unique"] = len(nodes)
    out["match_lines"] = match_lines
    out["fattn_nodes_sample"] = sorted(nodes)[:50]
    out["node_kind_unique"] = len(kind_nodes)
    out["node_kinds_sample"] = sorted(kind_nodes)[:50]
    out["node_kind_cpu_top"] = sorted(kind_cpu.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    out["node_kind_cuda_top"] = sorted(kind_cuda.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    if fattn_ids:
        ids = sorted(fattn_ids)
        out["fattn_id_min"] = ids[0]
        out["fattn_id_max"] = ids[-1]
        out["fattn_id_span"] = int(ids[-1] - ids[0] + 1)
        missing = 0
        have = set(fattn_ids)
        for i in range(ids[0], ids[-1] + 1):
            if i not in have:
                missing += 1
        out["fattn_id_missing_count"] = missing
        out["fattn_expected_id_0_42_ok"] = (ids[0] == 0 and ids[-1] >= 42 and missing == 0)
    out["fattn_backend_counts"] = {str(k): int(v) for (k, v) in sorted(fattn_backend.items(), key=lambda kv: kv[0])}
    out["fattn_backend_unique"] = len(fattn_backend)
    out["fattn_backend0_only"] = (len(fattn_backend) == 1 and 0 in fattn_backend and len(fattn_ids) > 0)
    if out["fattn_backend_unique"] > 0:
        out["fattn_expected_backend0_ok"] = bool(out["fattn_backend0_only"])
    out["fattn_cuda_device_counts"] = {str(k): int(v) for (k, v) in sorted(fattn_cuda_dev.items(), key=lambda kv: kv[0])}
    out["fattn_cuda_device_unique"] = len(fattn_cuda_dev)
    out["fattn_cuda_device0_only"] = (len(fattn_cuda_dev) == 1 and 0 in fattn_cuda_dev and len(fattn_ids) > 0)
    if out["fattn_cuda_device_unique"] > 0:
        out["fattn_expected_cuda_device0_ok"] = bool(out["fattn_cuda_device0_only"])
    return out

def _last_float_before(haystack: str, needle: str):
    if needle not in haystack:
        return None
    prefix = haystack.split(needle, 1)[0]
    floats = re.findall(r"([0-9]+(?:\\.[0-9]+)?)", prefix)
    if not floats:
        return None
    return float(floats[-1])

def _tokens_after_slash(haystack: str):
    m = re.search(r"/\s*([0-9]+)\s*(?:tokens|runs)\b", haystack)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None

prefill_tps = None
prefill_ms_per_tok = None
prefill_tokens = None
gen_tps = None
gen_ms_per_tok = None
gen_tokens = None
load_time_ms = None
sample_time_ms = None
prompt_eval_time_ms = None
eval_time_ms = None
total_time_ms = None
for tl in timings_lines:
    if "[ Prompt:" in tl and "Generation:" in tl and "t/s" in tl:
        mp = re.search(r"Prompt:\s*([0-9]+(?:\.[0-9]+)?)\s*t/s", tl)
        mg = re.search(r"Generation:\s*([0-9]+(?:\.[0-9]+)?)\s*t/s", tl)
        if mp is not None:
            prefill_tps = float(mp.group(1))
        if mg is not None:
            gen_tps = float(mg.group(1))
    elif "load time" in tl:
        m = re.search(r"load time\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*ms", tl)
        if m is not None:
            load_time_ms = float(m.group(1))
    elif "sample time" in tl:
        m = re.search(r"sample time\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*ms", tl)
        if m is not None:
            sample_time_ms = float(m.group(1))
    elif "total time" in tl:
        m = re.search(r"total time\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*ms", tl)
        if m is not None:
            total_time_ms = float(m.group(1))
    elif "prompt eval time" in tl:
        m = re.search(r"prompt eval time\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*ms", tl)
        if m is not None:
            prompt_eval_time_ms = float(m.group(1))
        prefill_tps = _last_float_before(tl, "tokens per second")
        prefill_ms_per_tok = _last_float_before(tl, "ms per token")
        prefill_tokens = _tokens_after_slash(tl)
    elif tl.startswith("eval time") or " eval time" in tl:
        m = re.search(r"eval time\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*ms", tl)
        if m is not None:
            eval_time_ms = float(m.group(1))
        gen_tps = _last_float_before(tl, "tokens per second")
        gen_ms_per_tok = _last_float_before(tl, "ms per token")
        gen_tokens = _tokens_after_slash(tl)

summary_lines = []
summary_lines.append("exit_code=%d" % rc)
summary_lines.append("llama_cli=%s" % llama_cli)
if llama_commit:
    summary_lines.append("llama_commit=%s" % llama_commit)
summary_lines.append("runtime_label=%s" % runtime_label)
summary_lines.append("model_source=%s" % model_source)
summary_lines.append("model_quant=%s" % model_quant)
summary_lines.append("model_gguf=%s" % model)
if model_sha256:
    summary_lines.append("model_sha256=%s" % model_sha256)
summary_lines.append("ctx=%s" % ctx)
summary_lines.append("n_tokens=%s" % n_tokens)
summary_lines.append("n_gpu_layers=%s" % ngl)
try:
    summary_lines.append("model_size_bytes=%d" % int(os.path.getsize(model)))
except OSError:
    summary_lines.append("model_size_bytes=NA")
if first_output_s is None or rc != 0:
    summary_lines.append("ttft_first_output_s=NA")
    summary_lines.append("ttft_s=NA")
else:
    summary_lines.append("ttft_first_output_s=%.6f" % first_output_s)
    summary_lines.append("ttft_s=%.6f" % first_output_s)
summary_lines.append("wall_s=%.6f" % (end - start))
summary_lines.append("total_wall_s=%.6f" % (end - start))
summary_lines.append("max_rss_kb=%d" % int(ru.ru_maxrss))
if load_time_ms is not None:
    summary_lines.append("load_time_s=%.6f" % (load_time_ms / 1000.0))
if sample_time_ms is not None:
    summary_lines.append("sample_time_s=%.6f" % (sample_time_ms / 1000.0))
if prompt_eval_time_ms is not None:
    summary_lines.append("prompt_eval_s=%.6f" % (prompt_eval_time_ms / 1000.0))
if eval_time_ms is not None:
    summary_lines.append("eval_time_s=%.6f" % (eval_time_ms / 1000.0))
if total_time_ms is not None:
    summary_lines.append("total_time_s=%.6f" % (total_time_ms / 1000.0))
if prefill_tps is not None:
    summary_lines.append("prefill_tps=%.6f" % prefill_tps)
if prefill_ms_per_tok is not None:
    summary_lines.append("prefill_ms_per_token=%.6f" % prefill_ms_per_tok)
if prefill_tokens is not None:
    summary_lines.append("prompt_tokens=%d" % int(prefill_tokens))
if gen_tps is not None:
    summary_lines.append("generation_tps=%.6f" % gen_tps)
    summary_lines.append("decode_tps=%.6f" % gen_tps)
if gen_ms_per_tok is not None:
    summary_lines.append("generation_ms_per_token=%.6f" % gen_ms_per_tok)
if gen_tokens is not None:
    summary_lines.append("output_tokens=%d" % int(gen_tokens))
elif rc == 0:
    try:
        summary_lines.append("output_tokens=%d" % int(n_tokens))
    except Exception:
        pass

if fattn_lines > 0:
    summary_lines.append("fattn_log_lines=%d" % int(fattn_lines))
if fattn_ids:
    summary_lines.append("fattn_unique_nodes=%d" % int(len(fattn_ids)))

probe = scan_fattn_cli(log_raw)
probe_path = os.path.join(os.path.dirname(log_summary), "fattn_cli_probe.json")
try:
    with open(probe_path, "w", encoding="utf-8") as pf:
        json.dump(probe, pf, indent=2, sort_keys=True)
    summary_lines.append("fattn_cli_probe_path=%s" % probe_path)
except Exception:
    pass

def _probe_val(name, default="NA"):
    v = probe.get(name, None)
    if v is None:
        return default
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)

if probe.get("fattn_id_min") is not None:
    summary_lines.append("fattn_id_min=%s" % _probe_val("fattn_id_min"))
if probe.get("fattn_id_max") is not None:
    summary_lines.append("fattn_id_max=%s" % _probe_val("fattn_id_max"))
if probe.get("fattn_id_missing_count") is not None:
    summary_lines.append("fattn_id_missing_count=%s" % _probe_val("fattn_id_missing_count"))
if probe.get("fattn_expected_id_0_42_ok") is not None:
    summary_lines.append("fattn_expected_id_0_42_ok=%s" % _probe_val("fattn_expected_id_0_42_ok"))
if probe.get("fattn_backend_unique", 0) > 0:
    summary_lines.append("fattn_backend0_only=%s" % _probe_val("fattn_backend0_only"))
if probe.get("fattn_cuda_device_unique", 0) > 0:
    summary_lines.append("fattn_cuda_device0_only=%s" % _probe_val("fattn_cuda_device0_only"))
if probe.get("sched_reserve_line_count", 0) > 0:
    summary_lines.append("sched_reserve_line_count=%s" % _probe_val("sched_reserve_line_count"))
if probe.get("sched_reserve_graph_nodes") is not None:
    summary_lines.append("sched_reserve_graph_nodes=%s" % _probe_val("sched_reserve_graph_nodes"))
if probe.get("sched_reserve_graph_splits") is not None:
    summary_lines.append("sched_reserve_graph_splits=%s" % _probe_val("sched_reserve_graph_splits"))
if probe.get("sched_reserve_took_ms") is not None:
    summary_lines.append("sched_reserve_took_ms=%s" % _probe_val("sched_reserve_took_ms"))
if probe.get("seen_fattn_disabled"):
    summary_lines.append("fattn_seen_disabled=true")
if probe.get("seen_sched_reserve_cpu_fattn"):
    summary_lines.append("fattn_seen_sched_reserve_cpu=true")
if probe.get("sched_reserve_fallback_line_count", 0) > 0:
    summary_lines.append("sched_reserve_fallback_line_count=%s" % _probe_val("sched_reserve_fallback_line_count"))
if probe.get("seen_sched_reserve_fallback"):
    summary_lines.append("sched_reserve_seen_fallback=true")
if probe.get("sched_reserve_failure_line_count", 0) > 0:
    summary_lines.append("sched_reserve_failure_line_count=%s" % _probe_val("sched_reserve_failure_line_count"))
if probe.get("seen_sched_reserve_failure"):
    summary_lines.append("sched_reserve_seen_failure=true")

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
