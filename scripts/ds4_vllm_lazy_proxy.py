#!/usr/bin/env python3
import concurrent.futures
import hashlib
import http.client
import json
import os
import fnmatch
import re
import signal
import shlex
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

TUNING_KEYS = (
    "max_model_len",
    "max_num_seqs",
    "max_num_batched_tokens",
    "gpu_memory_utilization",
    "enable_chunked_prefill",
    "enable_prefix_caching",
    "async_scheduling",
    "kv_cache_dtype",
    "reasoning_parser",
    "tool_call_parser",
    "attention_backend",
    "enable_auto_tool_choice",
    "speculative_config",
    "extra_args",
)


class VllmError(Exception):
    pass


class CpuServiceError(Exception):
    pass


def env_int(name, default):
    value = os.environ.get(name)
    if value in (None, ""):
        return(default)
    return(int(value))


def now():
    return(time.time())


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return(json.load(f))


def env_json(name, default):
    value = os.environ.get(name)
    if value in (None, ""):
        return(default)
    return(json.loads(value))


def env_bool(name, default):
    value = os.environ.get(name)
    if value in (None, ""):
        return(default)
    return(str(value).strip().lower() not in ("0", "false", "no", "off"))


def expand_path(path):
    if path in (None, ""):
        return(path)
    return(os.path.expanduser(os.path.expandvars(str(path))))


def read_json_if_present(path):
    path = expand_path(path)
    if path in (None, "") or not os.path.exists(path):
        return({})
    return(read_json(path))


def merge_dicts(*items):
    out = {}
    for item in items:
        if isinstance(item, dict):
            out.update(item)
    return(out)


def json_arg(value):
    if isinstance(value, str):
        return(value)
    return(json.dumps(value, separators=(",", ":")))


def text_payload(item, max_bytes):
    if not isinstance(item, dict):
        raise CpuServiceError("CPU service item must be an object")
    if "text" in item:
        text = str(item.get("text", ""))
    elif "content" in item:
        text = str(item.get("content", ""))
    else:
        text = ""
    if len(text.encode("utf-8")) > max_bytes:
        raise CpuServiceError("text payload exceeds CPU_SERVICE_MAX_TEXT_BYTES=%d" % max_bytes)
    return(text)


def service_result(ok, response):
    out = dict(response)
    out["_ok"] = bool(ok)
    return(out)


def safe_text(value):
    if value is None:
        return("")
    if isinstance(value, bytes):
        return(value.decode("utf-8", "replace"))
    return(str(value))


def has_weight_file(files):
    for name in files:
        if name.endswith((".safetensors", ".bin", ".pt")):
            return(True)
    return(False)


def model_dirs(root):
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        hf = ("config.json" in filenames and "tokenizer_config.json" in filenames)
        mistral = ("params.json" in filenames and "tokenizer_config.json" in filenames)
        if not hf and not mistral:
            continue
        if not has_weight_file(filenames):
            if not any(has_weight_file(fs) for _, _, fs in os.walk(dirpath)):
                continue
        rel = os.path.relpath(dirpath, root)
        if rel == ".":
            continue
        cfg = {}
        try:
            cfg = read_json(os.path.join(dirpath, "config.json" if hf else "params.json"))
        except Exception:
            cfg = {}
        out[rel] = {
            "id": rel,
            "path": dirpath,
            "backend": "vllm_lazy_hf",
            "format": "hf" if hf else "mistral",
            "model_type": cfg.get("model_type") or ("mistral" if mistral else None),
            "architectures": cfg.get("architectures") or [],
            "max_model_len": cfg.get("max_position_embeddings") or cfg.get("max_seq_len"),
        }
        dirnames[:] = []
    return(out)


def safe_model_id(path):
    base = os.path.basename(path)
    if base.endswith(".gguf"):
        base = base[:-5]
    out = []
    prev_dash = False
    for ch in base:
        if ch.isalnum():
            out.append(ch.lower())
            prev_dash = False
        elif not prev_dash:
            out.append("-")
            prev_dash = True
    return("".join(out).strip("-") or "gguf")


def gguf_model_dirs(root):
    out = {}
    root = expand_path(root)
    if not root or not os.path.isdir(root):
        return(out)
    files = sorted(os.listdir(root))
    mtp = ""
    for name in files:
        lower = name.lower()
        if lower.endswith(".gguf") and "mtp" in lower:
            mtp = os.path.join(root, name)
            break
    backend = os.environ.get("GGUF_BACKEND", "ds4_server")
    for name in files:
        lower = name.lower()
        if not lower.endswith(".gguf") or "mtp" in lower:
            continue
        path = os.path.join(root, name)
        mid = "gguf/" + safe_model_id(path)
        if "deepseek-v4-flash" in lower or "deepseek_v4_flash" in lower:
            mid = "antirez/" + safe_model_id(path)
        rec = {
            "id": mid,
            "path": path,
            "backend": backend,
            "format": "gguf",
            "served_model": os.environ.get("GGUF_SERVED_MODEL", "deepseek-v4-flash"),
        }
        if mtp and os.environ.get("GGUF_DISABLE_MTP", "0") != "1":
            rec["mtp"] = mtp
        out[mid] = rec
    return(out)


def extra_model_dirs():
    out = {}
    raw = os.environ.get("DS4_GATEWAY_MODELS_JSON") or os.environ.get("DS4_LOCAL_MODELS_JSON")
    if not raw:
        return(out)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise VllmError("DS4_GATEWAY_MODELS_JSON must be an object")
    for mid, rec in data.items():
        if isinstance(rec, str):
            rec = {"path": rec}
        if not isinstance(rec, dict):
            raise VllmError("model spec for %s must be an object or path string" % mid)
        spec = dict(rec)
        spec["id"] = mid
        spec["path"] = expand_path(spec.get("path", ""))
        spec["backend"] = spec.get("backend", "llama_server" if spec.get("path", "").endswith(".gguf") else "vllm_lazy_hf")
        if spec.get("mtp"):
            spec["mtp"] = expand_path(spec.get("mtp"))
        out[mid] = spec
    return(out)


def unique_aliases(models):
    counts = {}
    for mid in models:
        base = mid.rsplit("/", 1)[-1]
        counts[base] = (counts.get(base, 0) + 1)
    aliases = {}
    for mid in models:
        base = mid.rsplit("/", 1)[-1]
        if counts[base] == 1:
            aliases[base] = mid
    extra = os.environ.get("DS4_MODEL_ALIASES_JSON")
    if extra:
        aliases.update(json.loads(extra))
    for mid, rec in models.items():
        for alias in rec.get("aliases") or []:
            aliases[alias] = mid
    antirez = sorted(mid for mid in models if mid.startswith("antirez/"))
    if antirez:
        preferred = next((mid for mid in antirez if "imatrix" not in mid), antirez[0])
        aliases.setdefault("antirez-deepseek-v4-flash", preferred)
        aliases.setdefault("ds4-antirez", preferred)
        aliases.setdefault("deepseek-v4-flash-gguf", preferred)
    return(aliases)


def remote_model_map(models):
    out = {}
    base = os.environ.get("DEEPSEEK_V4_REMOTE_BASE")
    if base:
        target = os.environ.get("DEEPSEEK_V4_REMOTE_MODEL", "deepseek-v4-flash")
        for mid, rec in models.items():
            arch = set(rec.get("architectures") or [])
            if rec.get("model_type") == "deepseek_v4" or "DeepseekV4ForCausalLM" in arch:
                out[mid] = {"base": base.rstrip("/"), "model": target}
    extra = os.environ.get("DS4_REMOTE_MODELS_JSON")
    if extra:
        out.update(json.loads(extra))
    return(out)


def parse_gpu_value(value):
    value = value.strip()
    if value in ("", "N/A", "[N/A]", "Not Supported"):
        return(None)
    try:
        if "." in value:
            return(float(value))
        return(int(value))
    except Exception:
        return(value)


def gpu_snapshot():
    fields = [
        "index",
        "name",
        "utilization.gpu",
        "utilization.memory",
        "memory.total",
        "memory.used",
        "power.draw",
        "clocks.sm",
        "pstate",
    ]
    cmd = [
        "nvidia-smi",
        "--query-gpu=" + ",".join(fields),
        "--format=csv,noheader,nounits",
    ]
    out = {
        "host": socket.gethostname(),
        "timestamp": int(time.time()),
        "available": False,
        "gpus": [],
    }
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
    except FileNotFoundError:
        out["error"] = "nvidia-smi not found"
        return(out)
    except Exception as e:
        out["error"] = str(e)
        return(out)
    if proc.returncode != 0:
        out["error"] = (proc.stderr or proc.stdout)[-1000:]
        return(out)
    for raw in proc.stdout.splitlines():
        cols = [x.strip() for x in raw.split(",")]
        if len(cols) < len(fields):
            continue
        rec = {fields[i].replace(".", "_"): parse_gpu_value(cols[i]) for i in range(len(fields))}
        util = rec.get("utilization_gpu")
        mem_util = rec.get("utilization_memory")
        rec["gpu_used_pct"] = util if isinstance(util, (int, float)) else None
        rec["memory_used_pct"] = mem_util if isinstance(mem_util, (int, float)) else None
        out["gpus"].append(rec)
    out["available"] = len(out["gpus"]) != 0
    return(out)


class CpuServices:
    def __init__(self):
        cores = os.cpu_count() or 4
        default_workers = min(16, max(1, cores - 4))
        self.workers = max(1, env_int("CPU_SERVICE_WORKERS", default_workers))
        self.max_items = env_int("CPU_SERVICE_MAX_ITEMS", 1024)
        self.max_concurrency = max(1, env_int("CPU_SERVICE_MAX_CONCURRENCY", self.workers))
        self.default_concurrency = min(self.max_concurrency, max(1, env_int("CPU_SERVICE_DEFAULT_CONCURRENCY", min(4, self.max_concurrency))))
        self.max_text_bytes = env_int("CPU_SERVICE_MAX_TEXT_BYTES", 1024 * 1024)
        self.command_timeout = float(os.environ.get("CPU_SERVICE_COMMAND_TIMEOUT", "120"))
        self.command_output_bytes = env_int("CPU_SERVICE_COMMAND_OUTPUT_BYTES", 65536)
        self.commands = env_json("CPU_SERVICE_COMMANDS_JSON", {})
        self.lock = threading.Lock()
        self.pending = 0
        self.active = 0
        self.completed = 0
        self.failed = 0
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="ds4-cpu")
        self.services = {
            "json_validate": {
                "fn": self.service_json_validate,
                "description": "parse JSON text or inspect JSON object payloads",
                "batchable": True,
            },
            "regex_match": {
                "fn": self.service_regex_match,
                "description": "run deterministic regex checks against bounded text",
                "batchable": True,
            },
            "sha256": {
                "fn": self.service_sha256,
                "description": "compute SHA-256 cache keys for bounded text",
                "batchable": True,
            },
            "text_metrics": {
                "fn": self.service_text_metrics,
                "description": "line, word, byte, approximate token, and hash metrics",
                "batchable": True,
            },
            "diff_stats": {
                "fn": self.service_diff_stats,
                "description": "summarize unified-diff additions, deletions, files, and EVOLVE-BLOCK markers",
                "batchable": True,
            },
            "command": {
                "fn": self.service_command,
                "description": "run named allowlisted local commands from CPU_SERVICE_COMMANDS_JSON",
                "batchable": True,
                "configured": sorted(self.commands),
            },
        }

    def status(self):
        with self.lock:
            queue = {
                "workers": self.workers,
                "pending": self.pending,
                "active": self.active,
                "completed": self.completed,
                "failed": self.failed,
                "max_items": self.max_items,
                "max_concurrency": self.max_concurrency,
                "default_concurrency": self.default_concurrency,
                "max_text_bytes": self.max_text_bytes,
            }
        services = {}
        for name, rec in sorted(self.services.items()):
            services[name] = {k: v for k, v in rec.items() if k != "fn"}
        return({"object": "ds4.cpu_services", "queue": queue, "services": services})

    def normalize_items(self, payload):
        items = payload.get("items")
        if items is None:
            items = payload.get("requests")
        if not isinstance(items, list):
            raise CpuServiceError("CPU batch body must contain items or requests array")
        if len(items) == 0:
            raise CpuServiceError("CPU batch must contain at least one item")
        if len(items) > self.max_items:
            raise CpuServiceError("CPU batch item count %d exceeds CPU_SERVICE_MAX_ITEMS=%d" % (len(items), self.max_items))
        return(items)

    def concurrency(self, payload):
        raw = payload.get("concurrency", self.default_concurrency)
        try:
            value = int(raw)
        except Exception:
            raise CpuServiceError("CPU batch concurrency must be an integer")
        if value < 1:
            raise CpuServiceError("CPU batch concurrency must be >= 1")
        if value > self.max_concurrency:
            raise CpuServiceError("CPU batch concurrency %d exceeds CPU_SERVICE_MAX_CONCURRENCY=%d" % (value, self.max_concurrency))
        return(value)

    def service_name(self, payload):
        name = str(payload.get("service", "") or "")
        if name not in self.services:
            raise CpuServiceError("unknown CPU service: %s" % name)
        return(name)

    def item_request(self, item):
        if not isinstance(item, dict):
            raise CpuServiceError("CPU service item must be an object")
        req = item.get("request")
        if req is None:
            req = item
        if not isinstance(req, dict):
            raise CpuServiceError("CPU service item request must be an object")
        return(dict(req))

    def run_one(self, service, idx, item, sem):
        custom_id = item.get("custom_id") if isinstance(item, dict) else None
        rec = {"index": idx, "custom_id": custom_id, "service": service, "ok": False}
        start = now()
        sem.acquire()
        with self.lock:
            self.pending -= 1
            self.active += 1
        try:
            req = self.item_request(item)
            for key in ("custom_id", "metadata", "request"):
                req.pop(key, None)
            out = self.services[service]["fn"](req)
            ok = bool(out.pop("_ok", True)) if isinstance(out, dict) else True
            rec.update({"ok": ok, "response": out})
        except Exception as e:
            rec["error"] = str(e)
        finally:
            sem.release()
            rec["elapsed_s"] = round(now() - start, 6)
            with self.lock:
                self.active -= 1
                self.completed += 1
                if not rec.get("ok"):
                    self.failed += 1
        return(idx, rec)

    def run_batch(self, service, items, concurrency, timeout):
        sem = threading.Semaphore(concurrency)
        with self.lock:
            self.pending += len(items)
        futs = [self.pool.submit(self.run_one, service, idx, item, sem) for idx, item in enumerate(items)]
        results = [None] * len(items)
        try:
            done_iter = concurrent.futures.as_completed(futs, timeout=timeout)
            for fut in done_iter:
                idx, rec = fut.result()
                results[idx] = rec
        except concurrent.futures.TimeoutError:
            for idx, fut in enumerate(futs):
                if results[idx] is None:
                    if fut.cancel():
                        with self.lock:
                            self.pending = max(0, self.pending - 1)
                    results[idx] = {"index": idx, "service": service, "ok": False, "error": "CPU batch timeout"}
        return(results)

    def service_json_validate(self, item):
        if "json" in item:
            obj = item.get("json")
        else:
            text = text_payload(item, self.max_text_bytes)
            try:
                obj = json.loads(text)
            except Exception as e:
                return({"valid": False, "error": str(e)})
        required = item.get("required_keys") or []
        missing = []
        if required:
            if not isinstance(obj, dict):
                missing = list(required)
            else:
                missing = [k for k in required if k not in obj]
        return({
            "valid": len(missing) == 0,
            "type": type(obj).__name__,
            "keys": sorted(obj) if isinstance(obj, dict) else [],
            "missing_keys": missing,
        })

    def service_regex_match(self, item):
        text = text_payload(item, self.max_text_bytes)
        pattern = str(item.get("pattern", ""))
        if pattern == "":
            raise CpuServiceError("regex_match requires pattern")
        flags = 0
        for flag in item.get("flags") or []:
            if flag == "i":
                flags |= re.IGNORECASE
            elif flag == "m":
                flags |= re.MULTILINE
            elif flag == "s":
                flags |= re.DOTALL
            else:
                raise CpuServiceError("unsupported regex flag: %s" % flag)
        rx = re.compile(pattern, flags)
        if item.get("fullmatch"):
            match = rx.fullmatch(text)
            matches = [match] if match else []
        else:
            matches = list(rx.finditer(text))
        limit = int(item.get("limit", 16))
        return({
            "matched": len(matches) != 0,
            "count": len(matches),
            "matches": [{"span": list(m.span()), "text": m.group(0), "groups": list(m.groups())} for m in matches[:limit]],
        })

    def service_sha256(self, item):
        text = text_payload(item, self.max_text_bytes)
        raw = text.encode("utf-8")
        return({"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})

    def service_text_metrics(self, item):
        text = text_payload(item, self.max_text_bytes)
        raw = text.encode("utf-8")
        words = re.findall(r"\S+", text)
        return({
            "bytes": len(raw),
            "chars": len(text),
            "lines": 0 if text == "" else (text.count("\n") + (0 if text.endswith("\n") else 1)),
            "words": len(words),
            "approx_tokens": max(1, int((len(raw) + 3) / 4)) if raw else 0,
            "sha256": hashlib.sha256(raw).hexdigest(),
        })

    def service_diff_stats(self, item):
        text = text_payload(item, self.max_text_bytes)
        files = set()
        add = 0
        delete = 0
        for line in text.splitlines():
            if line.startswith("diff --git "):
                parts = line.split()
                if len(parts) >= 4:
                    files.add(parts[3][2:] if parts[3].startswith("b/") else parts[3])
            elif line.startswith("+++ ") or line.startswith("--- "):
                path = line[4:].strip()
                if path not in ("/dev/null", ""):
                    files.add(path[2:] if path.startswith(("a/", "b/")) else path)
            elif line.startswith("+") and not line.startswith("+++"):
                add += 1
            elif line.startswith("-") and not line.startswith("---"):
                delete += 1
        return({
            "files": sorted(files),
            "file_count": len(files),
            "additions": add,
            "deletions": delete,
            "changed_lines": add + delete,
            "contains_evolve_block": "EVOLVE-BLOCK" in text,
        })

    def service_command(self, item):
        name = str(item.get("name") or item.get("command") or "")
        spec = self.commands.get(name)
        if not isinstance(spec, dict):
            raise CpuServiceError("unknown allowlisted command: %s" % name)
        argv = spec.get("argv")
        if not isinstance(argv, list) or len(argv) == 0:
            raise CpuServiceError("allowlisted command %s has no argv" % name)
        argv = [str(x) for x in argv]
        if item.get("args"):
            if not spec.get("allow_args"):
                raise CpuServiceError("allowlisted command %s does not allow item args" % name)
            argv.extend(str(x) for x in item.get("args"))
        cwd = expand_path(spec.get("cwd", os.getcwd()))
        stdin = None
        if "stdin" in item:
            if not spec.get("allow_stdin"):
                raise CpuServiceError("allowlisted command %s does not allow stdin" % name)
            stdin = str(item.get("stdin", ""))
        timeout = min(float(item.get("timeout_s", spec.get("timeout_s", self.command_timeout))), self.command_timeout)
        env = os.environ.copy()
        env.update({str(k): str(v) for k, v in (spec.get("env") or {}).items()})
        try:
            proc = subprocess.run(argv, input=stdin, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
            out = {
                "name": name,
                "returncode": proc.returncode,
                "stdout": safe_text(proc.stdout)[-self.command_output_bytes:],
                "stderr": safe_text(proc.stderr)[-self.command_output_bytes:],
            }
            return(service_result(proc.returncode == 0, out))
        except subprocess.TimeoutExpired as e:
            return(service_result(False, {"name": name, "timeout_s": timeout, "stdout": safe_text(e.stdout)[-self.command_output_bytes:], "stderr": safe_text(e.stderr)[-self.command_output_bytes:]}))


class LazyVllm:
    def __init__(self):
        self.host = os.environ.get("BACKEND_HOST", "127.0.0.1")
        self.port = env_int("BACKEND_PORT", 18000)
        self.models_root = os.path.expanduser(os.environ.get("MODELS_ROOT", "~/models/hf"))
        self.vllm_home = os.path.expanduser(os.environ.get("VLLM_HOME", "~/standard-runtimes/vllm-0.21.0"))
        self.pyhdr_home = os.path.expanduser(os.environ.get("PYHDR_HOME", "~/standard-runtimes/python3.12-dev-extract"))
        self.log_dir = os.path.expanduser(os.environ.get("LOG_DIR", "~/vllm-lazy-logs"))
        self.gguf_root = os.path.expanduser(os.environ.get("GGUF_MODELS_ROOT", "~/models/ds4"))
        self.dflash_root = os.path.expanduser(os.environ.get("DS4_DFLASH_ROOT", "~/models/hf/z-lab"))
        self.ds4_server = os.path.expanduser(os.environ.get("DS4_SERVER", "~/src/ds4/ds4-server"))
        self.llama_server = os.path.expanduser(os.environ.get("LLAMA_SERVER", "~/src/llama.cpp-kamnxt/build-cuda/bin/llama-server"))
        self.max_model_len = os.environ.get("MAX_MODEL_LEN", "32768")
        self.max_num_seqs = os.environ.get("MAX_NUM_SEQS", "64")
        self.max_num_batched_tokens = os.environ.get("MAX_NUM_BATCHED_TOKENS", "32768")
        self.gpu_util = os.environ.get("GPU_MEMORY_UTILIZATION", "0.75")
        self.enable_chunked_prefill = env_bool("VLLM_ENABLE_CHUNKED_PREFILL", True)
        self.enable_prefix_caching = env_bool("VLLM_ENABLE_PREFIX_CACHING", True)
        self.async_scheduling = env_bool("VLLM_ASYNC_SCHEDULING", True)
        self.dflash_tokens = env_int("DS4_DFLASH_NUM_SPEC_TOKENS", 15)
        self.dflash_gpu_util = os.environ.get("DS4_DFLASH_GPU_MEMORY_UTILIZATION", "0.85")
        self.dflash_max_num_seqs = os.environ.get("DS4_DFLASH_MAX_NUM_SEQS", "16")
        self.gguf_ctx = os.environ.get("GGUF_CTX", self.max_model_len)
        self.gguf_tokens = os.environ.get("GGUF_DEFAULT_TOKENS", os.environ.get("MAX_TOKENS", "4096"))
        self.llama_ngl = os.environ.get("LLAMA_NGL", "99")
        self.llama_parallel = os.environ.get("LLAMA_PARALLEL", "1")
        self.llama_batch = os.environ.get("LLAMA_BATCH", "2048")
        self.llama_ubatch = os.environ.get("LLAMA_UBATCH", "512")
        self.batch_max_items = env_int("BATCH_MAX_ITEMS", 256)
        self.batch_max_concurrency = env_int("BATCH_MAX_CONCURRENCY", 16)
        self.batch_default_concurrency = env_int("BATCH_DEFAULT_CONCURRENCY", 4)
        self.start_timeout = env_int("START_TIMEOUT", 1800)
        self.idle_timeout = env_int("IDLE_TIMEOUT", 1800)
        self.resident_base_port = env_int("DS4_RESIDENT_BACKEND_BASE_PORT", self.port + 100)
        self.resident_start = env_bool("DS4_RESIDENT_START", True)
        self.trust_remote_code = os.environ.get("TRUST_REMOTE_CODE", "1") != "0"
        self.extra_args = shlex.split(os.environ.get("VLLM_EXTRA_ARGS", ""))
        self.ds4_extra_args = shlex.split(os.environ.get("DS4_SERVER_EXTRA_ARGS", ""))
        self.llama_extra_args = shlex.split(os.environ.get("LLAMA_SERVER_EXTRA_ARGS", ""))
        self.tuning_config = self.load_tuning_config()
        self.models = model_dirs(self.models_root)
        self.models.update(gguf_model_dirs(self.gguf_root))
        self.models.update(extra_model_dirs())
        self.aliases = unique_aliases(self.models)
        self.remote_models = remote_model_map(self.models)
        self.resident_specs = self.load_resident_specs()
        self.resident = {}
        self.cond = threading.Condition()
        self.current_model = None
        self.proc = None
        self.log_path = None
        self.current_args = []
        self.last_used = now()
        self.active_requests = 0
        self.starting = False
        os.makedirs(self.log_dir, exist_ok=True)
        if self.resident_start:
            self.start_resident_models()
        threading.Thread(target=self.reaper, daemon=True).start()

    def resolve(self, model):
        model = (model or "").strip()
        if model in self.models:
            return(model)
        if model in self.aliases:
            return(self.aliases[model])
        raise VllmError("unknown model: %s" % model)

    def remote_for(self, model):
        return(self.remote_models.get(model))

    def resident_for(self, model):
        rec = self.resident.get(model)
        if rec is None:
            return(None)
        proc = rec.get("proc")
        if proc is None or proc.poll() is not None:
            raise VllmError("resident backend exited for %s: %s" % (model, self.tail_log(rec.get("log", ""))))
        return({"base": "http://%s:%d" % (self.host, rec["port"]), "model": self.served_model(model)})

    def active(self):
        return(self.proc is not None and self.proc.poll() is None)

    def backend_base(self):
        return("http://%s:%d" % (self.host, self.port))

    def status(self):
        with self.cond:
            return({
                "current_model": self.current_model,
                "backend": self.backend_base(),
                "active": self.active(),
                "pid": self.proc.pid if self.active() else None,
                "idle_seconds": int(now() - self.last_used),
                "idle_timeout": self.idle_timeout,
                "models": sorted(self.models),
                "aliases": self.aliases,
                "remote_models": self.remote_models,
                "resident_specs": [{k: v for k, v in spec.items() if k != "rec"} for spec in self.resident_specs],
                "resident_backends": self.resident_status(),
                "model_backends": {model: self.backend_label(model) for model in sorted(self.models)},
                "model_tuning": {model: self.effective_tuning(model, self.models[model]) for model in sorted(self.models)},
                "gateway_defaults": self.gateway_defaults(),
                "cpu_services": CPU.status(),
                "gpu": gpu_snapshot(),
                "log": self.log_path,
                "args": self.current_args if self.active() else [],
            })

    def log_file_path(self, model, port):
        safe = ("%s-%s" % (self.models[model].get("backend", "backend"), model)).replace("/", "_").replace(":", "_").replace(" ", "_")
        return(os.path.join(self.log_dir, "%s-%d.log" % (safe, port)))

    def backend_label(self, model):
        if model in self.resident:
            return("resident_" + self.models[model].get("backend", "vllm_lazy_hf"))
        if model in self.remote_models:
            return("vllm_remote")
        return(self.models[model].get("backend", "vllm_lazy_hf"))

    def load_resident_specs(self):
        items = env_json("DS4_RESIDENT_MODELS_JSON", [])
        if not isinstance(items, list):
            raise VllmError("DS4_RESIDENT_MODELS_JSON must be a list")
        specs = []
        used_ports = set()
        next_port = self.resident_base_port
        for item in items:
            if isinstance(item, str):
                item = {"model": item}
            if not isinstance(item, dict):
                raise VllmError("resident model spec must be a string or object")
            model = self.resolve(str(item.get("model", "")))
            port = item.get("port")
            if port in (None, ""):
                while next_port in used_ports:
                    next_port += 1
                port = next_port
                next_port += 1
            port = int(port)
            if port == self.port or port in used_ports:
                raise VllmError("resident backend port conflict for %s: %d" % (model, port))
            used_ports.add(port)
            spec = dict(item)
            spec["model"] = model
            spec["port"] = port
            spec["rec"] = self.resident_rec(model, spec)
            specs.append(spec)
        return(specs)

    def resident_rec(self, model, spec):
        rec = dict(self.models[model])
        if isinstance(spec.get("tuning"), dict):
            rec["tuning"] = merge_dicts(rec.get("tuning", {}), spec["tuning"])
        for key in TUNING_KEYS:
            if key in spec:
                rec[key] = spec[key]
        return(rec)

    def resident_status(self):
        out = {}
        for model, rec in sorted(self.resident.items()):
            proc = rec.get("proc")
            out[model] = {
                "active": proc is not None and proc.poll() is None,
                "pid": proc.pid if proc is not None and proc.poll() is None else None,
                "base": "http://%s:%d" % (self.host, rec["port"]),
                "port": rec["port"],
                "log": rec["log"],
                "args": rec["args"],
            }
        return(out)

    def gateway_defaults(self):
        return({
            "max_model_len": self.max_model_len,
            "max_num_seqs": self.max_num_seqs,
            "max_num_batched_tokens": self.max_num_batched_tokens,
            "gpu_memory_utilization": self.gpu_util,
            "enable_chunked_prefill": self.enable_chunked_prefill,
            "enable_prefix_caching": self.enable_prefix_caching,
            "async_scheduling": self.async_scheduling,
            "batch_max_items": self.batch_max_items,
            "batch_max_concurrency": self.batch_max_concurrency,
            "batch_default_concurrency": self.batch_default_concurrency,
        })

    def load_tuning_config(self):
        cfg = {}
        file_cfg = read_json_if_present(os.environ.get("DS4_GATEWAY_TUNING_FILE", ""))
        raw = os.environ.get("DS4_GATEWAY_TUNING_JSON", "")
        if raw != "":
            cfg = json.loads(raw)
        return(merge_dicts(file_cfg, cfg))

    def served_max_model_len(self, rec, requested=None):
        try:
            requested = int(float(requested if requested not in (None, "") else self.max_model_len))
            cap = rec.get("max_model_len")
            if cap not in (None, ""):
                cap = int(float(cap))
                if cap > 0 and cap < requested:
                    return(str(cap))
            return(str(requested))
        except Exception:
            return(str(requested if requested not in (None, "") else self.max_model_len))

    def pattern_tuning(self, model):
        out = {}
        for rec in self.tuning_config.get("patterns", []):
            if not isinstance(rec, dict):
                continue
            pat = rec.get("model") or rec.get("glob")
            contains = rec.get("contains")
            prefix = rec.get("prefix")
            match = False
            if pat and fnmatch.fnmatch(model, pat):
                match = True
            if contains and str(contains).lower() in model.lower():
                match = True
            if prefix and model.startswith(str(prefix)):
                match = True
            if match:
                out.update(rec.get("tuning", rec))
        for key in ("model", "glob", "contains", "prefix", "tuning"):
            out.pop(key, None)
        return(out)

    def auto_tuning(self, model, rec):
        lower = model.lower()
        arch = set(rec.get("architectures") or [])
        out = self.gateway_defaults()
        if rec.get("model_type") == "deepseek_v4" or "DeepseekV4ForCausalLM" in arch:
            out["kv_cache_dtype"] = os.environ.get("DEEPSEEK_V4_KV_CACHE_DTYPE", "fp8")
        if "qwen3" in lower or "qwen/qwen3" in lower:
            out["reasoning_parser"] = rec.get("reasoning_parser", "qwen3")
        if "coder" in lower:
            out["tool_call_parser"] = rec.get("tool_call_parser", "qwen3_coder")
            out["enable_auto_tool_choice"] = rec.get("enable_auto_tool_choice", True)
        if "glm-4.7" in lower or "glm-47" in lower:
            out["tool_call_parser"] = rec.get("tool_call_parser", "glm47")
            out["enable_auto_tool_choice"] = rec.get("enable_auto_tool_choice", True)
        if "phi-4-mini" in lower:
            out["tool_call_parser"] = rec.get("tool_call_parser", "phi4_mini_json")
            out["enable_auto_tool_choice"] = rec.get("enable_auto_tool_choice", True)
        dflash = self.dflash_model_path(model)
        if dflash:
            out["speculative_config"] = {
                "method": "dflash",
                "model": dflash,
                "num_speculative_tokens": self.dflash_tokens,
            }
            out["attention_backend"] = rec.get("attention_backend", "flash_attn")
            out["gpu_memory_utilization"] = self.dflash_gpu_util
            out["max_num_seqs"] = self.dflash_max_num_seqs
        return(out)

    def dflash_model_path(self, model):
        leaf = model.rsplit("/", 1)[-1]
        if not leaf.startswith("Qwen"):
            return("")
        for suffix in ("-GPTQ-Int4", "-FP8", "-NVFP4", "-AWQ"):
            if leaf.endswith(suffix):
                leaf = leaf[:-len(suffix)]
        name = leaf + "-DFlash"
        path = os.path.join(self.dflash_root, name)
        if os.path.exists(os.path.join(path, "config.json")):
            return(path)
        return("")

    def effective_tuning(self, model, rec):
        cfg_models = self.tuning_config.get("models", {})
        model_cfg = cfg_models.get(model, {})
        alias_cfg = cfg_models.get(model.rsplit("/", 1)[-1], {})
        direct = {key: rec[key] for key in TUNING_KEYS if key in rec}
        tuning = merge_dicts(
            self.auto_tuning(model, rec),
            self.tuning_config.get("defaults", {}),
            self.pattern_tuning(model),
            alias_cfg,
            model_cfg,
            rec.get("tuning", {}),
            direct,
        )
        tuning["max_model_len"] = self.served_max_model_len(rec, tuning.get("max_model_len"))
        return(tuning)

    def add_bool_arg(self, args, key, value, yes, no=None):
        if value is None:
            return
        if bool(value):
            args.append(yes)
        elif no is not None:
            args.append(no)

    def add_vllm_tuning_args(self, args, tuning):
        args.extend(["--max-model-len", str(tuning.get("max_model_len", self.max_model_len))])
        args.extend(["--max-num-seqs", str(tuning.get("max_num_seqs", self.max_num_seqs))])
        args.extend(["--max-num-batched-tokens", str(tuning.get("max_num_batched_tokens", self.max_num_batched_tokens))])
        args.extend(["--gpu-memory-utilization", str(tuning.get("gpu_memory_utilization", self.gpu_util))])
        self.add_bool_arg(args, "enable_chunked_prefill", tuning.get("enable_chunked_prefill"), "--enable-chunked-prefill", "--no-enable-chunked-prefill")
        self.add_bool_arg(args, "enable_prefix_caching", tuning.get("enable_prefix_caching"), "--enable-prefix-caching", "--no-enable-prefix-caching")
        self.add_bool_arg(args, "async_scheduling", tuning.get("async_scheduling"), "--async-scheduling", "--no-async-scheduling")
        if tuning.get("kv_cache_dtype"):
            args.extend(["--kv-cache-dtype", str(tuning["kv_cache_dtype"])])
        if tuning.get("reasoning_parser"):
            args.extend(["--reasoning-parser", str(tuning["reasoning_parser"])])
        if tuning.get("tool_call_parser"):
            args.extend(["--tool-call-parser", str(tuning["tool_call_parser"])])
        if tuning.get("attention_backend"):
            args.extend(["--attention-backend", str(tuning["attention_backend"])])
        if tuning.get("enable_auto_tool_choice"):
            args.append("--enable-auto-tool-choice")
        if tuning.get("speculative_config"):
            args.extend(["--speculative-config", json_arg(tuning["speculative_config"])])
        extra = tuning.get("extra_args", [])
        if isinstance(extra, str):
            extra = shlex.split(extra)
        args.extend(extra)

    def model_args(self, rec):
        args = []
        arch = set(rec.get("architectures") or [])
        if rec.get("model_type") == "deepseek_v4" or "DeepseekV4ForCausalLM" in arch:
            args.extend(["--tokenizer-mode", "deepseek_v4", "--load-format", "safetensors"])
        return(args)

    def start_backend_proc(self, model, rec, port):
        log_path = self.log_file_path(model, port)
        log = open(log_path, "ab", buffering=0)
        args = self.args(model, rec=rec, port=port)
        proc = subprocess.Popen(
            args,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=self.env(rec),
            preexec_fn=os.setsid,
            close_fds=True,
        )
        return(proc, args, log_path)

    def vllm_env(self):
        env = os.environ.copy()
        for key in ("VLLM_ENABLE_PREFIX_CACHING", "VLLM_ASYNC_SCHEDULING", "VLLM_ENABLE_CHUNKED_PREFILL"):
            env.pop(key, None)
        pyhdr = ":".join([
            os.path.join(self.pyhdr_home, "usr/include"),
            os.path.join(self.pyhdr_home, "usr/include/python3.12"),
            os.path.join(self.pyhdr_home, "usr/include/aarch64-linux-gnu/python3.12"),
        ])
        env["CPATH"] = pyhdr + (":" + env["CPATH"] if env.get("CPATH") else "")
        env["C_INCLUDE_PATH"] = pyhdr + (":" + env["C_INCLUDE_PATH"] if env.get("C_INCLUDE_PATH") else "")
        env["CPLUS_INCLUDE_PATH"] = pyhdr + (":" + env["CPLUS_INCLUDE_PATH"] if env.get("CPLUS_INCLUDE_PATH") else "")
        env["PATH"] = os.path.join(self.vllm_home, "bin") + ":" + env.get("PATH", "")
        env.setdefault("HF_HOME", os.path.expanduser("~/.cache/huggingface"))
        env.setdefault("VLLM_CACHE_ROOT", os.path.expanduser("~/.cache/vllm"))
        return(env)

    def env(self, rec):
        if rec.get("backend", "vllm_lazy_hf").startswith("vllm"):
            return(self.vllm_env())
        return(os.environ.copy())

    def vllm_args(self, model, rec, port=None):
        if port is None:
            port = self.port
        tuning = self.effective_tuning(model, rec)
        args = [
            os.path.join(self.vllm_home, "bin/python"),
            os.path.join(self.vllm_home, "bin/vllm"),
            "serve",
            rec["path"],
            "--served-model-name",
            model,
            "--host",
            self.host,
            "--port",
            str(port),
        ]
        self.add_vllm_tuning_args(args, tuning)
        if self.trust_remote_code:
            args.append("--trust-remote-code")
        if rec.get("format") == "mistral":
            args.extend(["--config-format", "mistral", "--tokenizer-mode", "mistral", "--load-format", "mistral"])
        args.extend(self.model_args(rec))
        args.extend(self.extra_args)
        return(args)

    def ds4_server_args(self, rec, port=None):
        if port is None:
            port = self.port
        server = expand_path(rec.get("server") or rec.get("binary") or self.ds4_server)
        args = [
            server,
            "--model",
            rec["path"],
            "--host",
            self.host,
            "--port",
            str(port),
            "--ctx",
            str(rec.get("ctx", self.gguf_ctx)),
            "--tokens",
            str(rec.get("tokens", self.gguf_tokens)),
        ]
        if rec.get("mtp"):
            args.extend(["--mtp", rec["mtp"]])
        backend = rec.get("runtime_backend", os.environ.get("DS4_RUNTIME_BACKEND", "cuda"))
        if backend:
            args.append("--" + backend if backend in ("cuda", "metal", "cpu") else "--backend")
            if backend not in ("cuda", "metal", "cpu"):
                args.append(backend)
        args.extend(shlex.split(str(rec.get("extra_args", ""))))
        args.extend(self.ds4_extra_args)
        return(args)

    def llama_server_args(self, rec, port=None):
        if port is None:
            port = self.port
        server = expand_path(rec.get("server") or rec.get("binary") or self.llama_server)
        args = [
            server,
            "-m",
            rec["path"],
            "-c",
            str(rec.get("ctx", self.gguf_ctx)),
            "-ngl",
            str(rec.get("ngl", self.llama_ngl)),
            "--host",
            self.host,
            "--port",
            str(port),
            "--no-webui",
            "--cache-prompt",
            "--metrics",
            "--parallel",
            str(rec.get("parallel", self.llama_parallel)),
            "-b",
            str(rec.get("batch", self.llama_batch)),
            "-ub",
            str(rec.get("ubatch", self.llama_ubatch)),
        ]
        args.extend(shlex.split(str(rec.get("extra_args", ""))))
        args.extend(self.llama_extra_args)
        return(args)

    def args(self, model, rec=None, port=None):
        if rec is None:
            rec = self.models[model]
        backend = rec.get("backend", "vllm_lazy_hf")
        if backend == "ds4_server":
            return(self.ds4_server_args(rec, port))
        if backend == "llama_server":
            return(self.llama_server_args(rec, port))
        return(self.vllm_args(model, rec, port))

    def ready_path(self, rec):
        backend = rec.get("backend", "vllm_lazy_hf")
        if rec.get("ready_path"):
            return(rec["ready_path"])
        if backend.startswith("vllm"):
            return("/v1/models")
        if backend == "ds4_server":
            return("/v1/models")
        return("/health")

    def wait_ready(self, model):
        rec = self.models[model]
        self.wait_ready_proc(model, rec, self.proc, self.port, self.log_path)

    def wait_ready_proc(self, model, rec, proc, port, log_path):
        ready_path = self.ready_path(rec)
        deadline = now() + self.start_timeout
        last_err = ""
        while now() < deadline:
            if proc is None or proc.poll() is not None:
                raise VllmError("backend exited during startup: %s" % self.tail_log(log_path))
            try:
                conn = http.client.HTTPConnection(self.host, port, timeout=3)
                conn.request("GET", ready_path)
                resp = conn.getresponse()
                resp.read()
                if resp.status == 200:
                    return
                last_err = "status %d" % resp.status
            except Exception as e:
                last_err = str(e)
            time.sleep(2)
        raise VllmError("timeout waiting for backend readiness: %s\n%s" % (last_err, self.tail_log(log_path)))

    def tail_log(self, path=None):
        if path is None:
            path = self.log_path
        if not path or not os.path.exists(path):
            return("")
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 12000), os.SEEK_SET)
            return(f.read().decode("utf-8", "replace"))

    def stop_locked(self, reason):
        if not self.active():
            self.proc = None
            self.current_model = None
            self.current_args = []
            return(False)
        pid = self.proc.pid
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = now() + 20
        while now() < deadline and self.proc.poll() is None:
            time.sleep(0.2)
        if self.proc.poll() is None:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.proc = None
        self.current_model = None
        self.current_args = []
        return(True)

    def release(self, model=None):
        with self.cond:
            if model and self.current_model not in (model, self.aliases.get(model, model)):
                return(False)
            stopped = self.stop_locked("release")
            self.cond.notify_all()
            return(stopped)

    def served_model(self, model):
        rec = self.models[model]
        return(str(rec.get("served_model") or rec.get("server_model") or model))

    def should_rewrite_local_model(self, model):
        rec = self.models[model]
        if rec.get("rewrite_model") is not None:
            return(bool(rec.get("rewrite_model")))
        return(rec.get("backend") in ("ds4_server", "llama_server") and self.served_model(model) != model)

    def ensure(self, raw_model):
        model = self.resolve(raw_model)
        rec = self.models[model]
        with self.cond:
            while self.starting:
                self.cond.wait()
            if self.active() and self.current_model == model:
                self.last_used = now()
                return(model)
            self.starting = True
        try:
            with self.cond:
                if self.active():
                    self.stop_locked("switch")
                self.proc, self.current_args, self.log_path = self.start_backend_proc(model, rec, self.port)
                self.current_model = model
                self.last_used = now()
            try:
                self.wait_ready(model)
            except Exception:
                with self.cond:
                    self.stop_locked("startup-failed")
                raise
            return(model)
        finally:
            with self.cond:
                self.starting = False
                self.cond.notify_all()

    def start_resident_models(self):
        for spec in self.resident_specs:
            model = spec["model"]
            port = spec["port"]
            rec = spec["rec"]
            proc, args, log_path = self.start_backend_proc(model, rec, port)
            self.resident[model] = {"proc": proc, "port": port, "args": args, "log": log_path}
            try:
                self.wait_ready_proc(model, rec, proc, port, log_path)
            except Exception:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                raise

    def reaper(self):
        while True:
            time.sleep(10)
            with self.cond:
                if self.idle_timeout <= 0 or self.active_requests > 0:
                    continue
                if self.active() and (now() - self.last_used) > self.idle_timeout:
                    self.stop_locked("idle")
                    self.cond.notify_all()


CPU = CpuServices()
STATE = LazyVllm()


def json_bytes(data):
    return(json.dumps(data, separators=(",", ":")).encode("utf-8"))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    def send_json(self, status, data):
        body = json_bytes(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return(b"")
        return(self.rfile.read(length))

    def model_list(self):
        data = []
        created = int(time.time())
        for model in sorted(STATE.models):
            data.append({
                "id": model,
                "object": "model",
                "created": created,
                "owned_by": "ds4-model-gateway",
                "root": STATE.models[model]["path"],
                "backend": STATE.backend_label(model),
                "served_model": STATE.served_model(model),
                "parent": None,
            })
        return({"object": "list", "data": data})

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path in ("/health", "/ping"):
            self.send_json(200, {"ok": True})
            return
        if path == "/v1/models":
            self.send_json(200, self.model_list())
            return
        if path == "/ds4/status":
            self.send_json(200, STATE.status())
            return
        if path == "/ds4/gpu":
            self.send_json(200, gpu_snapshot())
            return
        if path in ("/ds4/services", "/ds4/cpu/services"):
            self.send_json(200, CPU.status())
            return
        self.proxy(None)

    def do_POST(self):
        body = self.read_body()
        path = urllib.parse.urlsplit(self.path).path
        if path == "/ds4/release":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            model = (query.get("model") or [None])[0]
            self.send_json(200, {"released": STATE.release(model), "status": STATE.status()})
            return
        if path in ("/ds4/batch", "/ds4/batches"):
            if self.is_cpu_batch(body):
                self.handle_cpu_batch(body)
            else:
                self.handle_batch(body)
            return
        if path in ("/ds4/cpu/batch", "/ds4/cpu/batches", "/ds4/services/batches"):
            self.handle_cpu_batch(body)
            return
        self.proxy(body)

    def do_DELETE(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/ds4/release":
            self.send_json(200, {"released": STATE.release(), "status": STATE.status()})
            return
        self.send_json(404, {"error": "not found"})

    def request_model(self, body):
        if not body:
            if STATE.current_model:
                return(STATE.current_model)
            raise VllmError("request body must contain a model")
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            raise VllmError("request body is not valid JSON")
        model = payload.get("model")
        if not model:
            raise VllmError("request body must contain a model")
        return(model)

    def rewrite_model(self, body, model):
        if body is None:
            return(body)
        payload = json.loads(body.decode("utf-8"))
        payload["model"] = model
        return(json_bytes(payload))

    def front_base(self):
        port = self.server.server_address[1]
        return("127.0.0.1", port)

    def item_request(self, item):
        if not isinstance(item, dict):
            raise VllmError("batch item must be an object")
        req = item.get("request")
        if req is None:
            req = item
        if not isinstance(req, dict):
            raise VllmError("batch item request must be an object")
        return(dict(req))

    def is_cpu_batch(self, body):
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            return(False)
        return(isinstance(payload, dict) and payload.get("service") not in (None, "") and payload.get("model") in (None, ""))

    def batch_items(self, payload):
        items = payload.get("items")
        if items is None:
            items = payload.get("requests")
        if not isinstance(items, list):
            raise VllmError("batch body must contain items or requests array")
        if len(items) == 0:
            raise VllmError("batch must contain at least one item")
        if len(items) > STATE.batch_max_items:
            raise VllmError("batch item count %d exceeds BATCH_MAX_ITEMS=%d" % (len(items), STATE.batch_max_items))
        return(items)

    def batch_concurrency(self, payload):
        raw = payload.get("concurrency", STATE.batch_default_concurrency)
        try:
            value = int(raw)
        except Exception:
            raise VllmError("batch concurrency must be an integer")
        if value < 1:
            raise VllmError("batch concurrency must be >= 1")
        if value > STATE.batch_max_concurrency:
            raise VllmError("batch concurrency %d exceeds BATCH_MAX_CONCURRENCY=%d" % (value, STATE.batch_max_concurrency))
        return(value)

    def batch_endpoint(self, payload):
        endpoint = str(payload.get("endpoint", "/v1/chat/completions"))
        if not endpoint.startswith("/v1/"):
            raise VllmError("batch endpoint must be under /v1/")
        return(endpoint)

    def batch_resolved_model(self, payload, items):
        default_model = str(payload.get("model", "") or "")
        resolved = None
        for item in items:
            req = self.item_request(item)
            raw_model = str(req.get("model", default_model) or "")
            if raw_model == "":
                raise VllmError("batch model is required at top level or per item")
            model = STATE.resolve(raw_model)
            if resolved is None:
                resolved = model
            elif resolved != model:
                raise VllmError("batch items must resolve to one model: %s != %s" % (resolved, model))
        return(resolved)

    def batch_item_payload(self, payload, item, endpoint):
        req = self.item_request(item)
        default_model = str(payload.get("model", "") or "")
        default_max_tokens = payload.get("max_tokens")
        default_temperature = payload.get("temperature")
        for key in ("custom_id", "metadata", "request"):
            req.pop(key, None)
        if req.get("model") in (None, "") and default_model != "":
            req["model"] = default_model
        if "max_tokens" not in req and default_max_tokens is not None:
            req["max_tokens"] = default_max_tokens
        if "temperature" not in req and default_temperature is not None:
            req["temperature"] = default_temperature
        if endpoint.endswith("/chat/completions") and "messages" not in req and "prompt" in req:
            prompt = req.pop("prompt")
            req["messages"] = [{"role": "user", "content": str(prompt)}]
        req["stream"] = False
        return(req)

    def batch_call(self, endpoint, payload, timeout):
        host, port = self.front_base()
        body = json_bytes(payload)
        headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.request("POST", endpoint, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        text = data.decode("utf-8", "replace")
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = text
        return(resp.status, parsed)

    def batch_result(self, endpoint, payload, timeout, idx, item):
        custom_id = item.get("custom_id") if isinstance(item, dict) else None
        start = now()
        rec = {"index": idx, "custom_id": custom_id, "ok": False}
        try:
            req = self.batch_item_payload(payload, item, endpoint)
            status, parsed = self.batch_call(endpoint, req, timeout)
            rec.update({"status": status, "response": parsed, "ok": 200 <= status < 300})
        except Exception as e:
            rec["error"] = str(e)
        rec["elapsed_s"] = round(now() - start, 6)
        return(idx, rec)

    def handle_cpu_batch(self, body):
        try:
            if not body:
                raise CpuServiceError("CPU batch body must be JSON")
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise CpuServiceError("CPU batch body must be an object")
            service = CPU.service_name(payload)
            items = CPU.normalize_items(payload)
            concurrency = CPU.concurrency(payload)
            try:
                timeout = float(payload.get("timeout_s", payload.get("timeout", 300.0)))
            except Exception:
                raise CpuServiceError("CPU batch timeout_s must be numeric")
            if timeout <= 0:
                raise CpuServiceError("CPU batch timeout_s must be > 0")
            batch_id = "cpu-batch-%d" % int(now() * 1000)
            results = CPU.run_batch(service, items, concurrency, timeout)
            ok = sum(1 for rec in results if rec and rec.get("ok"))
            self.send_json(200, {
                "id": batch_id,
                "object": "ds4.cpu_batch",
                "status": "completed" if ok == len(results) else "completed_with_errors",
                "created": int(now()),
                "service": service,
                "concurrency": concurrency,
                "counts": {"total": len(results), "succeeded": ok, "failed": len(results) - ok},
                "results": results,
                "queue": CPU.status()["queue"],
            })
        except CpuServiceError as e:
            self.send_json(400, {"error": {"message": str(e), "type": "ds4_cpu_batch"}})
        except Exception:
            self.send_json(500, {"error": {"message": traceback.format_exc(), "type": "ds4_cpu_batch"}})

    def handle_batch(self, body):
        try:
            if not body:
                raise VllmError("batch body must be JSON")
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise VllmError("batch body must be an object")
            items = self.batch_items(payload)
            endpoint = self.batch_endpoint(payload)
            concurrency = self.batch_concurrency(payload)
            try:
                timeout = float(payload.get("timeout_s", payload.get("timeout", 900.0)))
            except Exception:
                raise VllmError("batch timeout_s must be numeric")
            if timeout <= 0:
                raise VllmError("batch timeout_s must be > 0")
            model = self.batch_resolved_model(payload, items)
            if STATE.resident_for(model) is None and STATE.remote_for(model) is None:
                STATE.ensure(model)
            batch_id = "batch-%d" % int(now() * 1000)
            results = [None] * len(items)
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
                futs = [ex.submit(self.batch_result, endpoint, payload, timeout, idx, item) for idx, item in enumerate(items)]
                for fut in concurrent.futures.as_completed(futs):
                    idx, rec = fut.result()
                    results[idx] = rec
            ok = sum(1 for rec in results if rec and rec.get("ok"))
            out = {
                "id": batch_id,
                "object": "ds4.batch",
                "status": "completed" if ok == len(results) else "completed_with_errors",
                "created": int(now()),
                "model": model,
                "endpoint": endpoint,
                "concurrency": concurrency,
                "counts": {"total": len(results), "succeeded": ok, "failed": len(results) - ok},
                "results": results,
            }
            self.send_json(200, out)
        except VllmError as e:
            self.send_json(400, {"error": {"message": str(e), "type": "ds4_batch"}})
        except Exception:
            self.send_json(500, {"error": {"message": traceback.format_exc(), "type": "ds4_batch"}})

    def proxy(self, body):
        path = urllib.parse.urlsplit(self.path).path
        counted = False
        remote = None
        try:
            if path.startswith("/v1/") or path in ("/tokenize", "/detokenize"):
                raw_model = self.request_model(body) if self.command != "GET" else STATE.current_model
                model = STATE.resolve(raw_model)
                if not model:
                    raise VllmError("no active model for GET proxy request")
                remote = STATE.resident_for(model)
                if remote is None:
                    remote = STATE.remote_for(model)
                if remote is not None:
                    body = self.rewrite_model(body, remote.get("model", model))
                else:
                    STATE.ensure(model)
                    if STATE.should_rewrite_local_model(model):
                        body = self.rewrite_model(body, STATE.served_model(model))
            with STATE.cond:
                STATE.active_requests += 1
                counted = True
                STATE.last_used = now()
            self.proxy_backend(body, remote)
        except VllmError as e:
            self.send_json(503, {"error": {"message": str(e), "type": "ds4_model_gateway"}})
        except Exception:
            self.send_json(500, {"error": {"message": traceback.format_exc(), "type": "ds4_model_gateway"}})
        finally:
            with STATE.cond:
                if counted and STATE.active_requests > 0:
                    STATE.active_requests -= 1
                STATE.last_used = now()

    def proxy_backend(self, body, remote=None):
        if remote is None:
            host = STATE.host
            port = STATE.port
        else:
            u = urllib.parse.urlsplit(remote["base"])
            host = u.hostname
            port = u.port or (443 if u.scheme == "https" else 80)
        conn_cls = http.client.HTTPSConnection if remote is not None and u.scheme == "https" else http.client.HTTPConnection
        conn = conn_cls(host, port, timeout=None)
        headers = {}
        for key, value in self.headers.items():
            if key.lower() not in HOP_HEADERS and key.lower() != "host":
                headers[key] = value
        if body is not None:
            headers["Content-Length"] = str(len(body))
        conn.request(self.command, self.path, body=body, headers=headers)
        resp = conn.getresponse()
        content_type = resp.getheader("content-type", "")
        streaming = "text/event-stream" in content_type.lower()
        self.send_response(resp.status)
        for key, value in resp.getheaders():
            if key.lower() not in HOP_HEADERS and key.lower() != "content-length":
                self.send_header(key, value)
        if streaming:
            self.send_header("Connection", "close")
            self.close_connection = True
        else:
            data = resp.read()
            self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if streaming:
            while True:
                data = resp.readline()
                if not data:
                    break
                self.wfile.write(data)
                self.wfile.flush()
        else:
            self.wfile.write(data)


def main():
    host = os.environ.get("FRONT_HOST", "127.0.0.1")
    port = env_int("FRONT_PORT", 8000)
    server = ThreadingHTTPServer((host, port), Handler)
    print("ds4 model gateway on http://%s:%d -> %s, models=%d" % (host, port, STATE.backend_base(), len(STATE.models)), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
