#!/usr/bin/env python3
"""Resident llama-server prompt-size sweep for Spark-style hosts."""

import hashlib
import json
import os
import shlex
import signal
import subprocess
import sys
import time
import urllib.error

from scripts._lib.llamacpp_server import env_float
from scripts._lib.llamacpp_server import env_int
from scripts._lib.llamacpp_server import env_str_b64
from scripts._lib.llamacpp_server import extract_timings
from scripts._lib.llamacpp_server import http_json
from scripts._lib.llamacpp_server import http_text
from scripts._lib.llamacpp_server import make_prompt
from scripts._lib.llamacpp_server import metrics_delta_from_prom
from scripts._lib.llamacpp_server import scan_fattn_reservation
from scripts._lib.llamacpp_server import split_ints
from scripts._lib.llamacpp_server import wait_health


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
