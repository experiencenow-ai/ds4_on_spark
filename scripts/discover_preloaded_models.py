#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


FORMAT = "small-model-inventory-v1"
DEFAULT_MODEL_ROOT = "/home/spark2/models"
GGUF_SUFFIXES = ("Q2", "Q3", "Q4", "Q5", "Q6", "Q8", "IQ", "BF16", "FP16", "FP8", "NVFP4")


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-")


def estimate_params(text: str) -> int | None:
    matches = re.findall(r"(\d+(?:\.\d+)?)([BM])(?=[-_./]|$)", text, flags=re.IGNORECASE)
    if not matches:
        return None
    value, suffix = matches[-1]
    multiplier = 1_000_000_000 if suffix.upper() == "B" else 1_000_000
    return int(float(value) * multiplier)


def infer_gguf_dtype(path: str) -> str:
    stem = Path(path).stem
    tokens = re.split(r"[-_]", stem)
    for index, token in enumerate(tokens):
        upper = token.upper()
        if upper in {"BF16", "FP16", "FP8", "Q8", "Q8_0", "Q4", "Q5"}:
            return upper
        if upper.startswith("IQ"):
            return upper
        if upper in {"Q2", "Q3", "Q4", "Q5", "Q6", "Q8"} and (index + 2) <= len(tokens):
            return "_".join(tokens[index : min(index + 3, len(tokens))]).upper()
        if any(upper.startswith(prefix) for prefix in GGUF_SUFFIXES):
            return upper
    return "unknown"


def infer_hf_dtype(config: dict[str, Any]) -> str:
    quant = config.get("quantization_config")
    if isinstance(quant, dict):
        method = quant.get("quant_method") or quant.get("load_in_4bit") or quant.get("bits")
        if method is not None:
            return str(method)
    for key in ("torch_dtype", "dtype", "model_dtype"):
        if config.get(key):
            return str(config[key])
    return "unknown"


def model_id_from_path(path: str, model_root: str) -> str:
    rel = path[len(model_root) :].strip("/") if path.startswith(model_root) else path.strip("/")
    if rel.endswith(".gguf"):
        rel = rel[:-5]
    if rel.endswith("/config.json"):
        rel = rel[: -len("/config.json")]
    return slug(rel)


def discover_from_remote_listing(listing: dict[str, Any], host: str, model_root: str) -> dict[str, Any]:
    models: list[dict[str, Any]] = []
    for path in sorted(listing.get("gguf_files") or []):
        params = estimate_params(path)
        models.append(
            {
                "model_id": model_id_from_path(path, model_root),
                "model_path": path,
                "model_size_params": params,
                "model_dtype": infer_gguf_dtype(path),
                "serve_backend": "llama.cpp",
                "artifact_type": "gguf",
                "hardware_node": host,
                "can_serve_request": bool(listing.get("llama_cli_path")),
                "serve_command_hint": listing.get("llama_cli_path") or "",
            }
        )
    for path, config in sorted((listing.get("hf_configs") or {}).items()):
        params = int(config.get("num_parameters") or 0) or estimate_params(path)
        models.append(
            {
                "model_id": model_id_from_path(path, model_root),
                "model_path": str(Path(path).parent),
                "model_size_params": params,
                "model_dtype": infer_hf_dtype(config),
                "serve_backend": "transformers",
                "artifact_type": "hf",
                "hardware_node": host,
                "can_serve_request": True,
                "serve_command_hint": "python3 transformers AutoModelForCausalLM local_files_only greedy decode",
            }
        )
    return {"format": FORMAT, "inventory_timestamp": utc_now(), "hardware_node": host, "model_root": model_root, "model_count": len(models), "models": models}


def remote_inventory_listing(host: str, model_root: str, timeout_seconds: float) -> dict[str, Any]:
    code = r'''
import json, os
root = "__ROOT__"
gguf = []
configs = {}
for base, dirs, files in os.walk(root):
    dirs[:] = [d for d in dirs if not d.startswith(".")]
    for name in files:
        path = os.path.join(base, name)
        if name.endswith(".gguf"):
            gguf.append(path)
        elif name == "config.json":
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    configs[path] = json.load(fh)
            except Exception as exc:
                configs[path] = {"config_error": str(exc)}
llama_cli = ""
for candidate_root in ("/home/spark2/src", "/home/spark2"):
    for base, dirs, files in os.walk(candidate_root):
        if "llama-cli" in files and "/bin" in base:
            llama_cli = os.path.join(base, "llama-cli")
            break
    if llama_cli:
        break
print(json.dumps({"gguf_files": sorted(gguf), "hf_configs": configs, "llama_cli_path": llama_cli}, sort_keys=True))
'''.replace("__ROOT__", model_root)
    remote = "python3 -c " + shlex.quote(code)
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, remote], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout_seconds, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"remote inventory failed on {host}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover models preloaded on a Spark node.")
    parser.add_argument("host")
    parser.add_argument("--model-root", default=DEFAULT_MODEL_ROOT)
    parser.add_argument("--output")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    args = parser.parse_args()
    listing = remote_inventory_listing(args.host, args.model_root, args.timeout_seconds)
    inventory = discover_from_remote_listing(listing, args.host, args.model_root)
    text = json.dumps(inventory, indent=2, sort_keys=True)
    if args.output:
        write_json(Path(args.output), inventory)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
