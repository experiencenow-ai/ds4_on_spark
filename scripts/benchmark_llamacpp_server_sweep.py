#!/usr/bin/env python3
"""Resident llama-server prompt-size sweep for Spark-style hosts."""

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


def parse_prom_text(txt):
    # Minimal Prometheus text format parser.
    # Returns: series dict(key -> float)
    series = {}
    if not isinstance(txt, str) or not txt:
        return series

    def parse_labels(s):
        out = {}
        i = 0
        n = len(s)
        while i < n:
            while i < n and (s[i].isspace() or s[i] == ","):
                i += 1
            if i >= n:
                break
            k0 = i
            while i < n and s[i] != "=":
                i += 1
            key = s[k0:i].strip()
            if not key or i >= n or s[i] != "=":
                break
            i += 1
            if i >= n or s[i] != '"':
                break
            i += 1
            val = []
            while i < n:
                ch = s[i]
                if ch == "\\":
                    if i + 1 < n:
                        val.append(s[i + 1])
                        i += 2
                        continue
                if ch == '"':
                    i += 1
                    break
                val.append(ch)
                i += 1
            out[key] = "".join(val)
            while i < n and (not s[i].isspace()) and s[i] != ",":
                i += 1
            if i < n and s[i] == ",":
                i += 1
        return out

    for raw in txt.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name = ""
        labels = {}
        value_s = ""
        if "{" in line and "}" in line:
            try:
                name, rest = line.split("{", 1)
                labels_s, value_s = rest.split("}", 1)
                name = name.strip()
                labels = parse_labels(labels_s)
                value_s = value_s.strip()
            except ValueError:
                continue
        else:
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            name, value_s = parts[0].strip(), parts[1].strip()
        if not name:
            continue
        value_parts = value_s.split()
        if not value_parts:
            continue
        try:
            v = float(value_parts[0])
        except ValueError:
            continue
        if v != v:
            continue
        if labels:
            key = name + "{" + ",".join(
                ["%s=\"%s\"" % (k, labels[k].replace("\\", "\\\\").replace('"', "\\\"")) for k in sorted(labels)]
            ) + "}"
        else:
            key = name
        series[key] = v
    return series


def metrics_delta_from_prom(start_txt, end_txt, top_n=25):
    s0 = parse_prom_text(start_txt)
    s1 = parse_prom_text(end_txt)
    keys = set(s0.keys()) | set(s1.keys())
    deltas = []
    metric_sum = {}
    metric_series = {}
    for k in keys:
        v0 = float(s0.get(k, 0.0) or 0.0)
        v1 = float(s1.get(k, 0.0) or 0.0)
        d = v1 - v0
        if d == 0.0:
            continue
        name = k.split("{", 1)[0]
        metric_sum[name] = metric_sum.get(name, 0.0) + d
        metric_series[name] = metric_series.get(name, 0) + 1
        deltas.append({"series": k, "name": name, "start": v0, "end": v1, "delta": d})
    deltas.sort(key=lambda x: (-abs(float(x.get("delta") or 0.0)), x.get("series", "")))
    top_series = deltas[: int(top_n)]
    top_metrics = []
    for name, dsum in metric_sum.items():
        top_metrics.append({"name": name, "delta_sum": dsum, "series_count": metric_series.get(name, 0)})
    top_metrics.sort(key=lambda x: (-abs(float(x.get("delta_sum") or 0.0)), x.get("name", "")))
    return {
        "start_series": len(s0),
        "end_series": len(s1),
        "nonzero_series": len(deltas),
        "nonzero_metrics": len(metric_sum),
        "top_series_by_abs_delta": top_series,
        "top_metrics_by_abs_delta_sum": top_metrics[: int(top_n)],
    }


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


def nested_get(d, *names):
    cur = d
    for name in names:
        if not isinstance(cur, dict) or name not in cur:
            return None
        cur = cur[name]
    return cur


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


def write_summary(path, rows, meta):
    with open(path, "w", encoding="utf-8") as f:
        f.write("# llama-server Prompt Sweep\n\n")
        for k in sorted(meta):
            f.write("- %s: `%s`\n" % (k, meta[k]))
        f.write("\n")
        f.write("| target_words | repeat | prompt_tokens | cached | wall_s | prompt_tok_s | generation_tok_s | status |\n")
        f.write("| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |\n")
        for r in rows:
            t = r.get("timings", {})
            f.write(
                "| %s | %s | %s | %s | %.6f | %s | %s | %s |\n"
                % (
                    r.get("target_words", "NA"),
                    r.get("repeat_index", 0),
                    t.get("prompt_n", "NA"),
                    t.get("tokens_cached", "NA"),
                    float(r.get("wall_s", 0.0)),
                    "%.6f" % float(t["prompt_per_second"]) if t.get("prompt_per_second") is not None else "NA",
                    "%.6f" % float(t["predicted_per_second"]) if t.get("predicted_per_second") is not None else "NA",
                    r.get("status", "NA"),
                )
            )


def scan_fattn_reservation(log_path):
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


def main():
    out_dir = os.environ.get("OUT_DIR", "/tmp/llamacpp_server_sweep")
    llama_server = env_str_b64("LLAMA_SERVER", "")
    model = env_str_b64("MODEL_GGUF", "")
    host = os.environ.get("HOST", "127.0.0.1")
    port = env_int("PORT", 18080)
    ctx = env_int("CTX", 8192)
    ngl = env_int("N_GPU_LAYERS", 99)
    n_predict = env_int("N_PREDICT", 8)
    repeats = env_int("REPEATS", 1)
    start_server = env_int("START_SERVER", 1)
    keep_server = env_int("KEEP_SERVER", 0)
    cache_prompt = env_int("CACHE_PROMPT", 0)
    scrape_metrics = env_int("SCRAPE_METRICS", 0)
    metrics_timeout_s = env_float("METRICS_TIMEOUT_S", 20.0)
    wait_timeout_s = env_float("WAIT_TIMEOUT_S", 1200.0)
    poll_s = env_float("POLL_S", 5.0)
    prompt_sizes = split_ints(os.environ.get("PROMPT_WORDS", "256 1024 4096"))
    extra = env_str_b64("SERVER_ARGS", "")
    os.makedirs(out_dir, exist_ok=True)
    base_url = "http://%s:%d" % (host, port)
    server_log = os.path.join(out_dir, "llama_server.log")
    results_path = os.path.join(out_dir, "server_sweep.jsonl")
    summary_path = os.path.join(out_dir, "server_sweep.md")
    proc = None
    log_fp = None
    fattn_probe_path = os.path.join(out_dir, "fattn_reservation_probe.json")
    metrics_start_path = os.path.join(out_dir, "metrics_start.prom")
    metrics_end_path = os.path.join(out_dir, "metrics_end.prom")
    if start_server != 0:
        if not llama_server or not model:
            raise SystemExit("LLAMA_SERVER and MODEL_GGUF are required when START_SERVER=1")
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
        ]
        if extra.strip():
            cmd.extend(shlex.split(extra))
        log_fp = open(server_log, "wb")
        proc = subprocess.Popen(cmd, stdout=log_fp, stderr=subprocess.STDOUT, preexec_fn=os.setsid)
        with open(os.path.join(out_dir, "server.pid"), "w", encoding="utf-8") as f:
            f.write(str(proc.pid) + "\n")
        with open(os.path.join(out_dir, "server.cmd.json"), "w", encoding="utf-8") as f:
            json.dump(cmd, f, indent=2)
    rows = []
    meta = {
        "base_url": base_url,
        "ctx": ctx,
        "n_predict": n_predict,
        "repeats": repeats,
        "cache_prompt": cache_prompt,
        "scrape_metrics": scrape_metrics,
        "prompt_words": " ".join(str(x) for x in prompt_sizes),
        "started_server": start_server,
        "keep_server": keep_server,
        "out_dir": out_dir,
    }
    metrics_start_txt = None
    metrics_end_txt = None
    metrics_delta_json_path = os.path.join(out_dir, "metrics_delta.json")
    metrics_delta_md_path = os.path.join(out_dir, "metrics_delta.md")
    try:
        load_s, health = wait_health(base_url, wait_timeout_s, poll_s)
        meta["health_wait_s"] = "%.6f" % load_s
        meta["health"] = json.dumps(health, sort_keys=True)
        if scrape_metrics != 0:
            try:
                txt = http_text("GET", base_url + "/metrics", None, timeout=metrics_timeout_s)
                metrics_start_txt = txt
                with open(metrics_start_path, "w", encoding="utf-8") as f:
                    f.write(txt)
                meta["metrics_start_prom"] = metrics_start_path
            except Exception as e:
                meta["metrics_start_prom"] = "error:" + str(e)
        with open(results_path, "w", encoding="utf-8") as rf:
            for target_words in prompt_sizes:
                prompt = make_prompt(target_words)
                for repeat_index in range(repeats):
                    payload = {
                        "prompt": prompt,
                        "n_predict": n_predict,
                        "cache_prompt": bool(cache_prompt),
                        "temperature": 0,
                    }
                    row = {
                        "target_words": target_words,
                        "repeat_index": repeat_index,
                        "prompt_chars": len(prompt.encode("utf-8")),
                        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                        "status": "ok",
                    }
                    start = time.monotonic()
                    try:
                        data = http_json("POST", base_url + "/completion", payload, timeout=max(120.0, float(ctx)))
                        row["wall_s"] = time.monotonic() - start
                        row["timings"] = extract_timings(data if isinstance(data, dict) else {})
                        row["response_keys"] = sorted(data.keys()) if isinstance(data, dict) else []
                    except urllib.error.HTTPError as e:
                        row["wall_s"] = time.monotonic() - start
                        row["status"] = "http_error"
                        row["error"] = e.read().decode("utf-8", errors="replace")
                        row["code"] = e.code
                    except Exception as e:
                        row["wall_s"] = time.monotonic() - start
                        row["status"] = "error"
                        row["error"] = str(e)
                    rows.append(row)
                    rf.write(json.dumps(row, sort_keys=True) + "\n")
                    rf.flush()
                    print(json.dumps(row, sort_keys=True), flush=True)
        if scrape_metrics != 0:
            try:
                txt = http_text("GET", base_url + "/metrics", None, timeout=metrics_timeout_s)
                metrics_end_txt = txt
                with open(metrics_end_path, "w", encoding="utf-8") as f:
                    f.write(txt)
                meta["metrics_end_prom"] = metrics_end_path
            except Exception as e:
                meta["metrics_end_prom"] = "error:" + str(e)
        if scrape_metrics != 0 and metrics_start_txt is not None and metrics_end_txt is not None:
            try:
                delta = metrics_delta_from_prom(metrics_start_txt, metrics_end_txt, top_n=25)
                with open(metrics_delta_json_path, "w", encoding="utf-8") as f:
                    json.dump(delta, f, indent=2, sort_keys=True)
                with open(metrics_delta_md_path, "w", encoding="utf-8") as f:
                    f.write("# llama-server /metrics Delta (best-effort)\n\n")
                    f.write("- start_series: `%s`\n" % str(delta.get("start_series", "NA")))
                    f.write("- end_series: `%s`\n" % str(delta.get("end_series", "NA")))
                    f.write("- nonzero_series: `%s`\n" % str(delta.get("nonzero_series", "NA")))
                    f.write("- nonzero_metrics: `%s`\n" % str(delta.get("nonzero_metrics", "NA")))
                    f.write("\n")
                    f.write("## Top metrics (by abs delta sum)\n\n")
                    f.write("| metric | delta_sum | series |\n")
                    f.write("| --- | ---: | ---: |\n")
                    for row in delta.get("top_metrics_by_abs_delta_sum") or []:
                        f.write(
                            "| %s | %.6g | %d |\n"
                            % (row.get("name", "NA"), float(row.get("delta_sum") or 0.0), int(row.get("series_count") or 0))
                        )
                    f.write("\n")
                    f.write("## Top series (by abs delta)\n\n")
                    f.write("| series | delta | start | end |\n")
                    f.write("| --- | ---: | ---: | ---: |\n")
                    for row in delta.get("top_series_by_abs_delta") or []:
                        f.write(
                            "| %s | %.6g | %.6g | %.6g |\n"
                            % (
                                row.get("series", "NA").replace("|", "\\|"),
                                float(row.get("delta") or 0.0),
                                float(row.get("start") or 0.0),
                                float(row.get("end") or 0.0),
                            )
                        )
                meta["metrics_delta_json"] = metrics_delta_json_path
                meta["metrics_delta_md"] = metrics_delta_md_path
                meta["metrics_delta_nonzero_series"] = str(delta.get("nonzero_series", "NA"))
                meta["metrics_delta_nonzero_metrics"] = str(delta.get("nonzero_metrics", "NA"))
            except Exception as e:
                meta["metrics_delta_json"] = "error:" + str(e)
        if log_fp is not None:
            try:
                log_fp.flush()
            except Exception:
                pass
        fattn = scan_fattn_reservation(server_log)
        try:
            with open(fattn_probe_path, "w", encoding="utf-8") as pf:
                json.dump(fattn, pf, indent=2, sort_keys=True)
        except Exception:
            pass
        meta["fattn_seen_disabled"] = str(bool(fattn.get("seen_fattn_disabled")))
        meta["fattn_seen_sched_reserve_cpu"] = str(bool(fattn.get("seen_sched_reserve_cpu_fattn")))
        meta["fattn_line_count"] = str(int(fattn.get("fattn_line_count") or 0))
        meta["fattn_node_unique"] = str(int(fattn.get("fattn_node_unique") or 0))
        meta["fattn_id_min"] = str(fattn.get("fattn_id_min") if fattn.get("fattn_id_min") is not None else "NA")
        meta["fattn_id_max"] = str(fattn.get("fattn_id_max") if fattn.get("fattn_id_max") is not None else "NA")
        meta["fattn_id_span"] = str(fattn.get("fattn_id_span") if fattn.get("fattn_id_span") is not None else "NA")
        meta["fattn_id_missing_count"] = str(
            fattn.get("fattn_id_missing_count") if fattn.get("fattn_id_missing_count") is not None else "NA"
        )
        meta["fattn_expected_id_0_42_ok"] = str(
            fattn.get("fattn_expected_id_0_42_ok") if fattn.get("fattn_expected_id_0_42_ok") is not None else "NA"
        )
        meta["fattn_backend_unique"] = str(int(fattn.get("fattn_backend_unique") or 0))
        meta["fattn_backend0_only"] = str(bool(fattn.get("fattn_backend0_only")))
        meta["fattn_expected_backend0_ok"] = str(
            fattn.get("fattn_expected_backend0_ok") if fattn.get("fattn_expected_backend0_ok") is not None else "NA"
        )
        meta["fattn_backend_counts"] = json.dumps(fattn.get("fattn_backend_counts") or {}, sort_keys=True)
        meta["fattn_cuda_device_unique"] = str(int(fattn.get("fattn_cuda_device_unique") or 0))
        meta["fattn_cuda_device0_only"] = str(bool(fattn.get("fattn_cuda_device0_only")))
        meta["fattn_expected_cuda_device0_ok"] = str(
            fattn.get("fattn_expected_cuda_device0_ok")
            if fattn.get("fattn_expected_cuda_device0_ok") is not None
            else "NA"
        )
        meta["fattn_cuda_device_counts"] = json.dumps(fattn.get("fattn_cuda_device_counts") or {}, sort_keys=True)
        meta["sched_reserve_line_count"] = str(int(fattn.get("sched_reserve_line_count") or 0))
        meta["sched_reserve_graph_nodes"] = str(fattn.get("sched_reserve_graph_nodes") or "NA")
        meta["sched_reserve_graph_splits"] = str(fattn.get("sched_reserve_graph_splits") or "NA")
        meta["sched_reserve_took_ms"] = str(fattn.get("sched_reserve_took_ms") or "NA")
        meta["node_kind_unique"] = str(int(fattn.get("node_kind_unique") or 0))
        meta["node_kind_cpu_top"] = json.dumps(fattn.get("node_kind_cpu_top") or [], sort_keys=True)
        meta["node_kind_cuda_top"] = json.dumps(fattn.get("node_kind_cuda_top") or [], sort_keys=True)
        meta["fattn_probe_json"] = fattn_probe_path
        write_summary(summary_path, rows, meta)
        print("summary=" + summary_path)
        print("results=" + results_path)
        print("server_log=" + server_log)
        print("fattn_probe=" + fattn_probe_path)
        return 0
    finally:
        if proc is not None and keep_server == 0:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if log_fp is not None:
            try:
                log_fp.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
