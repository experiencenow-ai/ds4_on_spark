#!/usr/bin/env python3
"""Resident llama-server batching/concurrency throughput sweep for Spark-style hosts.

This is a heavier companion to benchmark_llamacpp_server_sweep.py. It is intended
to identify which server batching configuration maximizes aggregate throughput
under load, while also capturing DSv4 Flash reservation / fallback signals from
server logs.
"""

import base64
import hashlib
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed


def env_str_b64(name, default=""):
    b64 = os.environ.get(name + "_B64", "")
    if b64:
        try:
            return base64.b64decode(b64.encode("utf-8")).decode("utf-8", errors="replace")
        except Exception:
            pass
    return os.environ.get(name, default)


def env_int(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return int(default)


def env_float(name, default):
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return float(default)


def split_ints(s):
    out = []
    for part in s.replace(",", " ").split():
        try:
            out.append(int(part))
        except ValueError:
            pass
    return out


def split_opt_ints(s):
    if not s:
        return []
    return split_ints(s)


def http_json(method, url, payload=None, timeout=60.0):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    if not body:
        return None
    return json.loads(body.decode("utf-8", errors="replace"))


def http_text(method, url, payload=None, timeout=60.0):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    return body.decode("utf-8", errors="replace")


def wait_health(base_url, timeout_s, poll_s):
    start = time.monotonic()
    last_err = ""
    while (time.monotonic() - start) < timeout_s:
        try:
            data = http_json("GET", base_url + "/health", None, timeout=5.0)
            if isinstance(data, dict) and data.get("status") == "ok":
                return (time.monotonic() - start, data)
            last_err = json.dumps(data, sort_keys=True)
        except Exception as e:
            last_err = str(e)
        time.sleep(poll_s)
    raise RuntimeError("server did not become healthy: " + last_err)


def make_prompt(target_words):
    words = []
    i = 0
    stem = [
        "Spark",
        "quantized",
        "DeepSeek",
        "routing",
        "prefill",
        "latency",
        "expert",
        "cache",
    ]
    while len(words) < target_words:
        words.append(stem[i % len(stem)] + str(i % 997))
        i += 1
    return " ".join(words)


def extract_timings(data):
    t = data.get("timings", {}) if isinstance(data, dict) else {}
    return {
        "prompt_n": t.get("prompt_n") or data.get("tokens_evaluated"),
        "prompt_ms": t.get("prompt_ms"),
        "prompt_per_second": t.get("prompt_per_second"),
        "predicted_n": t.get("predicted_n") or data.get("tokens_predicted"),
        "predicted_ms": t.get("predicted_ms"),
        "predicted_per_second": t.get("predicted_per_second"),
        "tokens_cached": data.get("tokens_cached"),
        "tokens_evaluated": data.get("tokens_evaluated"),
    }


def scan_fattn_reservation(log_path):
    out = {
        "log_path": log_path,
        "seen_fattn_disabled": False,
        "seen_sched_reserve_cpu_fattn": False,
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
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                ln = line.rstrip("\n")
                is_match = False
                if ln.startswith("sched_reserve:"):
                    out["sched_reserve_line_count"] += 1
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
                if "Flash Attention was auto, set to disabled" in ln:
                    out["seen_fattn_disabled"] = True
                    is_match = True
                if "Flash Attention tensor is assigned to device CPU" in ln:
                    out["seen_sched_reserve_cpu_fattn"] = True
                    is_match = True
                if "__fattn__" in ln:
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
                    low = ln.lower()
                    if "cpu" in low:
                        out["fattn_cpu_line_count"] += 1
                    if "cuda" in low:
                        out["fattn_cuda_line_count"] += 1
                    is_match = True
                if "__op__" in ln:
                    for m in re.finditer(r"__op__-([^\\s:]+)", ln):
                        kind = m.group(1)
                        kind_nodes.add(kind)
                        low = ln.lower()
                        if "cpu" in low:
                            kind_cpu[kind] = kind_cpu.get(kind, 0) + 1
                        if "cuda" in low:
                            kind_cuda[kind] = kind_cuda.get(kind, 0) + 1
                    is_match = True
                if "sched_reserve:" in ln:
                    is_match = True
                if is_match and len(match_lines) < 250:
                    match_lines.append(ln)
    except Exception:
        pass
    out["match_lines"] = match_lines
    out["fattn_node_unique"] = len(nodes)
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
    out["node_kind_unique"] = len(kind_nodes)
    out["node_kind_cpu_top"] = sorted(kind_cpu.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    out["node_kind_cuda_top"] = sorted(kind_cuda.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    return out


def scan_multislot_reservation(log_path):
    out = {
        "log_path": log_path,
        "seen_sched_reserve_fail": False,
        "seen_reshape_3d": False,
        "seen_n_comp_visible_le_n_comp_cache": False,
        "seen_assert": False,
        "match_lines": [],
    }
    if not log_path or not os.path.exists(log_path):
        return out
    lines = []
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                ln = line.rstrip("\n")
                low = ln.lower()
                is_match = False
                if "sched_reserve" in low and ("fail" in low or "error" in low or "assert" in low):
                    out["seen_sched_reserve_fail"] = True
                    is_match = True
                if "ggml_reshape_3d" in ln:
                    out["seen_reshape_3d"] = True
                    is_match = True
                if "n_comp_visible" in ln and "n_comp_cache" in ln and "<=" in ln:
                    out["seen_n_comp_visible_le_n_comp_cache"] = True
                    is_match = True
                if "assert" in low:
                    out["seen_assert"] = True
                    is_match = True
                if is_match and len(lines) < 200:
                    lines.append(ln)
    except Exception:
        pass
    out["match_lines"] = lines
    return out


def build_server_args(base_args, parallel_flag, parallel_value, batch_flag, batch_value, ubatch_flag, ubatch_value):
    args = []
    if base_args.strip():
        args.extend(shlex.split(base_args))
    if parallel_flag and parallel_value is not None:
        args.extend([parallel_flag, str(parallel_value)])
    if batch_flag and batch_value is not None:
        args.extend([batch_flag, str(batch_value)])
    if ubatch_flag and ubatch_value is not None:
        args.extend([ubatch_flag, str(ubatch_value)])
    return args


def wave_request(base_url, prompt, n_predict, cache_prompt, timeout_s):
    payload = {"prompt": prompt, "n_predict": int(n_predict), "cache_prompt": bool(cache_prompt), "temperature": 0}
    start = time.monotonic()
    data = http_json("POST", base_url + "/completion", payload, timeout=timeout_s)
    wall = time.monotonic() - start
    return (wall, data)


def run_wave(base_url, prompt_words, n_predict, cache_prompt, concurrency, repeats, per_request_timeout_s):
    prompt = make_prompt(prompt_words)
    prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    out_rows = []
    for repeat_index in range(repeats):
        wave_start = time.monotonic()
        req_rows = []
        errors = 0
        with ThreadPoolExecutor(max_workers=int(concurrency)) as ex:
            futs = []
            for _ in range(int(concurrency)):
                futs.append(ex.submit(wave_request, base_url, prompt, n_predict, cache_prompt, per_request_timeout_s))
            for fut in as_completed(futs):
                row = {
                    "status": "ok",
                    "wall_s": None,
                    "timings": {},
                    "response_keys": [],
                }
                try:
                    wall_s, data = fut.result()
                    row["wall_s"] = float(wall_s)
                    if isinstance(data, dict):
                        row["timings"] = extract_timings(data)
                        row["response_keys"] = sorted(data.keys())
                except urllib.error.HTTPError as e:
                    row["status"] = "http_error"
                    try:
                        row["error"] = e.read().decode("utf-8", errors="replace")
                    except Exception:
                        row["error"] = "http_error"
                    row["code"] = int(getattr(e, "code", 0) or 0)
                    errors += 1
                except Exception as e:
                    row["status"] = "error"
                    row["error"] = str(e)
                    errors += 1
                req_rows.append(row)
        wave_wall_s = time.monotonic() - wave_start
        prompt_tok_total = 0
        gen_tok_total = 0
        ok_count = 0
        for r in req_rows:
            t = r.get("timings", {})
            if r.get("status") == "ok":
                ok_count += 1
            try:
                if t.get("prompt_n") is not None:
                    prompt_tok_total += int(t.get("prompt_n") or 0)
            except Exception:
                pass
            try:
                if t.get("predicted_n") is not None:
                    gen_tok_total += int(t.get("predicted_n") or 0)
            except Exception:
                pass
        agg = {
            "repeat_index": repeat_index,
            "concurrency": int(concurrency),
            "prompt_words": int(prompt_words),
            "prompt_sha256": prompt_sha,
            "prompt_chars": len(prompt.encode("utf-8")),
            "n_predict": int(n_predict),
            "cache_prompt": int(cache_prompt),
            "wave_wall_s": float(wave_wall_s),
            "ok_count": int(ok_count),
            "error_count": int(errors),
            "agg_prompt_tokens": int(prompt_tok_total),
            "agg_generated_tokens": int(gen_tok_total),
            "agg_prompt_tok_s": (float(prompt_tok_total) / float(wave_wall_s)) if wave_wall_s > 0 else None,
            "agg_generated_tok_s": (float(gen_tok_total) / float(wave_wall_s)) if wave_wall_s > 0 else None,
            "requests": req_rows,
        }
        out_rows.append(agg)
    return out_rows


def write_summary(path, combos, meta):
    with open(path, "w", encoding="utf-8") as f:
        f.write("# llama-server Throughput Sweep\n\n")
        for k in sorted(meta):
            f.write("- %s: `%s`\n" % (k, meta[k]))
        f.write("\n")
        f.write("| parallel | batch | ubatch | prompt_words | concurrency | repeats | ok | errors | wall_s | agg_prompt_tok_s | agg_gen_tok_s |\n")
        f.write("| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n")
        for c in combos:
            f.write(
                "| %s | %s | %s | %s | %s | %s | %s | %s | %.6f | %s | %s |\n"
                % (
                    c.get("parallel", "NA"),
                    c.get("batch", "NA"),
                    c.get("ubatch", "NA"),
                    c.get("prompt_words", "NA"),
                    c.get("concurrency", "NA"),
                    c.get("repeats", "NA"),
                    c.get("ok_count", 0),
                    c.get("error_count", 0),
                    float(c.get("wave_wall_s", 0.0)),
                    "%.6f" % float(c["agg_prompt_tok_s"]) if c.get("agg_prompt_tok_s") is not None else "NA",
                    "%.6f" % float(c["agg_generated_tok_s"]) if c.get("agg_generated_tok_s") is not None else "NA",
                )
            )


def main():
    out_dir = os.environ.get("OUT_DIR", "/tmp/llamacpp_server_throughput_sweep")
    llama_server = env_str_b64("LLAMA_SERVER", "")
    model = env_str_b64("MODEL_GGUF", "")
    host = os.environ.get("HOST", "127.0.0.1")
    port = env_int("PORT", 18080)
    ctx = env_int("CTX", 8192)
    ngl = env_int("N_GPU_LAYERS", 99)
    n_predict = env_int("N_PREDICT", 32)
    repeats = env_int("REPEATS", 1)
    start_server = env_int("START_SERVER", 1)
    keep_server = env_int("KEEP_SERVER", 0)
    cache_prompt = env_int("CACHE_PROMPT", 0)
    scrape_metrics = env_int("SCRAPE_METRICS", 0)
    metrics_timeout_s = env_float("METRICS_TIMEOUT_S", 20.0)
    wait_timeout_s = env_float("WAIT_TIMEOUT_S", 1200.0)
    poll_s = env_float("POLL_S", 5.0)
    per_request_timeout_s = env_float("REQUEST_TIMEOUT_S", max(180.0, float(ctx) / 10.0))

    prompt_sizes = split_ints(os.environ.get("PROMPT_WORDS", "4096"))
    conc_values = split_ints(os.environ.get("CONCURRENCY", "1 2 4"))
    parallel_values = split_opt_ints(os.environ.get("PARALLEL_VALUES", "1 2"))
    batch_values = split_opt_ints(os.environ.get("BATCH_VALUES", ""))
    ubatch_values = split_opt_ints(os.environ.get("UBATCH_VALUES", ""))

    base_args = env_str_b64("SERVER_ARGS", "")
    parallel_flag = os.environ.get("PARALLEL_FLAG", "--parallel").strip()
    batch_flag = os.environ.get("BATCH_FLAG", "-b").strip()
    ubatch_flag = os.environ.get("UBATCH_FLAG", "-ub").strip()

    restart_per_combo = env_int("RESTART_PER_COMBO", 1)
    restart_sleep_s = env_float("RESTART_SLEEP_S", 1.0)

    os.makedirs(out_dir, exist_ok=True)
    base_url = "http://%s:%d" % (host, port)

    results_path = os.path.join(out_dir, "throughput_sweep.jsonl")
    summary_path = os.path.join(out_dir, "throughput_sweep.md")
    best_path = os.path.join(out_dir, "throughput_best.json")
    metrics_start_path = os.path.join(out_dir, "metrics_start.prom")
    metrics_end_path = os.path.join(out_dir, "metrics_end.prom")

    meta = {
        "base_url": base_url,
        "ctx": ctx,
        "n_predict": n_predict,
        "repeats": repeats,
        "cache_prompt": cache_prompt,
        "scrape_metrics": scrape_metrics,
        "prompt_words": " ".join(str(x) for x in prompt_sizes),
        "concurrency": " ".join(str(x) for x in conc_values),
        "parallel_values": " ".join(str(x) for x in parallel_values),
        "batch_values": " ".join(str(x) for x in batch_values),
        "ubatch_values": " ".join(str(x) for x in ubatch_values),
        "parallel_flag": parallel_flag,
        "batch_flag": batch_flag,
        "ubatch_flag": ubatch_flag,
        "restart_per_combo": restart_per_combo,
        "started_server": start_server,
        "keep_server": keep_server,
        "out_dir": out_dir,
    }

    def start_one_server(server_cmd, server_log, combo_dir):
        log_fp = open(server_log, "wb")
        proc = subprocess.Popen(server_cmd, stdout=log_fp, stderr=subprocess.STDOUT, preexec_fn=os.setsid)
        with open(os.path.join(combo_dir, "server.pid"), "w", encoding="utf-8") as f:
            f.write(str(proc.pid) + "\n")
        with open(os.path.join(combo_dir, "server.cmd.json"), "w", encoding="utf-8") as f:
            json.dump(server_cmd, f, indent=2)
        return proc, log_fp

    combos_out = []
    best = None

    def stop_server(proc, log_fp):
        if log_fp is not None:
            try:
                log_fp.flush()
            except Exception:
                pass
        if proc is not None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if log_fp is not None:
            try:
                log_fp.close()
            except Exception:
                pass

    def score_row(row):
        # Prefer max aggregate prompt throughput first; break ties with gen throughput.
        try:
            p = float(row.get("agg_prompt_tok_s") or 0.0)
        except Exception:
            p = 0.0
        try:
            g = float(row.get("agg_generated_tok_s") or 0.0)
        except Exception:
            g = 0.0
        return (p, g)

    if start_server != 0:
        if not llama_server or not model:
            raise SystemExit("LLAMA_SERVER and MODEL_GGUF are required when START_SERVER=1")

    if restart_per_combo == 0 and (len(parallel_values) > 1 or len(batch_values) > 1 or len(ubatch_values) > 1):
        raise SystemExit("RESTART_PER_COMBO=0 only supports a single (parallel,batch,ubatch) combo")

    if not parallel_values:
        parallel_values = [None]
    if not batch_values:
        batch_values = [None]
    if not ubatch_values:
        ubatch_values = [None]

    global_server_proc = None
    global_server_log = None
    global_server_log_fp = None
    global_combo_dir = out_dir

    try:
        with open(results_path, "w", encoding="utf-8") as rf:
            for pval in parallel_values:
                for bval in batch_values:
                    for ubval in ubatch_values:
                        combo_name = "p%s_b%s_ub%s" % (
                            str(pval) if pval is not None else "NA",
                            str(bval) if bval is not None else "NA",
                            str(ubval) if ubval is not None else "NA",
                        )
                        combo_dir = os.path.join(out_dir, combo_name)
                        os.makedirs(combo_dir, exist_ok=True)
                        server_log = os.path.join(combo_dir, "llama_server.log")
                        fattn_probe_path = os.path.join(combo_dir, "fattn_reservation_probe.json")
                        multislot_probe_path = os.path.join(combo_dir, "multislot_reservation_probe.json")

                        proc = None
                        log_fp = None
                        server_args = build_server_args(base_args, parallel_flag, pval, batch_flag, bval, ubatch_flag, ubval)

                        if start_server != 0:
                            if restart_per_combo != 0 or global_server_proc is None:
                                if global_server_proc is not None:
                                    stop_server(global_server_proc, global_server_log_fp)
                                    global_server_proc = None
                                    global_server_log_fp = None
                                    time.sleep(max(0.0, float(restart_sleep_s)))
                                cmd = [
                                    llama_server,
                                    "-m",
                                    model,
                                    "-c",
                                    str(ctx),
                                    "-ngl",
                                    str(ngl),
                                    "--host",
                                    host,
                                    "--port",
                                    str(port),
                                    "--perf",
                                ] + server_args
                                proc, log_fp = start_one_server(cmd, server_log, combo_dir)
                                global_server_proc = proc
                                global_server_log_fp = log_fp
                                global_server_log = server_log
                                global_combo_dir = combo_dir
                            else:
                                proc = global_server_proc
                                log_fp = global_server_log_fp
                                server_log = global_server_log
                                combo_dir = global_combo_dir

                        combo_meta = {
                            "combo": combo_name,
                            "parallel": pval if pval is not None else "NA",
                            "batch": bval if bval is not None else "NA",
                            "ubatch": ubval if ubval is not None else "NA",
                            "server_args": " ".join(shlex.quote(x) for x in server_args),
                        }

                        try:
                            load_s, health = wait_health(base_url, wait_timeout_s, poll_s)
                            combo_meta["health_wait_s"] = "%.6f" % load_s
                            combo_meta["health"] = json.dumps(health, sort_keys=True)
                            if scrape_metrics != 0 and os.path.exists(combo_dir):
                                try:
                                    txt = http_text("GET", base_url + "/metrics", None, timeout=metrics_timeout_s)
                                    with open(os.path.join(combo_dir, "metrics_start.prom"), "w", encoding="utf-8") as f:
                                        f.write(txt)
                                except Exception:
                                    pass
                            for prompt_words in prompt_sizes:
                                for conc in conc_values:
                                    rows = run_wave(
                                        base_url,
                                        prompt_words,
                                        n_predict,
                                        cache_prompt,
                                        conc,
                                        repeats,
                                        per_request_timeout_s,
                                    )
                                    for row in rows:
                                        row["combo"] = combo_name
                                        row["parallel"] = combo_meta["parallel"]
                                        row["batch"] = combo_meta["batch"]
                                        row["ubatch"] = combo_meta["ubatch"]
                                        row["server_args"] = combo_meta["server_args"]
                                        row["repeats"] = repeats
                                        rf.write(json.dumps(row, sort_keys=True) + "\n")
                                        rf.flush()
                                        combos_out.append(row)
                                        if best is None or score_row(row) > score_row(best):
                                            best = row
                                        print(json.dumps(row, sort_keys=True), flush=True)
                            if scrape_metrics != 0 and os.path.exists(combo_dir):
                                try:
                                    txt = http_text("GET", base_url + "/metrics", None, timeout=metrics_timeout_s)
                                    with open(os.path.join(combo_dir, "metrics_end.prom"), "w", encoding="utf-8") as f:
                                        f.write(txt)
                                except Exception:
                                    pass
                        except Exception as e:
                            err_row = {
                                "combo": combo_name,
                                "parallel": combo_meta["parallel"],
                                "batch": combo_meta["batch"],
                                "ubatch": combo_meta["ubatch"],
                                "prompt_words": "NA",
                                "concurrency": "NA",
                                "status": "error",
                                "error": str(e),
                                "server_args": combo_meta["server_args"],
                                "repeats": repeats,
                            }
                            rf.write(json.dumps(err_row, sort_keys=True) + "\n")
                            rf.flush()
                            combos_out.append(err_row)
                            print(json.dumps(err_row, sort_keys=True), flush=True)
                        try:
                            fattn = scan_fattn_reservation(server_log)
                            with open(fattn_probe_path, "w", encoding="utf-8") as pf:
                                json.dump(fattn, pf, indent=2, sort_keys=True)
                        except Exception:
                            pass
                        try:
                            ms = scan_multislot_reservation(server_log)
                            with open(multislot_probe_path, "w", encoding="utf-8") as pf:
                                json.dump(ms, pf, indent=2, sort_keys=True)
                        except Exception:
                            pass
                        if start_server != 0 and restart_per_combo != 0:
                            stop_server(proc, log_fp)
                            if proc is global_server_proc:
                                global_server_proc = None
                                global_server_log_fp = None
                                global_server_log = None
                            time.sleep(max(0.0, float(restart_sleep_s)))
        if best is not None:
            try:
                with open(best_path, "w", encoding="utf-8") as bf:
                    json.dump(best, bf, indent=2, sort_keys=True)
                meta["best_json"] = best_path
            except Exception:
                pass
        write_summary(summary_path, combos_out, meta)
        print("summary=" + summary_path)
        print("results=" + results_path)
        if best is not None:
            print("best=" + best_path)
        return 0
    finally:
        if start_server != 0:
            stop_server(global_server_proc, global_server_log_fp)


if __name__ == "__main__":
    sys.exit(main())
