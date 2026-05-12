#!/usr/bin/env sh
set -eu

OUT_DIR="${OUT_DIR:-/tmp/baseline_vllm}"
mkdir -p "$OUT_DIR"

ALLOW_RUN="${ALLOW_RUN:-0}"
ALLOW_FETCH="${ALLOW_FETCH:-0}"
VLLM_MODEL="${VLLM_MODEL:-}"
PROMPT="${PROMPT:-Explain Redis streams in one paragraph.}"
MAX_TOKENS="${MAX_TOKENS:-256}"
TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-1}"
VLLM_TRUST_REMOTE_CODE="${VLLM_TRUST_REMOTE_CODE:-0}"
VLLM_SPECULATIVE_CONFIG_JSON="${VLLM_SPECULATIVE_CONFIG_JSON:-}"
VLLM_EXTRA_LLM_KWARGS_JSON="${VLLM_EXTRA_LLM_KWARGS_JSON:-{}}"
VLLM_EXTRA_SAMPLING_KWARGS_JSON="${VLLM_EXTRA_SAMPLING_KWARGS_JSON:-{}}"
SMOKE_EVAL="${SMOKE_EVAL:-0}"
SMOKE_MAX_TOKENS_PER_TASK="${SMOKE_MAX_TOKENS_PER_TASK:-64}"

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
echo "- If VLLM_MODEL is not a readable local path, set ALLOW_FETCH=1 explicitly."
echo "- TTFT is not measured (Python API returns after generation completes)."
echo "- Set SMOKE_EVAL=1 to run a tiny deterministic smoke-eval task set and emit passed/total/local_quality_score into the baseline summary."

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

if [ ! -e "$VLLM_MODEL" ] && [ "$ALLOW_FETCH" != "1" ]; then
    echo "VLLM_MODEL is not a local path: $VLLM_MODEL" >&2
    echo "set ALLOW_FETCH=1 to allow vLLM/Hugging Face to fetch model artifacts" >&2
    exit 5
fi

echo
echo "== vLLM generate probe (approx; no streaming TTFT) =="
echo "model=$VLLM_MODEL"
echo "tp=$TENSOR_PARALLEL_SIZE"
echo "max_tokens=$MAX_TOKENS"
echo "allow_fetch=$ALLOW_FETCH"
echo "trust_remote_code=$VLLM_TRUST_REMOTE_CODE"
echo "speculative_config_json=$VLLM_SPECULATIVE_CONFIG_JSON"
echo "llm_kwargs_json=$VLLM_EXTRA_LLM_KWARGS_JSON"
echo "sampling_kwargs_json=$VLLM_EXTRA_SAMPLING_KWARGS_JSON"
echo "smoke_eval=$SMOKE_EVAL"
echo "smoke_max_tokens_per_task=$SMOKE_MAX_TOKENS_PER_TASK"
echo

LOG_RAW="$OUT_DIR/vllm_generate_probe.txt"
LOG_SUMMARY="$OUT_DIR/vllm_generate_probe.summary.txt"

python3 - <<'PY' "$VLLM_MODEL" "$PROMPT" "$MAX_TOKENS" "$TENSOR_PARALLEL_SIZE" "$LOG_RAW" "$LOG_SUMMARY" "$VLLM_TRUST_REMOTE_CODE" "$VLLM_SPECULATIVE_CONFIG_JSON" "$VLLM_EXTRA_LLM_KWARGS_JSON" "$VLLM_EXTRA_SAMPLING_KWARGS_JSON" "$SMOKE_EVAL" "$SMOKE_MAX_TOKENS_PER_TASK"
import json, resource, sys, time

model, prompt, max_tokens_s, tp_s, log_raw, log_summary, trust_remote_code_s, speculative_config_json, llm_kwargs_json, sampling_kwargs_json, smoke_eval_s, smoke_max_tokens_s = sys.argv[1:]
max_tokens = int(max_tokens_s)
tp = int(tp_s)
smoke_eval = (smoke_eval_s.strip() == "1")
smoke_max_tokens = int(smoke_max_tokens_s)

start = time.monotonic()
utc_start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

rc = 0
load_s = None
generate_wall_s = None
total_wall_s = None
generated_tokens = 0
passed_tasks = None
total_tasks = None
local_quality_score = None
spec_method = None
spec_model = None
spec_num_spec_tokens = None
spec_decode_num_drafts = None
spec_decode_num_draft_tokens = None
spec_decode_num_accepted_tokens = None
spec_decode_mean_accept_len = None
spec_decode_accept_rate = None

raw_lines = []
raw_lines.append("utc_start=" + utc_start)
raw_lines.append("model=" + model)
raw_lines.append("tp=%d" % tp)
raw_lines.append("max_tokens=%d" % max_tokens)
raw_lines.append("trust_remote_code=" + trust_remote_code_s)
raw_lines.append("speculative_config_json=" + speculative_config_json)
raw_lines.append("llm_kwargs_json=" + llm_kwargs_json)
raw_lines.append("sampling_kwargs_json=" + sampling_kwargs_json)
raw_lines.append("smoke_eval=%s" % ("1" if smoke_eval else "0"))
raw_lines.append("smoke_max_tokens_per_task=%d" % smoke_max_tokens)

try:
    from vllm import LLM, SamplingParams
    llm_kwargs = json.loads(llm_kwargs_json)
    sampling_kwargs = json.loads(sampling_kwargs_json)
    if not isinstance(llm_kwargs, dict):
        raise TypeError("VLLM_EXTRA_LLM_KWARGS_JSON must decode to an object")
    if not isinstance(sampling_kwargs, dict):
        raise TypeError("VLLM_EXTRA_SAMPLING_KWARGS_JSON must decode to an object")
    if trust_remote_code_s == "1":
        llm_kwargs.setdefault("trust_remote_code", True)
    if speculative_config_json.strip():
        speculative_config = json.loads(speculative_config_json)
        if not isinstance(speculative_config, dict):
            raise TypeError("VLLM_SPECULATIVE_CONFIG_JSON must decode to an object")
        spec_method = speculative_config.get("method")
        spec_model = speculative_config.get("model")
        spec_num_spec_tokens = speculative_config.get("num_speculative_tokens")
        if spec_method is not None:
            spec_method = str(spec_method)
        if spec_model is not None:
            spec_model = str(spec_model)
        if spec_num_spec_tokens is not None:
            try:
                spec_num_spec_tokens = int(spec_num_spec_tokens)
            except Exception:
                spec_num_spec_tokens = None
        llm_kwargs["speculative_config"] = speculative_config
    llm = LLM(model=model, tensor_parallel_size=tp, **llm_kwargs)
    loaded = time.monotonic()
    load_s = loaded - start
    if smoke_eval:
        import re

        def _first_int(text: str):
            m = re.search(r"[-+]?\\d+", text)
            if not m:
                return None
            try:
                return int(m.group(0))
            except Exception:
                return None

        def _first_json(text: str):
            import json as _json
            dec = _json.JSONDecoder()
            idxs = [i for i in (text.find("{"), text.find("[")) if i != -1]
            if not idxs:
                raise ValueError("no json start")
            idx = min(idxs)
            obj, _ = dec.raw_decode(text[idx:])
            return obj

        tasks = [
            {
                "id": "arith_23x17",
                "prompt": "Compute 23*17. Output only the integer.",
                "kind": "int",
                "expected": 391,
            },
            {
                "id": "reverse_stressed",
                "prompt": "Reverse the string 'stressed'. Output only the reversed string.",
                "kind": "exact",
                "expected": "desserts",
            },
            {
                "id": "kv_recall",
                "prompt": "Key/value list: alpha=cat, beta=dog, gamma=owl. What is the value of gamma? Output only the value.",
                "kind": "exact",
                "expected": "owl",
            },
            {
                "id": "json_obj",
                "prompt": "Output only a JSON object with keys a=1 and b=[2,3]. No extra text.",
                "kind": "json",
                "expected": {"a": 1, "b": [2, 3]},
            },
            {
                "id": "sort_json_array",
                "prompt": "Given the integers 9, 1, 4, 1, output only the sorted list as a JSON array.",
                "kind": "json",
                "expected": [1, 1, 4, 9],
            },
            {
                "id": "kib_1024",
                "prompt": "1024 bytes equals how many KiB? Output only the integer.",
                "kind": "int",
                "expected": 1,
            },
        ]

        smoke_path = log_raw + ".smoke.jsonl"
        smoke_md = log_raw + ".smoke.md"

        prompts = [t["prompt"] for t in tasks]
        sampling_args = {"max_tokens": smoke_max_tokens, "temperature": 0.0}
        sampling_args.update(sampling_kwargs)
        sampling = SamplingParams(**sampling_args)

        outs = llm.generate(prompts, sampling)
        end = time.monotonic()
        generate_wall_s = end - loaded
        total_wall_s = end - start

        generated_tokens = 0
        passed = 0
        results = []
        for t, out in zip(tasks, outs):
            rec = {"task_id": t["id"], "passed": False}
            try:
                text = ""
                token_ids = None
                if out.outputs and len(out.outputs) > 0:
                    o0 = out.outputs[0]
                    text = getattr(o0, "text", "") or ""
                    token_ids = getattr(o0, "token_ids", None)
                rec["output_text"] = text[:8000]
                if token_ids is not None:
                    try:
                        generated_tokens += int(len(token_ids))
                    except Exception:
                        pass

                kind = t["kind"]
                if kind == "int":
                    got = _first_int(text.strip())
                    rec["got"] = got
                    rec["expected"] = t["expected"]
                    rec["passed"] = (got == t["expected"])
                elif kind == "exact":
                    got = text.strip()
                    rec["got"] = got
                    rec["expected"] = t["expected"]
                    rec["passed"] = (got == t["expected"])
                elif kind == "json":
                    got = _first_json(text.strip())
                    rec["got"] = got
                    rec["expected"] = t["expected"]
                    rec["passed"] = (got == t["expected"])
                else:
                    rec["error"] = "unknown kind: " + str(kind)
            except Exception as e:
                rec["error"] = repr(e)
            if rec.get("passed"):
                passed += 1
            results.append(rec)

        passed_tasks = float(passed)
        total_tasks = float(len(tasks))
        local_quality_score = (100.0 * passed_tasks / total_tasks) if total_tasks > 0 else None

        with open(smoke_path, "w", encoding="utf-8") as sf:
            for r in results:
                sf.write(json.dumps(r, ensure_ascii=False) + "\\n")
        with open(smoke_md, "w", encoding="utf-8") as mf:
            mf.write("# vLLM smoke eval\\n\\n")
            mf.write(f"- passed_tasks: {passed}/{len(tasks)}\\n")
            mf.write(f"- local_quality_score: {local_quality_score:.6f}\\n" if local_quality_score is not None else "- local_quality_score: NA\\n")
            mf.write("\\n| task_id | passed |\\n| --- | --- |\\n")
            for r in results:
                mf.write(f"| {r.get('task_id','')} | {str(bool(r.get('passed'))).lower()} |\\n")

        raw_lines.append("smoke_eval_jsonl=" + smoke_path)
        raw_lines.append("smoke_eval_md=" + smoke_md)
    else:
        sampling_args = {"max_tokens": max_tokens, "temperature": 0.0}
        sampling_args.update(sampling_kwargs)
        sampling = SamplingParams(**sampling_args)

        outs = llm.generate([prompt], sampling)
        end = time.monotonic()
        generate_wall_s = end - loaded
        total_wall_s = end - start

        try:
            o0 = outs[0].outputs[0]
            if hasattr(o0, "token_ids") and o0.token_ids is not None:
                generated_tokens = len(o0.token_ids)
        except Exception:
            pass

    try:
        if hasattr(llm, "get_metrics"):
            metrics = llm.get_metrics()
            by_name = {}
            for m in metrics:
                name = getattr(m, "name", None)
                if not name or "spec_decode" not in str(name):
                    continue
                v = getattr(m, "value", None)
                if v is None:
                    continue
                if isinstance(v, (int, float)):
                    by_name[str(name)] = float(v)
                else:
                    try:
                        by_name[str(name)] = float(v)
                    except Exception:
                        pass
            spec_decode_num_drafts = by_name.get("vllm:spec_decode_num_drafts")
            spec_decode_num_draft_tokens = by_name.get("vllm:spec_decode_num_draft_tokens")
            spec_decode_num_accepted_tokens = by_name.get("vllm:spec_decode_num_accepted_tokens")
            if spec_decode_num_drafts is not None and spec_decode_num_drafts > 0 and spec_decode_num_accepted_tokens is not None:
                spec_decode_mean_accept_len = 1.0 + (spec_decode_num_accepted_tokens / spec_decode_num_drafts)
            if spec_decode_num_draft_tokens is not None and spec_decode_num_draft_tokens > 0 and spec_decode_num_accepted_tokens is not None:
                spec_decode_accept_rate = (spec_decode_num_accepted_tokens / spec_decode_num_draft_tokens)
    except Exception as e:
        raw_lines.append("spec_decode_metrics_error=" + repr(e))
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
summary.append("ttft_first_output_s=NA")
summary.append("ttft_s=NA")
summary.append("load_s=" + _fmt_float(load_s))
summary.append("generate_wall_s=" + _fmt_float(generate_wall_s))
summary.append("total_wall_s=" + _fmt_float(total_wall_s))
summary.append("generated_tokens=%d" % int(generated_tokens))
summary.append("output_tokens=%d" % int(generated_tokens))
if spec_method:
    summary.append("speculative_method=" + str(spec_method))
if spec_model:
    summary.append("speculative_draft_model=" + str(spec_model))
if spec_num_spec_tokens is not None:
    summary.append("speculative_num_speculative_tokens=%d" % int(spec_num_spec_tokens))
if spec_decode_num_drafts is not None:
    summary.append("spec_decode_num_drafts=%.0f" % float(spec_decode_num_drafts))
if spec_decode_num_draft_tokens is not None:
    summary.append("spec_decode_num_draft_tokens=%.0f" % float(spec_decode_num_draft_tokens))
if spec_decode_num_accepted_tokens is not None:
    summary.append("spec_decode_num_accepted_tokens=%.0f" % float(spec_decode_num_accepted_tokens))
if spec_decode_mean_accept_len is not None:
    summary.append("spec_decode_mean_accept_len=%.6f" % float(spec_decode_mean_accept_len))
if spec_decode_accept_rate is not None:
    summary.append("spec_decode_accept_rate=%.6f" % float(spec_decode_accept_rate))
if passed_tasks is not None and total_tasks is not None:
    summary.append("passed_tasks=%d" % int(passed_tasks))
    summary.append("total_tasks=%d" % int(total_tasks))
if local_quality_score is not None:
    summary.append("local_quality_score=%.6f" % float(local_quality_score))
if generate_wall_s is not None and generate_wall_s > 0 and generated_tokens > 0:
    summary.append("generation_tps=%.6f" % (generated_tokens / max(1e-9, generate_wall_s)))
    summary.append("decode_tps=%.6f" % (generated_tokens / max(1e-9, generate_wall_s)))
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

cat "$LOG_RAW" || true

echo
echo "== gpu snapshot (post) =="
GPU_POST="$OUT_DIR/nvidia_smi_post.txt"
nvidia-smi >"$GPU_POST" 2>&1 || true
cat "$GPU_POST" || true
