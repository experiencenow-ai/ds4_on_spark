from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.request
from typing import Any


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


def parse_prom_text(txt):
	series = {}
	if not isinstance(txt, str) or not txt:
		return series
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
				labels = parse_prom_labels(labels_s)
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
			key = name + "{" + ",".join(["%s=\"%s\"" % (k, labels[k].replace("\\", "\\\\").replace('"', "\\\"")) for k in sorted(labels)]) + "}"
		else:
			key = name
		series[key] = v
	return series


def parse_prom_labels(s):
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
	top_metrics = []
	for name, dsum in metric_sum.items():
		top_metrics.append({"name": name, "delta_sum": dsum, "series_count": metric_series.get(name, 0)})
	top_metrics.sort(key=lambda x: (-abs(float(x.get("delta_sum") or 0.0)), x.get("name", "")))
	return {
		"start_series": len(s0),
		"end_series": len(s1),
		"nonzero_series": len(deltas),
		"nonzero_metrics": len(metric_sum),
		"top_series_by_abs_delta": deltas[: int(top_n)],
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
	stem = ["Spark", "quantized", "DeepSeek", "routing", "prefill", "latency", "expert", "cache"]
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


def scan_fattn_reservation(log_path, *, match_limit=50, include_node_samples=True, op_kind_format=False, include_sched_reserve_match=False):
	out = _empty_fattn_probe(log_path)
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
				_scan_fattn_line(
					line.rstrip("\n"),
					out,
					nodes,
					fattn_ids,
					fattn_backend,
					fattn_cuda_dev,
					kind_nodes,
					kind_cpu,
					kind_cuda,
					match_lines,
					rx_fattn_disabled,
					rx_sched_reserve_fallback,
					rx_sched_reserve_failure,
					match_limit,
					op_kind_format,
					include_sched_reserve_match,
				)
	except Exception:
		pass
	_finish_fattn_probe(out, nodes, fattn_ids, fattn_backend, fattn_cuda_dev, kind_nodes, kind_cpu, kind_cuda, match_lines, include_node_samples)
	return out


def _empty_fattn_probe(log_path):
	return {
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


def _scan_fattn_line(ln, out, nodes, fattn_ids, fattn_backend, fattn_cuda_dev, kind_nodes, kind_cpu, kind_cuda, match_lines, rx_fattn_disabled, rx_sched_reserve_fallback, rx_sched_reserve_failure, match_limit, op_kind_format, include_sched_reserve_match):
	is_match = False
	if ln.startswith("sched_reserve:"):
		is_match = _scan_sched_reserve(ln, out, rx_sched_reserve_fallback, rx_sched_reserve_failure) or is_match
		if include_sched_reserve_match:
			is_match = True
	if rx_fattn_disabled.search(ln) is not None:
		out["seen_fattn_disabled"] = True
		is_match = True
	if "Flash Attention tensor is assigned to device CPU" in ln:
		out["seen_sched_reserve_cpu_fattn"] = True
		is_match = True
	if "__fattn__" in ln:
		_scan_fattn_token(ln, out, nodes, fattn_ids, fattn_backend, fattn_cuda_dev)
		is_match = True
	if _scan_kind_tokens(ln, kind_nodes, kind_cpu, kind_cuda, op_kind_format):
		is_match = True
	if is_match and len(match_lines) < int(match_limit):
		match_lines.append(ln[:4000] if include_node_samples else ln)


def _scan_sched_reserve(ln, out, rx_sched_reserve_fallback, rx_sched_reserve_failure):
	is_match = False
	if rx_sched_reserve_fallback.search(ln) is not None:
		out["seen_sched_reserve_fallback"] = True
		out["sched_reserve_fallback_line_count"] += 1
		is_match = True
	if rx_sched_reserve_failure.search(ln) is not None:
		out["seen_sched_reserve_failure"] = True
		out["sched_reserve_failure_line_count"] += 1
		is_match = True
	for key, pattern, cast in (
		("sched_reserve_graph_nodes", r"graph nodes\s*=\s*(\d+)", int),
		("sched_reserve_graph_splits", r"graph splits\s*=\s*(\d+)", int),
		("sched_reserve_took_ms", r"reserve took\s*([0-9]+(?:\.[0-9]+)?)\s*ms", float),
	):
		m = re.search(pattern, ln)
		if m is not None:
			try:
				out[key] = cast(m.group(1))
			except ValueError:
				pass
	out["sched_reserve_line_count"] += 1
	return is_match


def _scan_fattn_token(ln, out, nodes, fattn_ids, fattn_backend, fattn_cuda_dev):
	low = ln.lower()
	if "fallback" in low or "fall back" in low:
		out["seen_sched_reserve_fallback"] = True
		out["sched_reserve_fallback_line_count"] += 1
	out["fattn_line_count"] += 1
	for m in re.finditer(r"__fattn__-(\d+)", ln):
		nodes.add("__fattn__-" + m.group(1))
		try:
			fattn_ids.add(int(m.group(1)))
		except ValueError:
			pass
	m = re.search(r"(?:cuda\s+backend|backend)\s*(?:=|:)?\s*([0-9]+)", ln, flags=re.IGNORECASE)
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


def _scan_kind_tokens(ln, kind_nodes, kind_cpu, kind_cuda, op_kind_format):
	matches = list(re.finditer(r"__op__-([^\s:]+)", ln)) if op_kind_format and "__op__" in ln else list(re.finditer(r"(__[A-Za-z0-9_]+__)-\d+", ln))
	for m in matches:
		kind = m.group(1)
		kind_nodes.add(kind)
		low = ln.lower()
		if "cpu" in low:
			kind_cpu[kind] = kind_cpu.get(kind, 0) + 1
		if "cuda" in low:
			kind_cuda[kind] = kind_cuda.get(kind, 0) + 1
	return bool(matches)


def _finish_fattn_probe(out, nodes, fattn_ids, fattn_backend, fattn_cuda_dev, kind_nodes, kind_cpu, kind_cuda, match_lines, include_node_samples):
	out["fattn_node_unique"] = len(nodes)
	out["match_lines"] = match_lines
	if include_node_samples:
		out["fattn_nodes_sample"] = sorted(nodes)[:50]
		out["node_kinds_sample"] = sorted(kind_nodes)[:50]
	out["node_kind_unique"] = len(kind_nodes)
	out["node_kind_cpu_top"] = sorted(kind_cpu.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
	out["node_kind_cuda_top"] = sorted(kind_cuda.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
	if fattn_ids:
		ids = sorted(fattn_ids)
		out["fattn_id_min"] = ids[0]
		out["fattn_id_max"] = ids[-1]
		out["fattn_id_span"] = int(ids[-1] - ids[0] + 1)
		have = set(fattn_ids)
		out["fattn_id_missing_count"] = sum(1 for i in range(ids[0], ids[-1] + 1) if i not in have)
		out["fattn_expected_id_0_42_ok"] = ids[0] == 0 and ids[-1] >= 42 and out["fattn_id_missing_count"] == 0
	out["fattn_backend_counts"] = {str(k): int(v) for (k, v) in sorted(fattn_backend.items(), key=lambda kv: kv[0])}
	out["fattn_backend_unique"] = len(fattn_backend)
	out["fattn_backend0_only"] = len(fattn_backend) == 1 and 0 in fattn_backend and len(fattn_ids) > 0
	if out["fattn_backend_unique"] > 0:
		out["fattn_expected_backend0_ok"] = bool(out["fattn_backend0_only"])
	out["fattn_cuda_device_counts"] = {str(k): int(v) for (k, v) in sorted(fattn_cuda_dev.items(), key=lambda kv: kv[0])}
	out["fattn_cuda_device_unique"] = len(fattn_cuda_dev)
	out["fattn_cuda_device0_only"] = len(fattn_cuda_dev) == 1 and 0 in fattn_cuda_dev and len(fattn_ids) > 0
	if out["fattn_cuda_device_unique"] > 0:
		out["fattn_expected_cuda_device0_ok"] = bool(out["fattn_cuda_device0_only"])
