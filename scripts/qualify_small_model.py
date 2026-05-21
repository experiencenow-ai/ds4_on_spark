#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime
import json
import shlex
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any, Callable


FORMAT = "small-model-qualification-v1"
DEFAULT_EVAL_SET = Path("fixtures/small_model_qualification/eval_set_v1.json")
DEFAULT_LLAMA_CLI = "/home/spark2/src/llama.cpp-deepseek-v4-flash/build-rpc-cuda-nvcc/bin/llama-cli"
DEFAULT_TRANSFORMERS_PYTHON = "python3"
DEFAULT_TRANSFORMERS_DOCKER_IMAGE = ""
DEFAULT_TRANSFORMERS_MODEL_MOUNT = "/home/spark2/models:/home/spark2/models:ro"
TRANSFORMERS_RESULT_PREFIX = "__SMALL_MODEL_TRANSFORMERS_RESULT__ "
CommandRunner = Callable[[list[str], float], dict[str, Any]]


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_eval_set(path: Path) -> dict[str, Any]:
    data = load_json(path)
    if data.get("format") != "small-model-eval-set-v1":
        raise ValueError(f"invalid eval set format: {path}")
    prompts = data.get("prompts")
    if not isinstance(prompts, list) or not prompts:
        raise ValueError("eval set must contain prompts")
    task_ids = [item.get("task_id") for item in prompts]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("eval set task_id values must be unique")
    return data


def find_model(inventory: dict[str, Any], model_id: str) -> dict[str, Any]:
    for model in inventory.get("models") or []:
        if model.get("model_id") == model_id or model.get("model_path") == model_id:
            return dict(model)
    raise ValueError(f"model not found in inventory: {model_id}")


def default_command_runner(command: list[str], timeout_seconds: float) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout_seconds, check=False)
    except subprocess.TimeoutExpired as exc:
        elapsed = max(time.perf_counter() - started, 0.000001)
        return {"returncode": 124, "stdout": exc.stdout or "", "stderr": exc.stderr or "timeout expired", "elapsed_seconds": elapsed}
    elapsed = max(time.perf_counter() - started, 0.000001)
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr, "elapsed_seconds": elapsed}


def build_llama_command(host: str, llama_cli: str, model_path: str, prompt: str, max_tokens: int, timeout_seconds: float) -> list[str]:
    remote = [
        "timeout",
        "-k",
        "5s",
        str(int(max(timeout_seconds, 1.0))),
        llama_cli,
        "-m",
        model_path,
        "-p",
        prompt,
        "-n",
        str(max_tokens),
        "--temp",
        "0",
        "--no-display-prompt",
        "--log-disable",
        "--single-turn",
        "--simple-io",
    ]
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, shlex.join(remote)]


def transformers_runner_code() -> str:
    return r'''
import argparse, json
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
parser = argparse.ArgumentParser()
parser.add_argument("--model-path", required=True)
parser.add_argument("--prompt", required=True)
parser.add_argument("--max-new-tokens", type=int, required=True)
args = parser.parse_args()
tokenizer = AutoTokenizer.from_pretrained(args.model_path, trust_remote_code=True, local_files_only=True)
model = AutoModelForCausalLM.from_pretrained(args.model_path, torch_dtype="auto", trust_remote_code=True, local_files_only=True)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model.to(device)
model.eval()
if getattr(tokenizer, "chat_template", None):
    templated = tokenizer.apply_chat_template([{"role": "user", "content": args.prompt}], tokenize=True, add_generation_prompt=True, return_tensors="pt", return_dict=True)
    if hasattr(templated, "items"):
        inputs = {key: value.to(device) for key, value in templated.items()}
    else:
        inputs = {"input_ids": templated.to(device)}
else:
    inputs = tokenizer(args.prompt, return_tensors="pt")
    inputs = {key: value.to(device) for key, value in inputs.items()}
pad_token_id = tokenizer.eos_token_id
with torch.inference_mode():
    output_ids = model.generate(**inputs, max_new_tokens=args.max_new_tokens, do_sample=False, pad_token_id=pad_token_id)
prompt_tokens = int(inputs["input_ids"].shape[-1])
generated_ids = output_ids[0][prompt_tokens:]
generated_text = tokenizer.decode(generated_ids, skip_special_tokens=True)
print("__SMALL_MODEL_TRANSFORMERS_RESULT__ " + json.dumps({"generated_text": generated_text, "generated_token_count": int(generated_ids.numel())}, sort_keys=True))
'''


def transformers_batch_runner_code() -> str:
    return r'''
import argparse, json, time
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
parser = argparse.ArgumentParser()
parser.add_argument("--model-path", required=True)
parser.add_argument("--prompts-json", required=True)
args = parser.parse_args()
prompts = json.loads(args.prompts_json)
tokenizer = AutoTokenizer.from_pretrained(args.model_path, trust_remote_code=True, local_files_only=True)
model = AutoModelForCausalLM.from_pretrained(args.model_path, torch_dtype="auto", trust_remote_code=True, local_files_only=True)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model.to(device)
model.eval()
pad_token_id = tokenizer.eos_token_id
results = []
for item in prompts:
    prompt_text = str(item["prompt"])
    max_new_tokens = int(item.get("max_tokens") or 8)
    if getattr(tokenizer, "chat_template", None):
        templated = tokenizer.apply_chat_template([{"role": "user", "content": prompt_text}], tokenize=True, add_generation_prompt=True, return_tensors="pt", return_dict=True)
        if hasattr(templated, "items"):
            inputs = {key: value.to(device) for key, value in templated.items()}
        else:
            inputs = {"input_ids": templated.to(device)}
    else:
        inputs = tokenizer(prompt_text, return_tensors="pt")
        inputs = {key: value.to(device) for key, value in inputs.items()}
    started = time.perf_counter()
    with torch.inference_mode():
        output_ids = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False, pad_token_id=pad_token_id)
    elapsed = max(time.perf_counter() - started, 0.000001)
    prompt_tokens = int(inputs["input_ids"].shape[-1])
    generated_ids = output_ids[0][prompt_tokens:]
    generated_text = tokenizer.decode(generated_ids, skip_special_tokens=True)
    results.append({"task_id": item.get("task_id"), "generated_text": generated_text, "generated_token_count": int(generated_ids.numel()), "latency_ms": round(elapsed * 1000.0, 3)})
print("__SMALL_MODEL_TRANSFORMERS_RESULT__ " + json.dumps({"results": results}, sort_keys=True))
'''


def build_transformers_invocation(python_executable: str, model_path: str, prompt: str, max_tokens: int) -> list[str]:
    return [
        python_executable,
        "-c",
        transformers_runner_code(),
        "--model-path",
        model_path,
        "--prompt",
        prompt,
        "--max-new-tokens",
        str(max_tokens),
    ]


def build_transformers_batch_invocation(python_executable: str, model_path: str, prompts: list[dict[str, Any]]) -> list[str]:
    prompts_payload = json.dumps(
        [
            {"task_id": item["task_id"], "prompt": item["prompt"], "max_tokens": int(item.get("max_tokens") or 8)}
            for item in prompts
        ],
        sort_keys=True,
    )
    return [
        python_executable,
        "-c",
        transformers_batch_runner_code(),
        "--model-path",
        model_path,
        "--prompts-json",
        prompts_payload,
    ]


def build_transformers_command(host: str, python_executable: str, model_path: str, prompt: str, max_tokens: int, timeout_seconds: float, docker_image: str = DEFAULT_TRANSFORMERS_DOCKER_IMAGE, docker_model_mount: str = DEFAULT_TRANSFORMERS_MODEL_MOUNT) -> list[str]:
    invocation = build_transformers_invocation(python_executable, model_path, prompt, max_tokens)
    if docker_image:
        invocation = ["docker", "run", "--rm", "--gpus", "all", "-v", docker_model_mount, docker_image] + invocation
    remote = [
        "timeout",
        "-k",
        "5s",
        str(int(max(timeout_seconds, 1.0))),
    ] + invocation
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, shlex.join(remote)]


def build_transformers_batch_command(host: str, python_executable: str, model_path: str, prompts: list[dict[str, Any]], timeout_seconds: float, docker_image: str = DEFAULT_TRANSFORMERS_DOCKER_IMAGE, docker_model_mount: str = DEFAULT_TRANSFORMERS_MODEL_MOUNT) -> list[str]:
    invocation = build_transformers_batch_invocation(python_executable, model_path, prompts)
    if docker_image:
        invocation = ["docker", "run", "--rm", "--gpus", "all", "-v", docker_model_mount, docker_image] + invocation
    remote = [
        "timeout",
        "-k",
        "5s",
        str(int(max(timeout_seconds, 1.0))),
    ] + invocation
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, shlex.join(remote)]


def score_answer(expected: str, observed: str) -> bool:
    return bool(expected) and expected.lower() in observed.lower()


def token_count(text: str) -> int:
    return len([item for item in text.strip().split() if item])


def extract_generated_text(stdout: str, prompt_text: str) -> str:
    text = stdout.strip()
    if prompt_text in text:
        text = text.rsplit(prompt_text, 1)[-1]
    if "[ Prompt:" in text:
        text = text.split("[ Prompt:", 1)[0]
    if "Exiting..." in text:
        text = text.split("Exiting...", 1)[0]
    return text.strip(" \n>")[-1000:]


def extract_transformers_result(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        if line.startswith(TRANSFORMERS_RESULT_PREFIX):
            payload = line[len(TRANSFORMERS_RESULT_PREFIX) :]
            data = json.loads(payload)
            if not isinstance(data.get("generated_text"), str) and not isinstance(data.get("results"), list):
                raise RuntimeError("transformers runner result missing generated_text/results")
            return data
    raise RuntimeError("transformers runner did not emit result sentinel")


def run_transformers_prompts(model: dict[str, Any], prompts: list[dict[str, Any]], host: str, runner: CommandRunner, timeout_seconds: float, transformers_python: str, transformers_docker_image: str, transformers_model_mount: str) -> list[dict[str, Any]]:
    command_timeout = max(timeout_seconds, timeout_seconds * max(len(prompts), 1))
    command = build_transformers_batch_command(host, transformers_python, str(model["model_path"]), prompts, command_timeout, transformers_docker_image, transformers_model_mount)
    result = runner(command, command_timeout)
    stderr = str(result.get("stderr") or "").strip()
    if int(result.get("returncode") or 0) != 0:
        raise RuntimeError(f"transformers qualification command failed rc={int(result.get('returncode') or 0)} stderr={stderr[-1000:]}")
    parsed = extract_transformers_result(str(result.get("stdout") or ""))
    raw_results = parsed.get("results")
    if not isinstance(raw_results, list) or len(raw_results) != len(prompts):
        raise RuntimeError("transformers runner result count did not match prompt count")
    rows = []
    for prompt, raw in zip(prompts, raw_results):
        output = str(raw.get("generated_text") or "").strip()
        generated = int(raw.get("generated_token_count") or token_count(output))
        latency_ms = float(raw.get("latency_ms") or 0.0)
        elapsed = max(latency_ms / 1000.0, 0.000001)
        rows.append(
            {
                "task_id": prompt["task_id"],
                "task_kind": prompt["task_kind"],
                "prompt": prompt["prompt"],
                "expected_answer": prompt["expected_answer"],
                "observed_answer": output[-1000:],
                "generated_tokens": output.split(),
                "generated_token_count": generated,
                "latency_ms": round(latency_ms, 3),
                "tok_s": generated / elapsed if elapsed > 0.0 else 0.0,
                "passed": score_answer(str(prompt["expected_answer"]), output),
                "returncode": 0,
                "stderr_tail": stderr[-1000:],
            }
        )
    return rows


def cost_proxy(model_size_params: int | None, pass_rate: float) -> dict[str, Any]:
    params = int(model_size_params or 0)
    params_b = params / 1_000_000_000.0 if params > 0 else None
    denominator = max(pass_rate, 0.05)
    score = (params_b / denominator) if params_b is not None else None
    return {"basis": "model_size_params_billion / max(pass_rate, 0.05)", "score": score, "model_size_params": params or None}


def aggregate_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    pass_count = sum(1 for item in results if item.get("passed"))
    latencies = [float(item["latency_ms"]) for item in results]
    tok_s = [float(item["tok_s"]) for item in results]
    return {
        "prompt_count": len(results),
        "pass_count": pass_count,
        "pass_rate": pass_count / len(results) if results else 0.0,
        "mean_tok_s": statistics.mean(tok_s) if tok_s else 0.0,
        "median_tok_s": statistics.median(tok_s) if tok_s else 0.0,
        "p95_latency_ms": sorted(latencies)[min(len(latencies) - 1, int(0.95 * (len(latencies) - 1)))] if latencies else 0.0,
    }


def run_prompt(model: dict[str, Any], prompt: dict[str, Any], host: str, llama_cli: str, runner: CommandRunner, timeout_seconds: float, transformers_python: str = DEFAULT_TRANSFORMERS_PYTHON, transformers_docker_image: str = DEFAULT_TRANSFORMERS_DOCKER_IMAGE, transformers_model_mount: str = DEFAULT_TRANSFORMERS_MODEL_MOUNT) -> dict[str, Any]:
    backend = model.get("serve_backend")
    if backend == "llama.cpp" and not model.get("can_serve_request"):
        raise RuntimeError(f"model is not marked servable: {model.get('model_id')}")
    max_tokens = int(prompt.get("max_tokens") or 8)
    if backend == "llama.cpp":
        command = build_llama_command(host, llama_cli, str(model["model_path"]), str(prompt["prompt"]), max_tokens, timeout_seconds)
    elif backend == "transformers":
        command = build_transformers_command(host, transformers_python, str(model["model_path"]), str(prompt["prompt"]), max_tokens, timeout_seconds, transformers_docker_image, transformers_model_mount)
    else:
        raise RuntimeError(f"unsupported serve_backend for live qualification: {backend}")
    result = runner(command, timeout_seconds)
    raw_output = str(result.get("stdout") or "").strip()
    stderr = str(result.get("stderr") or "").strip()
    elapsed = float(result.get("elapsed_seconds") or 0.0)
    if backend == "transformers" and int(result.get("returncode") or 0) == 0:
        parsed = extract_transformers_result(raw_output)
        output = str(parsed["generated_text"]).strip()
        generated = int(parsed.get("generated_token_count") or token_count(output))
    else:
        output = extract_generated_text(raw_output, str(prompt["prompt"]))
        generated = token_count(output)
    passed = int(result.get("returncode") or 0) == 0 and score_answer(str(prompt["expected_answer"]), output)
    return {
        "task_id": prompt["task_id"],
        "task_kind": prompt["task_kind"],
        "prompt": prompt["prompt"],
        "expected_answer": prompt["expected_answer"],
        "observed_answer": output[-1000:],
        "generated_tokens": output.split(),
        "generated_token_count": generated,
        "latency_ms": round(max(elapsed, 0.000001) * 1000.0, 3),
        "tok_s": generated / elapsed if elapsed > 0.0 else 0.0,
        "passed": passed,
        "returncode": int(result.get("returncode") or 0),
        "stderr_tail": stderr[-1000:],
    }


def qualify_model(model: dict[str, Any], eval_set: dict[str, Any], host: str, llama_cli: str, runner: CommandRunner = default_command_runner, timeout_seconds: float = 120.0, transformers_python: str = DEFAULT_TRANSFORMERS_PYTHON, transformers_docker_image: str = DEFAULT_TRANSFORMERS_DOCKER_IMAGE, transformers_model_mount: str = DEFAULT_TRANSFORMERS_MODEL_MOUNT) -> dict[str, Any]:
    if model.get("serve_backend") == "transformers":
        results = run_transformers_prompts(model, eval_set["prompts"], host, runner, timeout_seconds, transformers_python, transformers_docker_image, transformers_model_mount)
    else:
        results = [run_prompt(model, prompt, host, llama_cli, runner, timeout_seconds, transformers_python, transformers_docker_image, transformers_model_mount) for prompt in eval_set["prompts"]]
    aggregate = aggregate_results(results)
    return {
        "format": FORMAT,
        "qualification_timestamp": utc_now(),
        "hardware_node": host,
        "model_id": model["model_id"],
        "model_path": model["model_path"],
        "model_size_params": model.get("model_size_params"),
        "model_dtype": model.get("model_dtype") or "unknown",
        "serve_backend": model.get("serve_backend"),
        "eval_set_id": eval_set["eval_set_id"],
        "per_prompt_results": results,
        "aggregate_metrics": aggregate,
        "cost_proxy_estimate": cost_proxy(model.get("model_size_params"), float(aggregate["pass_rate"])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Qualify one preloaded small model on Spark2.")
    parser.add_argument("model_id")
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--eval-set", default=str(DEFAULT_EVAL_SET))
    parser.add_argument("--host", default="spark2")
    parser.add_argument("--llama-cli", default=DEFAULT_LLAMA_CLI)
    parser.add_argument("--transformers-python", default=DEFAULT_TRANSFORMERS_PYTHON)
    parser.add_argument("--transformers-docker-image", default=DEFAULT_TRANSFORMERS_DOCKER_IMAGE)
    parser.add_argument("--transformers-model-mount", default=DEFAULT_TRANSFORMERS_MODEL_MOUNT)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--output")
    args = parser.parse_args()
    inventory = load_json(Path(args.inventory))
    eval_set = load_eval_set(Path(args.eval_set))
    model = find_model(inventory, args.model_id)
    record = qualify_model(model, eval_set, args.host, args.llama_cli, timeout_seconds=args.timeout_seconds, transformers_python=args.transformers_python, transformers_docker_image=args.transformers_docker_image, transformers_model_mount=args.transformers_model_mount)
    if args.output:
        write_json(Path(args.output), record)
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
