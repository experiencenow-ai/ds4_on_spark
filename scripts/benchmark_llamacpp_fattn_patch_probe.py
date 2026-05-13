#!/usr/bin/env python3
"""Read-only source probe for llama.cpp DSv4 Flash fattn reservation fix.

This script is designed to run on Spark-style hosts where the llama.cpp runtime
tree already exists. It does not build or run the model; it only scans source
files to determine whether the narrow pad-to-256 reservation patch is present.
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


def scan_file(path, patterns, max_matches=50):
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


def walk_candidates(root, rel_roots, want_files):
    out = []
    for rel in rel_roots:
        base = os.path.join(root, rel)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                if fn in want_files:
                    out.append(os.path.join(dirpath, fn))
    return out


def main():
    out_dir = os.environ.get("OUT_DIR", "/tmp/llamacpp_fattn_patch_probe")
    llama_dir = env_str_b64("LLAMA_DIR", os.path.expanduser("~/src/llama.cpp"))
    os.makedirs(out_dir, exist_ok=True)

    result = {
        "llama_dir": llama_dir,
        "llama_rev": None,
        "probe_ok": False,
        "files_checked": [],
        "pad256_found": False,
        "pad256_confidence": "absent",
        "pad256_matches": [],
        "cuda_reject_debug_found": None,
        "cuda_reject_debug_matches": [],
        "notes": [],
    }

    if not llama_dir or not os.path.isdir(llama_dir):
        result["notes"].append("missing llama_dir")
        with open(os.path.join(out_dir, "fattn_patch_probe.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, sort_keys=True)
        print(json.dumps(result, sort_keys=True))
        return 2

    result["llama_rev"] = git_rev(llama_dir)

    pad_patterns = [
        ("ggml_pad_256", re.compile(r"GGML_PAD\(\s*n_tokens\s*,\s*256\s*\)")),
        ("head_dim_512", re.compile(r"n_embd_head_k\s*==\s*512")),
        ("is_prefill", re.compile(r"\bis_prefill\b")),
        ("flash_attn", re.compile(r"\bflash_attn\b")),
        ("ggml_pad_call", re.compile(r"\bggml_pad\s*\(")),
        ("attn_mask_concat", re.compile(r"\battn_mask\s*=\s*ggml_concat\s*\(")),
        ("infinity", re.compile(r"-INFINITY")),
    ]

    # Prefer the canonical path of the DSv4 model builder; fall back to walking.
    candidates = []
    canonical = os.path.join(llama_dir, "src", "models", "deepseek4.cpp")
    if os.path.exists(canonical):
        candidates.append(canonical)
    else:
        want = {"deepseek4.cpp", "ggml-cuda.cu"}
        candidates.extend(walk_candidates(llama_dir, ["src/models", "src", "ggml/src/ggml-cuda"], want))
        # Fallback: if the file layout differs, scan a small bounded set of likely roots.
        if not candidates:
            candidates.extend(walk_candidates(llama_dir, ["src", "ggml/src"], want))

    candidates = sorted(set(candidates))
    for path in candidates:
        rel = os.path.relpath(path, llama_dir)
        result["files_checked"].append(rel)
        ms = scan_file(path, pad_patterns, max_matches=120)
        if not ms:
            continue

        hits = {m["pattern"] for m in ms}

        # Heuristic (high confidence): match the DSv4-specific prefill pad-to-256 fix:
        #   if (is_prefill && cparams.flash_attn && n_embd_head_k == 512) { ... GGML_PAD(n_tokens,256) ... ggml_pad ... attn_mask=ggml_concat(... -INFINITY) }
        required = {"ggml_pad_256", "head_dim_512", "is_prefill", "flash_attn"}
        supporting = {"ggml_pad_call", "attn_mask_concat", "infinity"}
        if required.issubset(hits):
            result["pad256_found"] = True
            support_count = len(hits.intersection(supporting))
            if support_count >= 2:
                result["pad256_confidence"] = "high"
            elif support_count >= 1:
                result["pad256_confidence"] = "medium"
            else:
                result["pad256_confidence"] = "low"

        # Store matches for any file that mentions the pad-to-256 anchor so later
        # debugging can inspect the exact lines without SSHing again.
        if "ggml_pad_256" in hits or "head_dim_512" in hits:
            result["pad256_matches"].append({"file": rel, "matches": ms})

    # Debug-print scan (best-effort): informational only.
    #
    # Historical note: some fattn reservation debugging patches introduced or removed
    # REJECT/ACCEPT stderr prints in `ggml-cuda.cu`, but those tokens may appear in
    # other contexts too. Treat this as an extra signal, not as a definitive
    # "patch present/absent" gate.
    cuda_debug_rx = re.compile(r"\bREJECT\b|\bACCEPT\b")
    cuda_debug_hits = []
    for path in candidates:
        if not path.endswith("ggml-cuda.cu"):
            continue
        rel = os.path.relpath(path, llama_dir)
        ms = scan_file(path, [("cuda_debug", cuda_debug_rx)], max_matches=20)
        if ms:
            cuda_debug_hits.append({"file": rel, "matches": ms})
    if cuda_debug_hits:
        result["cuda_reject_debug_found"] = True
        result["cuda_reject_debug_matches"] = cuda_debug_hits
    else:
        result["cuda_reject_debug_found"] = False

    # Record the patch artifact hash for cross-run pinning.
    patch_path = os.path.join(os.path.dirname(__file__), "..", "docs", "patches", "llama-cpp-kamnxt-ds4-fattn-reservation.patch")
    patch_path = os.path.normpath(patch_path)
    if os.path.exists(patch_path):
        try:
            result["patch_artifact_rel"] = "docs/patches/llama-cpp-kamnxt-ds4-fattn-reservation.patch"
            result["patch_artifact_sha256"] = sha256_file(patch_path)
        except Exception:
            pass

    result["probe_ok"] = True
    out_path = os.path.join(out_dir, "fattn_patch_probe.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, sort_keys=True)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
