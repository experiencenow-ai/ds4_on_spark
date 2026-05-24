#!/usr/bin/env python3
import argparse
import http.client
import json
import os
import subprocess
import sys
import time
import urllib.parse


def jdump(obj):
    return(json.dumps(obj, sort_keys=True, separators=(",", ":")))


def request(method, url, payload=None, timeout=30):
    u = urllib.parse.urlsplit(url)
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["content-type"] = "application/json"
        headers["content-length"] = str(len(body))
    conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout)
    path = urllib.parse.urlunsplit(("", "", u.path or "/", u.query, ""))
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    text = data.decode("utf-8", "replace")
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = None
    return(resp.status, text, parsed)


def models(endpoint):
    status, text, parsed = request("GET", endpoint.rstrip("/") + "/models", timeout=30)
    if status != 200 or parsed is None:
        raise SystemExit("model list failed: %d %s" % (status, text[:500]))
    return(sorted(item["id"] for item in parsed["data"]))


def status(base):
    code, text, parsed = request("GET", base + "/ds4/status", timeout=30)
    if code != 200 or parsed is None:
        return({"error": text[:500], "code": code})
    return(parsed)


def release(base, model=None):
    url = base + "/ds4/release"
    if model:
        url += "?model=" + urllib.parse.quote(model, safe="")
    code, text, parsed = request("POST", url, timeout=120)
    return({"code": code, "body": parsed if parsed is not None else text[:500]})


def chat(endpoint, model, timeout, max_tokens):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Return exactly: OK"}],
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    body = json.dumps(payload, separators=(",", ":"))
    cmd = [
        "curl",
        "-sS",
        "--http1.1",
        "-m",
        str(timeout),
        "-w",
        "\n%{http_code}",
        "-H",
        "content-type: application/json",
        "-d",
        body,
        endpoint.rstrip("/") + "/chat/completions",
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out = proc.stdout
    if "\n" not in out:
        return(0, proc.stderr[-4000:] or out[-4000:], None)
    text, code = out.rsplit("\n", 1)
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = None
    if proc.returncode != 0 and parsed is None:
        text = (text + "\n" + proc.stderr)[-4000:]
    return(int(code or "0"), text, parsed)


def content(parsed):
    try:
        return(parsed["choices"][0]["message"].get("content") or "")
    except Exception:
        return("")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("BASE", "http://127.0.0.1:8000"))
    ap.add_argument("--out", default=os.environ.get("OUT", "/tmp/ds4_vllm_lazy_sweep.jsonl"))
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--skip", action="append", default=[])
    ap.add_argument("--timeout", type=int, default=int(os.environ.get("TIMEOUT", "1200")))
    ap.add_argument("--max-tokens", type=int, default=int(os.environ.get("MAX_TOKENS", "4")))
    args = ap.parse_args()
    endpoint = args.base.rstrip("/") + "/v1"
    wanted = models(endpoint)
    if args.only:
        keep = set(args.only)
        wanted = [m for m in wanted if m in keep or m.rsplit("/", 1)[-1] in keep]
    skip = set(args.skip)
    wanted = [m for m in wanted if m not in skip and m.rsplit("/", 1)[-1] not in skip]
    with open(args.out, "a", encoding="utf-8") as f:
        for idx, model in enumerate(wanted, 1):
            start = time.time()
            rec = {"model": model, "index": idx, "total": len(wanted), "started_at": int(start)}
            print("SWEEP_START %d/%d %s" % (idx, len(wanted), model), flush=True)
            rec["pre_release"] = release(args.base)
            try:
                code, text, parsed = chat(endpoint, model, args.timeout, args.max_tokens)
                rec["http_status"] = code
                rec["elapsed_sec"] = round(time.time() - start, 3)
                rec["response_model"] = parsed.get("model") if parsed else None
                rec["content"] = content(parsed)[:200] if parsed else ""
                rec["ok"] = (code == 200 and parsed is not None and len(parsed.get("choices", [])) > 0)
                if not rec["ok"]:
                    rec["error"] = text[-4000:]
            except Exception as e:
                rec["ok"] = False
                rec["elapsed_sec"] = round(time.time() - start, 3)
                rec["error"] = repr(e)
            rec["post_status"] = status(args.base)
            rec["post_release"] = release(args.base, model)
            time.sleep(2)
            rec["final_status"] = status(args.base)
            f.write(jdump(rec) + "\n")
            f.flush()
            print("SWEEP_DONE %s %s %.1fs" % ("ok" if rec.get("ok") else "fail", model, rec.get("elapsed_sec", -1)), flush=True)
    return(0)


if __name__ == "__main__":
    sys.exit(main())
