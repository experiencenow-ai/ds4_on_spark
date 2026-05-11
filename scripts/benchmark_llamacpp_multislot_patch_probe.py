#!/usr/bin/env python3
"""Read-only source probe for llama.cpp DeepSeek V4 multi-slot (--parallel 2) fixes.

This probe is intended for Spark-style hosts where a llama.cpp runtime source tree
already exists. It does not build or run a model; it only scans source files for
the narrow multi-slot reservation fixes tracked in docs/baseline-multislot-parallel2.md.
"""

import base64
import hashlib
import json
import os
import re
import subprocess
import sys


def env_str_b64(name, default=""):
    b64 = os.environ.get(name + "_B64", "")
    if b64:
        try:
            return base64.b64decode(b64.encode("utf-8")).decode("utf-8", errors="replace")
        except Exception:
            pass
    return os.environ.get(name, default)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def git_rev(path):
    try:
        out = subprocess.check_output(["git", "-C", path, "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
        return out.decode("utf-8", errors="replace").strip()
    except Exception:
        return None


def scan_file(path, patterns, max_matches=80):
    matches = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, start=1):
                ln = line.rstrip("\n")
                for name, rx in patterns:
                    if rx.search(ln):
                        matches.append({"pattern": name, "line": i, "text": ln[:4000]})
                        break
                if len(matches) >= max_matches:
                    break
    except Exception:
        return []
    return matches


def main():
    out_dir = os.environ.get("OUT_DIR", "/tmp/llamacpp_multislot_patch_probe")
    llama_dir = env_str_b64("LLAMA_DIR", os.path.expanduser("~/src/llama.cpp"))
    os.makedirs(out_dir, exist_ok=True)

    result = {
        "llama_dir": llama_dir,
        "llama_rev": None,
        "probe_ok": False,
        "files_checked": [],
        "swa_stream_view_found": False,
        "swa_stream_view_matches": [],
        "reserve_cap_n_ctx_seq_found": False,
        "reserve_cap_n_ctx_seq_matches": [],
        "patch_artifacts": [],
        "notes": [],
    }

    if not llama_dir or not os.path.isdir(llama_dir):
        result["notes"].append("missing llama_dir")
        with open(os.path.join(out_dir, "multislot_patch_probe.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, sort_keys=True)
        print(json.dumps(result, sort_keys=True))
        return 2

    result["llama_rev"] = git_rev(llama_dir)

    deepseek4_path = os.path.join(llama_dir, "src", "models", "deepseek4.cpp")
    context_path = os.path.join(llama_dir, "src", "llama-context.cpp")

    # Heuristic patterns:
    # - SWA stream view fix: ensure multi-stream cache views are sliced to one stream before reshape.
    swa_patterns = [
        ("mctx_swa_get_k", re.compile(r"mctx_swa->get_k\\s*\\(")),
        ("mctx_swa_get_v", re.compile(r"mctx_swa->get_v\\s*\\(")),
        ("ne3_check", re.compile(r"\\bne\\s*\\[\\s*3\\s*\\]\\s*>\\s*1")),
        ("ggml_view_3d", re.compile(r"\\bggml_view_3d\\s*\\(")),
        ("reshape_3d", re.compile(r"\\bggml_reshape_3d\\s*\\(")),
    ]

    reserve_patterns = [
        ("reserve_pos0", re.compile(r"\\breserve_pos0\\b")),
        ("n_ctx_seq", re.compile(r"\\bn_ctx_seq\\b")),
        ("deepseek_v4_resumed_pp", re.compile(r"DeepSeek\\s+V4\\s+resumed", re.IGNORECASE)),
    ]

    if os.path.exists(deepseek4_path):
        rel = os.path.relpath(deepseek4_path, llama_dir)
        result["files_checked"].append(rel)
        ms = scan_file(deepseek4_path, swa_patterns, max_matches=120)
        if ms:
            has_getk = any(m["pattern"] == "mctx_swa_get_k" for m in ms)
            has_view = any(m["pattern"] == "ggml_view_3d" for m in ms)
            has_ne3 = any(m["pattern"] == "ne3_check" for m in ms)
            if has_getk and has_view and has_ne3:
                result["swa_stream_view_found"] = True
            result["swa_stream_view_matches"].append({"file": rel, "matches": ms})
    else:
        result["notes"].append("missing src/models/deepseek4.cpp")

    if os.path.exists(context_path):
        rel = os.path.relpath(context_path, llama_dir)
        result["files_checked"].append(rel)
        ms = scan_file(context_path, reserve_patterns, max_matches=120)
        if ms:
            has_reserve = any(m["pattern"] == "reserve_pos0" for m in ms)
            has_seq = any(m["pattern"] == "n_ctx_seq" for m in ms)
            if has_reserve and has_seq:
                result["reserve_cap_n_ctx_seq_found"] = True
            result["reserve_cap_n_ctx_seq_matches"].append({"file": rel, "matches": ms})
    else:
        result["notes"].append("missing src/llama-context.cpp")

    # Record patch artifact hashes for cross-run bookkeeping (best-effort; these live in ds4_on_spark).
    repo_guess = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    patches = [
        ("docs/patches/llama-cpp-dsv4-multislot-swa-stream-view.patch", "swa_stream_view"),
        ("docs/patches/llama-cpp-dsv4-multislot-reserve-nctxseq.patch", "reserve_cap_n_ctx_seq"),
    ]
    for rel, kind in patches:
        path = os.path.join(repo_guess, rel)
        if not os.path.exists(path):
            continue
        try:
            result["patch_artifacts"].append(
                {
                    "kind": kind,
                    "artifact_rel": rel,
                    "sha256": sha256_file(path),
                }
            )
        except Exception:
            pass

    result["probe_ok"] = True
    out_path = os.path.join(out_dir, "multislot_patch_probe.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, sort_keys=True)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
