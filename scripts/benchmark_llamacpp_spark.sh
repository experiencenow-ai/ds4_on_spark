#!/usr/bin/env sh
set -eu

target_note="llama.cpp baseline (Spark/CUDA)"

b64_dec()
{
    if [ "${1:-}" = "" ]; then
        return 0
    fi
    if command -v base64 >/dev/null 2>&1; then
        if printf %s "$1" | base64 -d >/dev/null 2>&1; then
            printf %s "$1" | base64 -d
            return 0
        fi
        if printf %s "$1" | base64 --decode >/dev/null 2>&1; then
            printf %s "$1" | base64 --decode
            return 0
        fi
    fi
    return 1
}

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
SKIP_MODEL_SHA="${SKIP_MODEL_SHA:-0}"

OUT_DIR="${OUT_DIR:-/tmp/baseline_llamacpp}"
ALLOW_FETCH="${ALLOW_FETCH:-0}"
ALLOW_BUILD="${ALLOW_BUILD:-0}"
ALLOW_RUN="${ALLOW_RUN:-0}"
GPU_SAMPLE="${GPU_SAMPLE:-1}"
GPU_SAMPLE_INTERVAL_S="${GPU_SAMPLE_INTERVAL_S:-1}"

if [ "${PROMPT_B64:-}" != "" ]; then
    PROMPT="$(b64_dec "$PROMPT_B64" || echo "$PROMPT")"
fi
if [ "${EXTRA_ARGS_B64:-}" != "" ]; then
    EXTRA_ARGS="$(b64_dec "$EXTRA_ARGS_B64" || echo "$EXTRA_ARGS")"
fi

if [ "${LLAMA_DIR_B64:-}" != "" ]; then
    LLAMA_DIR="$(b64_dec "$LLAMA_DIR_B64" || echo "$LLAMA_DIR")"
fi
if [ "${MODEL_GGUF_B64:-}" != "" ]; then
    MODEL_GGUF="$(b64_dec "$MODEL_GGUF_B64" || echo "$MODEL_GGUF")"
fi
if [ "${LLAMA_CLI_B64:-}" != "" ]; then
    LLAMA_CLI="$(b64_dec "$LLAMA_CLI_B64" || echo "$LLAMA_CLI")"
fi
if [ "${RUNTIME_LABEL_B64:-}" != "" ]; then
    RUNTIME_LABEL="$(b64_dec "$RUNTIME_LABEL_B64" || echo "$RUNTIME_LABEL")"
fi
if [ "${MODEL_SOURCE_B64:-}" != "" ]; then
    MODEL_SOURCE="$(b64_dec "$MODEL_SOURCE_B64" || echo "$MODEL_SOURCE")"
fi
if [ "${MODEL_QUANT_B64:-}" != "" ]; then
    MODEL_QUANT="$(b64_dec "$MODEL_QUANT_B64" || echo "$MODEL_QUANT")"
fi

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

gpu_sampler_pid=""
gpu_sampler_file="$OUT_DIR/nvidia_smi_poll.csv"

gpu_sampler_start()
{
    if [ "$GPU_SAMPLE" != "1" ]; then
        return 0
    fi
    if ! command -v nvidia-smi >/dev/null 2>&1; then
        return 0
    fi
    (nvidia-smi --query-gpu=timestamp,index,memory.used,memory.total,utilization.gpu,utilization.memory,power.draw --format=csv -l "$GPU_SAMPLE_INTERVAL_S" >"$gpu_sampler_file" 2>&1) &
    gpu_sampler_pid=$!
    echo "gpu_sampler_pid=$gpu_sampler_pid"
    echo "gpu_sampler_file=$gpu_sampler_file"
    echo
}

gpu_sampler_stop()
{
    if [ "$gpu_sampler_pid" = "" ]; then
        return 0
    fi
    kill "$gpu_sampler_pid" 2>/dev/null || true
    wait "$gpu_sampler_pid" 2>/dev/null || true
    gpu_sampler_pid=""
}
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
        if [ ! -d "$LLAMA_DIR" ]; then
            echo "LLAMA_DIR is required for ALLOW_BUILD=1: $LLAMA_DIR"
            exit 6
        fi
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
if [ "$SKIP_MODEL_SHA" = "1" ]; then
    echo "sha256sum skipped (SKIP_MODEL_SHA=1)"
elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$MODEL_GGUF" || true
elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$MODEL_GGUF" || true
fi
echo

LOG_RAW="$OUT_DIR/llama_cli.log"
LOG_SUMMARY="$OUT_DIR/llama_cli.summary.txt"

echo "== run =="
echo "runtime_label=$RUNTIME_LABEL"
echo "prompt_chars=$(printf %s \"$PROMPT\" | wc -c | tr -d ' ')"
if command -v sha256sum >/dev/null 2>&1; then
    echo "prompt_sha256=$(printf %s \"$PROMPT\" | sha256sum | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
    echo "prompt_sha256=$(printf %s \"$PROMPT\" | shasum -a 256 | awk '{print $1}')"
fi
echo "cmd=$LLAMA_CLI -m $MODEL_GGUF -p <prompt> -n $N_TOKENS -c $CTX -ngl $N_GPU_LAYERS --perf $EXTRA_ARGS"
echo

LLAMA_CLI_SHA256=""
LLAMA_CLI_VERSION=""
if command -v sha256sum >/dev/null 2>&1; then
    LLAMA_CLI_SHA256="$(sha256sum "$LLAMA_CLI" 2>/dev/null | awk '{print $1}' || true)"
elif command -v shasum >/dev/null 2>&1; then
    LLAMA_CLI_SHA256="$(shasum -a 256 "$LLAMA_CLI" 2>/dev/null | awk '{print $1}' || true)"
fi
LLAMA_CLI_VERSION="$("$LLAMA_CLI" --version 2>/dev/null | head -n 1 | tr -s ' ' | sed 's/[[:space:]]*$//' || true)"

LLAMA_CLI_HELP_FILE="$OUT_DIR/llama_cli.help.txt"
("$LLAMA_CLI" --help >"$LLAMA_CLI_HELP_FILE" 2>&1) || true

rc_run=0
trap gpu_sampler_stop EXIT
gpu_sampler_start

python3 - <<'PY' "$LLAMA_CLI" "$MODEL_GGUF" "$PROMPT" "$N_TOKENS" "$CTX" "$N_GPU_LAYERS" "$EXTRA_ARGS" "$LOG_RAW" "$LOG_SUMMARY" "$RUNTIME_LABEL" "$MODEL_SOURCE" "$MODEL_QUANT" "$LLAMA_CLI_SHA256" "$LLAMA_CLI_VERSION" "$gpu_sampler_file" || rc_run=$?
import hashlib, json, math, os, resource, re, subprocess, sys, time, shlex

llama_cli, model, prompt, n_tokens, ctx, ngl, extra_args, log_raw, log_summary, runtime_label, model_source, model_quant, llama_cli_sha256, llama_cli_version, gpu_poll_csv = sys.argv[1:]

cmd = [llama_cli, "-m", model, "-p", prompt, "-n", n_tokens, "-c", ctx, "-ngl", ngl, "--perf"]
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

    def gguf_probe(path: str):
        info = {
            "is_gguf": False,
            "version": None,
            "architecture": None,
            "alignment": None,
            "has_mtp": None,
            "mtp_tensor_count": None,
        }
        try:
            with open(path, "rb") as bf:
                magic = bf.read(4)
                if magic == b"GGUF":
                    endian = "<"
                elif magic == b"FUGG":
                    endian = ">"
                else:
                    return info
                import struct
                info["is_gguf"] = True
                (version,) = struct.unpack(endian + "I", bf.read(4))
                info["version"] = int(version)
                (tensor_count,) = struct.unpack(endian + "Q", bf.read(8))
                (kv_count,) = struct.unpack(endian + "Q", bf.read(8))

                def read_u32():
                    (v,) = struct.unpack(endian + "I", bf.read(4))
                    return int(v)

                def read_u64():
                    (v,) = struct.unpack(endian + "Q", bf.read(8))
                    return int(v)

                def read_i32():
                    (v,) = struct.unpack(endian + "i", bf.read(4))
                    return int(v)

                def read_string():
                    n = read_u64()
                    if n <= 0:
                        return ""
                    b = bf.read(n)
                    return b.decode("utf-8", errors="replace")

                GGUF_TYPE_UINT8 = 0
                GGUF_TYPE_INT8 = 1
                GGUF_TYPE_UINT16 = 2
                GGUF_TYPE_INT16 = 3
                GGUF_TYPE_UINT32 = 4
                GGUF_TYPE_INT32 = 5
                GGUF_TYPE_FLOAT32 = 6
                GGUF_TYPE_BOOL = 7
                GGUF_TYPE_STRING = 8
                GGUF_TYPE_ARRAY = 9
                GGUF_TYPE_UINT64 = 10
                GGUF_TYPE_INT64 = 11
                GGUF_TYPE_FLOAT64 = 12

                def skip_value(vt: int):
                    if vt in (GGUF_TYPE_UINT8, GGUF_TYPE_INT8, GGUF_TYPE_BOOL):
                        bf.read(1)
                        return
                    if vt in (GGUF_TYPE_UINT16, GGUF_TYPE_INT16):
                        bf.read(2)
                        return
                    if vt in (GGUF_TYPE_UINT32, GGUF_TYPE_INT32, GGUF_TYPE_FLOAT32):
                        bf.read(4)
                        return
                    if vt in (GGUF_TYPE_UINT64, GGUF_TYPE_INT64, GGUF_TYPE_FLOAT64):
                        bf.read(8)
                        return
                    if vt == GGUF_TYPE_STRING:
                        n = read_u64()
                        if n > 0:
                            bf.read(n)
                        return
                    if vt == GGUF_TYPE_ARRAY:
                        elem_type = read_i32()
                        count = read_u64()
                        if elem_type == GGUF_TYPE_STRING:
                            for _ in range(int(count)):
                                n = read_u64()
                                if n > 0:
                                    bf.read(n)
                            return
                        elem_sizes = {
                            GGUF_TYPE_UINT8: 1,
                            GGUF_TYPE_INT8: 1,
                            GGUF_TYPE_BOOL: 1,
                            GGUF_TYPE_UINT16: 2,
                            GGUF_TYPE_INT16: 2,
                            GGUF_TYPE_UINT32: 4,
                            GGUF_TYPE_INT32: 4,
                            GGUF_TYPE_FLOAT32: 4,
                            GGUF_TYPE_UINT64: 8,
                            GGUF_TYPE_INT64: 8,
                            GGUF_TYPE_FLOAT64: 8,
                        }
                        sz = elem_sizes.get(elem_type)
                        if sz is None:
                            return
                        bf.read(int(count) * int(sz))
                        return

                # metadata kv
                for _ in range(int(kv_count)):
                    key = read_string()
                    vt = read_i32()
                    if key == "general.architecture" and vt == GGUF_TYPE_STRING:
                        info["architecture"] = read_string()
                        continue
                    if key == "general.alignment" and vt in (GGUF_TYPE_UINT32, GGUF_TYPE_INT32):
                        info["alignment"] = read_u32()
                        continue
                    skip_value(vt)

                # tensor infos
                mtp_count = 0
                for _ in range(int(tensor_count)):
                    name = read_string()
                    if name.startswith("mtp.0.") or name == "mtp.0":
                        mtp_count += 1
                    n_dims = read_u32()
                    if n_dims > 0:
                        bf.read(int(n_dims) * 8)
                    bf.read(4)  # ggml_type
                    bf.read(8)  # offset

                info["mtp_tensor_count"] = int(mtp_count)
                info["has_mtp"] = (mtp_count > 0)
                return info
        except Exception:
            return info

    gguf_info = gguf_probe(model)
    with open(os.path.join(os.path.dirname(log_raw), "gguf_probe.txt"), "w", encoding="utf-8") as gf:
        for k in ("is_gguf", "version", "architecture", "alignment", "has_mtp", "mtp_tensor_count"):
            gf.write(f"{k}={gguf_info.get(k)}\n")

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
    first_output_s = None

    import codecs

    line_buf = ""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    token_trace = {
        "path": os.path.join(os.path.dirname(log_raw), "token_trace.jsonl"),
        "fp": None,
        "count": 0,
        "first_ts": None,
        "last_ts": None,
        "mono_s": [],
        "expert_counts": {},
        "expert_events": 0,
        "queue_depth": [],
        "batch_size": [],
        "expert_batch_size": [],
        "router_top1_score": [],
        "router_topk_n": [],
        "mtp_draft": None,
        "mtp_accepted": None,
        "mtp_rejected": None,
        "fattn_probe": {
            "seen_fattn_disabled": False,
            "seen_sched_reserve_cpu_fattn": False,
            "fattn_line_count": 0,
            "fattn_cpu_line_count": 0,
            "fattn_cuda_line_count": 0,
            "sched_reserve_line_count": 0,
            "sched_reserve_graph_nodes": None,
            "sched_reserve_graph_splits": None,
            "sched_reserve_took_ms": None,
            "fattn_ids": set(),
            "fattn_nodes": set(),
            "fattn_backend_counts": {},
            "fattn_cuda_device_counts": {},
            "node_kind_nodes": set(),
            "node_kind_cpu_counts": {},
            "node_kind_cuda_counts": {},
            "match_lines": [],
        },
    }

    def _append_cap(xs, v, cap=200000):
        if len(xs) >= cap:
            return
        xs.append(v)

    def _count_expert(eid):
        try:
            eid_i = int(eid)
        except Exception:
            return
        if eid_i < 0:
            return
        d = token_trace["expert_counts"]
        d[eid_i] = int(d.get(eid_i, 0)) + 1
        token_trace["expert_events"] += 1

    def _record_evt_metrics(evt):
        # Best-effort: only record metrics if the runtime emits them in token JSON.
        for k in ("queue_depth", "expert_queue_depth"):
            v = evt.get(k)
            if isinstance(v, (int, float)):
                _append_cap(token_trace["queue_depth"], float(v))

        for k in ("batch_size", "batch_n", "n_batch"):
            v = evt.get(k)
            if isinstance(v, (int, float)):
                _append_cap(token_trace["batch_size"], float(v))

        for k in ("expert_batch_size", "expert_batch", "expert_batch_n"):
            v = evt.get(k)
            if isinstance(v, (int, float)):
                _append_cap(token_trace["expert_batch_size"], float(v))

        # Expert routing: record IDs if present.
        for k in ("expert_id", "expert", "router_expert_id"):
            v = evt.get(k)
            if isinstance(v, int):
                _count_expert(v)
        for k in ("expert_ids", "experts", "router_expert_ids"):
            v = evt.get(k)
            if isinstance(v, list):
                for e in v[:64]:
                    _count_expert(e)

        # Router top-k scores (best-effort): record only summary-compatible scalars.
        for k in ("scores", "router_scores", "router_topk_scores", "topk_scores"):
            v = evt.get(k)
            if isinstance(v, list) and v:
                xs = []
                for s in v[:64]:
                    if isinstance(s, (int, float)):
                        xs.append(float(s))
                if xs:
                    _append_cap(token_trace["router_top1_score"], max(xs))
                    _append_cap(token_trace["router_topk_n"], float(len(xs)))
                    break

        # MTP counters: record the last seen values if present.
        for k, outk in (
            ("mtp_draft", "mtp_draft"),
            ("mtp_accepted", "mtp_accepted"),
            ("mtp_rejected", "mtp_rejected"),
            ("draft_tokens", "mtp_draft"),
            ("accepted_tokens", "mtp_accepted"),
            ("rejected_tokens", "mtp_rejected"),
        ):
            v = evt.get(k)
            if isinstance(v, (int, float)):
                token_trace[outk] = float(v)

    def _fattn_probe_line(line: str):
        fp = token_trace.get("fattn_probe") or {}
        if not isinstance(fp, dict):
            return
        ln = line.rstrip("\n")
        is_match = False

        if ln.startswith("sched_reserve:"):
            fp["sched_reserve_line_count"] = int(fp.get("sched_reserve_line_count") or 0) + 1
            m = re.search(r"graph nodes\\s*=\\s*(\\d+)", ln)
            if m is not None:
                try:
                    fp["sched_reserve_graph_nodes"] = int(m.group(1))
                except Exception:
                    pass
            m = re.search(r"graph splits\\s*=\\s*(\\d+)", ln)
            if m is not None:
                try:
                    fp["sched_reserve_graph_splits"] = int(m.group(1))
                except Exception:
                    pass
            m = re.search(r"reserve took\\s*([0-9]+(?:\\.[0-9]+)?)\\s*ms", ln)
            if m is not None:
                try:
                    fp["sched_reserve_took_ms"] = float(m.group(1))
                except Exception:
                    pass
            is_match = True

        if "Flash Attention was auto, set to disabled" in ln:
            fp["seen_fattn_disabled"] = True
            is_match = True
        if "Flash Attention tensor is assigned to device CPU" in ln:
            fp["seen_sched_reserve_cpu_fattn"] = True
            is_match = True

        if "__fattn__" in ln:
            fp["fattn_line_count"] = int(fp.get("fattn_line_count") or 0) + 1
            nodes = fp.get("fattn_nodes")
            if isinstance(nodes, set):
                for m in re.finditer(r"__fattn__-(\\d+)", ln):
                    nodes.add("__fattn__-" + m.group(1))
                    ids = fp.get("fattn_ids")
                    if isinstance(ids, set):
                        try:
                            ids.add(int(m.group(1)))
                        except Exception:
                            pass
            m = re.search(r"(?:cuda\\s+backend|backend)\\s*(?:=|:)?\\s*([0-9]+)", ln, flags=re.IGNORECASE)
            if m is not None:
                try:
                    bid = int(m.group(1))
                    d = fp.get("fattn_backend_counts")
                    if isinstance(d, dict):
                        d[bid] = int(d.get(bid, 0)) + 1
                except Exception:
                    pass
            m = re.search(r"CUDA([0-9]+)", ln)
            if m is not None:
                try:
                    did = int(m.group(1))
                    d = fp.get("fattn_cuda_device_counts")
                    if isinstance(d, dict):
                        d[did] = int(d.get(did, 0)) + 1
                except Exception:
                    pass
            low = ln.lower()
            if "cpu" in low:
                fp["fattn_cpu_line_count"] = int(fp.get("fattn_cpu_line_count") or 0) + 1
            if "cuda" in low:
                fp["fattn_cuda_line_count"] = int(fp.get("fattn_cuda_line_count") or 0) + 1
            is_match = True

        for m in re.finditer(r"(__[A-Za-z0-9_]+__)-\\d+", ln):
            kinds = fp.get("node_kind_nodes")
            if isinstance(kinds, set):
                kinds.add(m.group(1))
            low = ln.lower()
            if "cpu" in low:
                d = fp.get("node_kind_cpu_counts")
                if isinstance(d, dict):
                    d[m.group(1)] = int(d.get(m.group(1), 0)) + 1
            if "cuda" in low:
                d = fp.get("node_kind_cuda_counts")
                if isinstance(d, dict):
                    d[m.group(1)] = int(d.get(m.group(1), 0)) + 1
            is_match = True

        if is_match:
            lines = fp.get("match_lines")
            if isinstance(lines, list) and len(lines) < 50:
                lines.append(ln[:4000])

    def _emit_text(s: str):
        f.write(s)
        f.flush()
        sys.stdout.write(s)
        sys.stdout.flush()

    def _handle_line(line: str):
        if line.lstrip().startswith("{") and "process_token" in line and "token" in line:
            try:
                evt = json.loads(line)
                if isinstance(evt, dict) and evt.get("function") == "process_token":
                    if token_trace["fp"] is None:
                        token_trace["fp"] = open(token_trace["path"], "w", encoding="utf-8")
                    token_trace["fp"].write(json.dumps(evt, ensure_ascii=False) + "\n")
                    token_trace["fp"].flush()
                    token_trace["count"] += 1
                    _append_cap(token_trace["mono_s"], float(time.monotonic() - start))
                    ts = evt.get("timestamp")
                    if isinstance(ts, (int, float)):
                        if token_trace["first_ts"] is None:
                            token_trace["first_ts"] = float(ts)
                        token_trace["last_ts"] = float(ts)
                    _record_evt_metrics(evt)
            except Exception:
                pass
        _fattn_probe_line(line)
        if "prompt eval time" in line or ("eval time" in line and "prompt eval time" not in line) or ("Prompt:" in line and "Generation:" in line):
            timings_lines.append(line.strip())
        _emit_text(line)

    assert proc.stdout is not None
    while True:
        b = proc.stdout.read(1)
        if b == b"":
            break
        if first_output_s is None:
            first_output_s = time.monotonic() - start
        try:
            s = decoder.decode(b)
        except Exception:
            s = ""
        line_buf += s
        while "\n" in line_buf:
            line, line_buf = line_buf.split("\n", 1)
            _handle_line(line + "\n")

    try:
        tail = decoder.decode(b"", final=True)
        if tail:
            line_buf += tail
    except Exception:
        pass

    if line_buf != "":
        _handle_line(line_buf)

    rc = proc.wait()
    if token_trace["fp"] is not None:
        try:
            token_trace["fp"].close()
        except Exception:
            pass

end = time.monotonic()

ru = resource.getrusage(resource.RUSAGE_CHILDREN)
max_rss_native = int(ru.ru_maxrss)
max_rss_bytes = max_rss_native
if sys.platform.startswith("linux"):
    max_rss_bytes = max_rss_native * 1024

def _pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    if len(xs) == 1:
        return float(xs[0])
    k = (len(xs) - 1) * float(p)
    f = int(math.floor(k))
    c = int(math.ceil(k))
    if f == c:
        return float(xs[f])
    return float(xs[f] * (c - k) + xs[c] * (k - f))

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
    elif "Prompt:" in tl and "Generation:" in tl:
        mp = re.search(r"Prompt:\s*([0-9]+(?:\.[0-9]+)?)\s*t/s", tl)
        mg = re.search(r"Generation:\s*([0-9]+(?:\.[0-9]+)?)\s*t/s", tl)
        if mp is not None:
            prefill_tps = float(mp.group(1))
        if mg is not None:
            gen_tps = float(mg.group(1))

gpu_used_mib = []
gpu_used_mib_gpu0 = []
gpu_util_gpu_pct = []
gpu_util_gpu_pct_gpu0 = []
gpu_util_mem_pct = []
gpu_util_mem_pct_gpu0 = []
gpu_power_w = []
gpu_power_w_gpu0 = []
gpu_indices = set()
if gpu_poll_csv and os.path.exists(gpu_poll_csv):
    try:
        with open(gpu_poll_csv, "r", encoding="utf-8", errors="replace") as pf:
            for ln in pf:
                if "memory.used" in ln and "timestamp" in ln:
                    continue
                cols = [c.strip() for c in ln.split(",")]
                if len(cols) < 7:
                    continue
                m_idx = re.search(r"(\\d+)", cols[1])
                idx = None
                if m_idx:
                    try:
                        idx = int(m_idx.group(1))
                        gpu_indices.add(idx)
                    except Exception:
                        idx = None

                m = re.search(r"(\\d+)", cols[2])
                if m:
                    v = float(int(m.group(1)))
                    gpu_used_mib.append(v)
                    if idx == 0:
                        gpu_used_mib_gpu0.append(v)

                m = re.search(r"([0-9]+(?:\\.[0-9]+)?)", cols[4])
                if m:
                    v = float(m.group(1))
                    gpu_util_gpu_pct.append(v)
                    if idx == 0:
                        gpu_util_gpu_pct_gpu0.append(v)

                m = re.search(r"([0-9]+(?:\\.[0-9]+)?)", cols[5])
                if m:
                    v = float(m.group(1))
                    gpu_util_mem_pct.append(v)
                    if idx == 0:
                        gpu_util_mem_pct_gpu0.append(v)

                m = re.search(r"([0-9]+(?:\\.[0-9]+)?)", cols[6])
                if m:
                    v = float(m.group(1))
                    gpu_power_w.append(v)
                    if idx == 0:
                        gpu_power_w_gpu0.append(v)

                if len(gpu_used_mib) >= 200000:
                    break
    except Exception:
        gpu_used_mib = []
        gpu_used_mib_gpu0 = []
        gpu_util_gpu_pct = []
        gpu_util_gpu_pct_gpu0 = []
        gpu_util_mem_pct = []
        gpu_util_mem_pct_gpu0 = []
        gpu_power_w = []
        gpu_power_w_gpu0 = []
        gpu_indices = set()

token_latency_ms = []
try:
    monos = [float(x) for x in token_trace.get("mono_s") or []]
    if len(monos) > 1:
        for i in range(1, len(monos)):
            dt = monos[i] - monos[i - 1]
            if dt < 0:
                continue
            token_latency_ms.append(dt * 1000.0)
except Exception:
    token_latency_ms = []

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
summary_lines.append("gguf_is_gguf=%s" % str(gguf_info.get("is_gguf")))
summary_lines.append("gguf_version=%s" % (str(gguf_info.get("version")) if gguf_info.get("version") is not None else "NA"))
summary_lines.append("gguf_architecture=%s" % (gguf_info.get("architecture") or "NA"))
summary_lines.append("gguf_alignment=%s" % (str(gguf_info.get("alignment")) if gguf_info.get("alignment") is not None else "NA"))
summary_lines.append("gguf_has_mtp=%s" % (str(gguf_info.get("has_mtp")) if gguf_info.get("has_mtp") is not None else "NA"))
summary_lines.append("gguf_mtp_tensor_count=%s" % (str(gguf_info.get("mtp_tensor_count")) if gguf_info.get("mtp_tensor_count") is not None else "NA"))
summary_lines.append("ctx=%s" % ctx)
summary_lines.append("n_tokens=%s" % n_tokens)
summary_lines.append("n_gpu_layers=%s" % ngl)
if first_output_s is None:
    summary_lines.append("ttft_first_output_s=NA")
else:
    summary_lines.append("ttft_first_output_s=%.6f" % first_output_s)
summary_lines.append("token_trace_events=%d" % int(token_trace["count"]))
if token_trace["first_ts"] is None or token_trace["last_ts"] is None:
    summary_lines.append("token_trace_ts_first=NA")
    summary_lines.append("token_trace_ts_last=NA")
else:
    summary_lines.append("token_trace_ts_first=%.6f" % float(token_trace["first_ts"]))
    summary_lines.append("token_trace_ts_last=%.6f" % float(token_trace["last_ts"]))
    if token_trace["count"] > 1 and float(token_trace["last_ts"]) > float(token_trace["first_ts"]):
        dur = float(token_trace["last_ts"]) - float(token_trace["first_ts"])
        summary_lines.append("token_trace_duration_s=%.6f" % dur)
        summary_lines.append("token_trace_tps=%.6f" % (float(token_trace["count"]) / max(1e-9, dur)))
    else:
        summary_lines.append("token_trace_duration_s=NA")
        summary_lines.append("token_trace_tps=NA")

summary_lines.append("token_latency_samples=%d" % int(len(token_latency_ms)))
if token_latency_ms:
    summary_lines.append("token_latency_ms_min=%.6f" % min(token_latency_ms))
    summary_lines.append("token_latency_ms_p50=%.6f" % (_pct(token_latency_ms, 0.50) or 0.0))
    summary_lines.append("token_latency_ms_p90=%.6f" % (_pct(token_latency_ms, 0.90) or 0.0))
    summary_lines.append("token_latency_ms_p99=%.6f" % (_pct(token_latency_ms, 0.99) or 0.0))
    summary_lines.append("token_latency_ms_max=%.6f" % max(token_latency_ms))
    summary_lines.append("token_latency_ms_mean=%.6f" % (sum(token_latency_ms) / max(1, len(token_latency_ms))))
else:
    summary_lines.append("token_latency_ms_min=NA")
    summary_lines.append("token_latency_ms_p50=NA")
    summary_lines.append("token_latency_ms_p90=NA")
    summary_lines.append("token_latency_ms_p99=NA")
    summary_lines.append("token_latency_ms_max=NA")
    summary_lines.append("token_latency_ms_mean=NA")

if gpu_used_mib:
    summary_lines.append("gpu_poll_mem_used_min_mib=%.3f" % min(gpu_used_mib))
    summary_lines.append("gpu_poll_mem_used_max_mib=%.3f" % max(gpu_used_mib))
    summary_lines.append("gpu_poll_mem_used_delta_mib=%.3f" % (max(gpu_used_mib) - min(gpu_used_mib)))
else:
    summary_lines.append("gpu_poll_mem_used_min_mib=NA")
    summary_lines.append("gpu_poll_mem_used_max_mib=NA")
    summary_lines.append("gpu_poll_mem_used_delta_mib=NA")

summary_lines.append("gpu_poll_gpu_index_unique_count=%d" % int(len(gpu_indices)))
if gpu_indices:
    summary_lines.append("gpu_poll_gpu_indices=%s" % ",".join(str(x) for x in sorted(gpu_indices)))
else:
    summary_lines.append("gpu_poll_gpu_indices=NA")

if gpu_used_mib_gpu0:
    summary_lines.append("gpu_poll_gpu0_mem_used_min_mib=%.3f" % min(gpu_used_mib_gpu0))
    summary_lines.append("gpu_poll_gpu0_mem_used_max_mib=%.3f" % max(gpu_used_mib_gpu0))
    summary_lines.append("gpu_poll_gpu0_mem_used_delta_mib=%.3f" % (max(gpu_used_mib_gpu0) - min(gpu_used_mib_gpu0)))
else:
    summary_lines.append("gpu_poll_gpu0_mem_used_min_mib=NA")
    summary_lines.append("gpu_poll_gpu0_mem_used_max_mib=NA")
    summary_lines.append("gpu_poll_gpu0_mem_used_delta_mib=NA")

def _agg_stats_pct(xs, prefix):
    if not xs:
        summary_lines.append(prefix + "_samples=0")
        summary_lines.append(prefix + "_min=NA")
        summary_lines.append(prefix + "_p50=NA")
        summary_lines.append(prefix + "_p90=NA")
        summary_lines.append(prefix + "_max=NA")
        summary_lines.append(prefix + "_mean=NA")
        return
    summary_lines.append(prefix + "_samples=%d" % len(xs))
    summary_lines.append(prefix + "_min=%.6f" % min(xs))
    summary_lines.append(prefix + "_p50=%.6f" % (_pct(xs, 0.50) or 0.0))
    summary_lines.append(prefix + "_p90=%.6f" % (_pct(xs, 0.90) or 0.0))
    summary_lines.append(prefix + "_max=%.6f" % max(xs))
    summary_lines.append(prefix + "_mean=%.6f" % (sum(xs) / max(1, len(xs))))

_agg_stats_pct(gpu_util_gpu_pct, "gpu_poll_util_gpu_pct")
_agg_stats_pct(gpu_util_mem_pct, "gpu_poll_util_mem_pct")
_agg_stats_pct(gpu_power_w, "gpu_poll_power_w")
_agg_stats_pct(gpu_util_gpu_pct_gpu0, "gpu_poll_gpu0_util_gpu_pct")
_agg_stats_pct(gpu_util_mem_pct_gpu0, "gpu_poll_gpu0_util_mem_pct")
_agg_stats_pct(gpu_power_w_gpu0, "gpu_poll_gpu0_power_w")

summary_lines.append("expert_events=%d" % int(token_trace.get("expert_events") or 0))
if token_trace.get("expert_counts"):
    top = sorted(token_trace["expert_counts"].items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    summary_lines.append("expert_unique_count=%d" % len(token_trace["expert_counts"]))
    summary_lines.append("expert_top5=%s" % ",".join("%d:%d" % (k, v) for (k, v) in top))
else:
    summary_lines.append("expert_unique_count=NA")
    summary_lines.append("expert_top5=NA")

def _agg_stats(xs, prefix):
    if not xs:
        summary_lines.append(prefix + "_samples=0")
        summary_lines.append(prefix + "_min=NA")
        summary_lines.append(prefix + "_max=NA")
        summary_lines.append(prefix + "_mean=NA")
        return
    summary_lines.append(prefix + "_samples=%d" % len(xs))
    summary_lines.append(prefix + "_min=%.6f" % min(xs))
    summary_lines.append(prefix + "_max=%.6f" % max(xs))
    summary_lines.append(prefix + "_mean=%.6f" % (sum(xs) / max(1, len(xs))))

_agg_stats(token_trace.get("queue_depth") or [], "queue_depth")
_agg_stats(token_trace.get("batch_size") or [], "batch_size")
_agg_stats(token_trace.get("expert_batch_size") or [], "expert_batch_size")
_agg_stats(token_trace.get("router_top1_score") or [], "router_top1_score")
_agg_stats(token_trace.get("router_topk_n") or [], "router_topk_n")

for k in ("mtp_draft", "mtp_accepted", "mtp_rejected"):
    v = token_trace.get(k)
    if v is None:
        summary_lines.append(k + "=NA")
    else:
        summary_lines.append(k + "=%.6f" % float(v))
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

fp = token_trace.get("fattn_probe") or {}
if isinstance(fp, dict):
    ids = fp.get("fattn_ids")
    if isinstance(ids, set) and ids:
        id_min = min(ids)
        id_max = max(ids)
        span = (id_max - id_min) + 1
        missing = 0
        for x in range(id_min, id_max + 1):
            if x not in ids:
                missing += 1
        summary_lines.append("fattn_id_min=%d" % int(id_min))
        summary_lines.append("fattn_id_max=%d" % int(id_max))
        summary_lines.append("fattn_id_span=%d" % int(span))
        summary_lines.append("fattn_id_missing_count=%d" % int(missing))
    else:
        summary_lines.append("fattn_id_min=NA")
        summary_lines.append("fattn_id_max=NA")
        summary_lines.append("fattn_id_span=NA")
        summary_lines.append("fattn_id_missing_count=NA")

    summary_lines.append("fattn_seen_disabled=%s" % str(bool(fp.get("seen_fattn_disabled"))))
    summary_lines.append("fattn_seen_sched_reserve_cpu=%s" % str(bool(fp.get("seen_sched_reserve_cpu_fattn"))))
    summary_lines.append("fattn_line_count=%d" % int(fp.get("fattn_line_count") or 0))

    nodes = fp.get("fattn_nodes")
    summary_lines.append("fattn_node_unique=%s" % (str(len(nodes)) if isinstance(nodes, set) else "NA"))

    bc = fp.get("fattn_backend_counts")
    if isinstance(bc, dict) and bc:
        summary_lines.append("fattn_backend_unique=%d" % len(bc))
        summary_lines.append("fattn_backend0_only=%s" % str((len(bc) == 1 and 0 in bc)))
        summary_lines.append("fattn_backend_counts=%s" % ",".join("%s:%s" % (k, bc[k]) for k in sorted(bc)))
    else:
        summary_lines.append("fattn_backend_unique=NA")
        summary_lines.append("fattn_backend0_only=NA")
        summary_lines.append("fattn_backend_counts=NA")

    dc = fp.get("fattn_cuda_device_counts")
    if isinstance(dc, dict) and dc:
        summary_lines.append("fattn_cuda_device_unique=%d" % len(dc))
        summary_lines.append("fattn_cuda_device0_only=%s" % str((len(dc) == 1 and 0 in dc)))
        summary_lines.append("fattn_cuda_device_counts=%s" % ",".join("%s:%s" % (k, dc[k]) for k in sorted(dc)))
    else:
        summary_lines.append("fattn_cuda_device_unique=NA")
        summary_lines.append("fattn_cuda_device0_only=NA")
        summary_lines.append("fattn_cuda_device_counts=NA")

    summary_lines.append("sched_reserve_line_count=%d" % int(fp.get("sched_reserve_line_count") or 0))
    for k in ("sched_reserve_graph_nodes", "sched_reserve_graph_splits", "sched_reserve_took_ms"):
        v = fp.get(k)
        if v is None:
            summary_lines.append(k + "=NA")
        elif isinstance(v, float):
            summary_lines.append(k + "=%.6f" % float(v))
        else:
            summary_lines.append(k + "=%s" % str(v))

    kinds = fp.get("node_kind_nodes")
    summary_lines.append("node_kind_unique=%s" % (str(len(kinds)) if isinstance(kinds, set) else "NA"))
    for name, key in (("node_kind_cpu_top", "node_kind_cpu_counts"), ("node_kind_cuda_top", "node_kind_cuda_counts")):
        d = fp.get(key)
        if isinstance(d, dict) and d:
            top = sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            summary_lines.append(name + "=%s" % ",".join("%s:%s" % (k, v) for (k, v) in top))
        else:
            summary_lines.append(name + "=NA")

    try:
        fp_out = {
            "seen_fattn_disabled": bool(fp.get("seen_fattn_disabled")),
            "seen_sched_reserve_cpu_fattn": bool(fp.get("seen_sched_reserve_cpu_fattn")),
            "fattn_line_count": int(fp.get("fattn_line_count") or 0),
            "fattn_cpu_line_count": int(fp.get("fattn_cpu_line_count") or 0),
            "fattn_cuda_line_count": int(fp.get("fattn_cuda_line_count") or 0),
            "fattn_nodes": sorted(list(fp.get("fattn_nodes") or []))[:2000],
            "fattn_ids": sorted(list(fp.get("fattn_ids") or []))[:2000],
            "fattn_backend_counts": fp.get("fattn_backend_counts") or {},
            "fattn_cuda_device_counts": fp.get("fattn_cuda_device_counts") or {},
            "sched_reserve_line_count": int(fp.get("sched_reserve_line_count") or 0),
            "sched_reserve_graph_nodes": fp.get("sched_reserve_graph_nodes"),
            "sched_reserve_graph_splits": fp.get("sched_reserve_graph_splits"),
            "sched_reserve_took_ms": fp.get("sched_reserve_took_ms"),
            "node_kind_unique": len(fp.get("node_kind_nodes") or []),
            "node_kind_cpu_counts": fp.get("node_kind_cpu_counts") or {},
            "node_kind_cuda_counts": fp.get("node_kind_cuda_counts") or {},
            "match_lines": list(fp.get("match_lines") or [])[:50],
        }
        with open(os.path.join(os.path.dirname(log_raw), "fattn_cli_probe.json"), "w", encoding="utf-8") as pf:
            json.dump(fp_out, pf, sort_keys=True, indent=2)
    except Exception:
        pass

with open(log_summary, "w", encoding="utf-8") as sf:
    sf.write("\n".join(summary_lines) + "\n")

print("\n== baseline summary (approx) ==")
print("\n".join(summary_lines))
sys.exit(rc)
PY

gpu_sampler_stop
trap - EXIT

echo
echo "== gpu snapshot (post) =="
GPU_POST="$OUT_DIR/nvidia_smi_post.txt"
nvidia-smi >"$GPU_POST" 2>&1 || true
cat "$GPU_POST" || true

exit "$rc_run"
