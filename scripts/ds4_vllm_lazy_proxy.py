#!/usr/bin/env python3
import http.client
import json
import os
import signal
import shlex
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


class VllmError(Exception):
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
            "format": "hf" if hf else "mistral",
            "model_type": cfg.get("model_type") or ("mistral" if mistral else None),
            "architectures": cfg.get("architectures") or [],
            "max_model_len": cfg.get("max_position_embeddings") or cfg.get("max_seq_len"),
        }
        dirnames[:] = []
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
    return(aliases)


class LazyVllm:
    def __init__(self):
        self.host = os.environ.get("BACKEND_HOST", "127.0.0.1")
        self.port = env_int("BACKEND_PORT", 18000)
        self.models_root = os.path.expanduser(os.environ.get("MODELS_ROOT", "~/models/hf"))
        self.vllm_home = os.path.expanduser(os.environ.get("VLLM_HOME", "~/standard-runtimes/vllm-0.21.0"))
        self.pyhdr_home = os.path.expanduser(os.environ.get("PYHDR_HOME", "~/standard-runtimes/python3.12-dev-extract"))
        self.log_dir = os.path.expanduser(os.environ.get("LOG_DIR", "~/vllm-lazy-logs"))
        self.max_model_len = os.environ.get("MAX_MODEL_LEN", "32768")
        self.gpu_util = os.environ.get("GPU_MEMORY_UTILIZATION", "0.70")
        self.start_timeout = env_int("START_TIMEOUT", 900)
        self.idle_timeout = env_int("IDLE_TIMEOUT", 1800)
        self.trust_remote_code = os.environ.get("TRUST_REMOTE_CODE", "1") != "0"
        self.extra_args = shlex.split(os.environ.get("VLLM_EXTRA_ARGS", ""))
        self.models = model_dirs(self.models_root)
        self.aliases = unique_aliases(self.models)
        self.cond = threading.Condition()
        self.current_model = None
        self.proc = None
        self.log_path = None
        self.last_used = now()
        self.active_requests = 0
        self.starting = False
        os.makedirs(self.log_dir, exist_ok=True)
        threading.Thread(target=self.reaper, daemon=True).start()

    def resolve(self, model):
        model = (model or "").strip()
        if model in self.models:
            return(model)
        if model in self.aliases:
            return(self.aliases[model])
        raise VllmError("unknown model: %s" % model)

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
                "log": self.log_path,
            })

    def open_log(self, model):
        safe = model.replace("/", "_").replace(":", "_").replace(" ", "_")
        self.log_path = os.path.join(self.log_dir, "%s-%d.log" % (safe, self.port))
        return(open(self.log_path, "ab", buffering=0))

    def env(self):
        env = os.environ.copy()
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

    def args(self, model):
        rec = self.models[model]
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
            str(self.port),
            "--max-model-len",
            self.max_model_len,
            "--gpu-memory-utilization",
            self.gpu_util,
        ]
        if self.trust_remote_code:
            args.append("--trust-remote-code")
        if rec.get("format") == "mistral":
            args.extend(["--config-format", "mistral", "--tokenizer-mode", "mistral", "--load-format", "mistral"])
        args.extend(self.extra_args)
        return(args)

    def wait_ready(self):
        deadline = now() + self.start_timeout
        last_err = ""
        while now() < deadline:
            if not self.active():
                raise VllmError("vLLM exited during startup: %s" % self.tail_log())
            try:
                conn = http.client.HTTPConnection(self.host, self.port, timeout=3)
                conn.request("GET", "/v1/models")
                resp = conn.getresponse()
                resp.read()
                if resp.status == 200:
                    return
                last_err = "status %d" % resp.status
            except Exception as e:
                last_err = str(e)
            time.sleep(2)
        raise VllmError("timeout waiting for vLLM readiness: %s\n%s" % (last_err, self.tail_log()))

    def tail_log(self):
        if not self.log_path or not os.path.exists(self.log_path):
            return("")
        with open(self.log_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 12000), os.SEEK_SET)
            return(f.read().decode("utf-8", "replace"))

    def stop_locked(self, reason):
        if not self.active():
            self.proc = None
            self.current_model = None
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
        return(True)

    def release(self, model=None):
        with self.cond:
            if model and self.current_model not in (model, self.aliases.get(model, model)):
                return(False)
            stopped = self.stop_locked("release")
            self.cond.notify_all()
            return(stopped)

    def ensure(self, raw_model):
        model = self.resolve(raw_model)
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
                log = self.open_log(model)
                self.proc = subprocess.Popen(
                    self.args(model),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env=self.env(),
                    preexec_fn=os.setsid,
                    close_fds=True,
                )
                self.current_model = model
                self.last_used = now()
            try:
                self.wait_ready()
            except Exception:
                with self.cond:
                    self.stop_locked("startup-failed")
                raise
            return(model)
        finally:
            with self.cond:
                self.starting = False
                self.cond.notify_all()

    def reaper(self):
        while True:
            time.sleep(10)
            with self.cond:
                if self.idle_timeout <= 0 or self.active_requests > 0:
                    continue
                if self.active() and (now() - self.last_used) > self.idle_timeout:
                    self.stop_locked("idle")
                    self.cond.notify_all()


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
                "owned_by": "ds4-lazy-vllm",
                "root": STATE.models[model]["path"],
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
        self.proxy(None)

    def do_POST(self):
        body = self.read_body()
        path = urllib.parse.urlsplit(self.path).path
        if path == "/ds4/release":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            model = (query.get("model") or [None])[0]
            self.send_json(200, {"released": STATE.release(model), "status": STATE.status()})
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

    def proxy(self, body):
        path = urllib.parse.urlsplit(self.path).path
        counted = False
        try:
            if path.startswith("/v1/") or path in ("/tokenize", "/detokenize"):
                model = self.request_model(body) if self.command != "GET" else STATE.current_model
                if not model:
                    raise VllmError("no active model for GET proxy request")
                STATE.ensure(model)
            with STATE.cond:
                STATE.active_requests += 1
                counted = True
                STATE.last_used = now()
            self.proxy_backend(body)
        except VllmError as e:
            self.send_json(503, {"error": {"message": str(e), "type": "ds4_lazy_vllm"}})
        except Exception:
            self.send_json(500, {"error": {"message": traceback.format_exc(), "type": "ds4_lazy_vllm"}})
        finally:
            with STATE.cond:
                if counted and STATE.active_requests > 0:
                    STATE.active_requests -= 1
                STATE.last_used = now()

    def proxy_backend(self, body):
        conn = http.client.HTTPConnection(STATE.host, STATE.port, timeout=None)
        headers = {}
        for key, value in self.headers.items():
            if key.lower() not in HOP_HEADERS and key.lower() != "host":
                headers[key] = value
        if body is not None:
            headers["Content-Length"] = str(len(body))
        conn.request(self.command, self.path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        self.send_response(resp.status)
        for key, value in resp.getheaders():
            if key.lower() not in HOP_HEADERS and key.lower() != "content-length":
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    host = os.environ.get("FRONT_HOST", "127.0.0.1")
    port = env_int("FRONT_PORT", 8000)
    server = ThreadingHTTPServer((host, port), Handler)
    print("ds4 lazy vLLM proxy on http://%s:%d -> %s, models=%d" % (host, port, STATE.backend_base(), len(STATE.models)), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
