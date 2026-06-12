#!/usr/bin/env python3
from __future__ import annotations

import argparse
import http.client
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVAL_RUNNER = ROOT / "scripts" / "ds4_eval_api_runner.py"
DEFAULT_SOURCE_C = ROOT / "fixtures" / "ds4_eval" / "ds4_eval.c"
DEFAULT_LLAMA_REPO = "https://github.com/ggml-org/llama.cpp.git"
DEFAULT_LLAMA_REF = "pull/24423/head"
DEFAULT_LLAMA_COMMIT = "10a2613aa0b2686f7d0608520c4f0ea05219df03"
DEFAULT_CUDA_COMPILER = "/usr/local/cuda-13.0/bin/nvcc"
DEFAULT_LLAMA_TARGETS = [
    "llama-diffusion-cli",
    "llama-diffusion-gemma-visual-server",
    "llama-diffusion-gemma-server",
]
GGUF_REPO = "unsloth/diffusiongemma-26B-A4B-it-GGUF"
GGUF_FILES = {
    "q4": "diffusiongemma-26B-A4B-it-Q4_K_M.gguf",
    "q5": "diffusiongemma-26B-A4B-it-Q5_K_M.gguf",
    "q6": "diffusiongemma-26B-A4B-it-Q6_K.gguf",
    "q8": "diffusiongemma-26B-A4B-it-Q8_0.gguf",
    "bf16": "diffusiongemma-26B-A4B-it-BF16.gguf",
}
SNAPSHOT_REPOS = [
    "google/diffusiongemma-26B-A4B-it",
    "nvidia/diffusiongemma-26B-A4B-it-NVFP4",
    "RedHatAI/diffusiongemma-26B-A4B-it-NVFP4",
    "RedHatAI/diffusiongemma-26B-A4B-it-FP8-dynamic",
]


def _run(argv: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(argv), file=sys.stderr)
    subprocess.run(argv, cwd=str(cwd) if cwd else None, env=env, check=True)


def _out(argv: list[str], *, cwd: Path | None = None) -> str:
    print("+ " + " ".join(argv), file=sys.stderr)
    return subprocess.check_output(argv, cwd=str(cwd) if cwd else None, text=True).strip()


def _load_runner(path: Path):
    spec = importlib.util.spec_from_file_location("ds4_eval_api_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _system_prompt(mode: str, runner) -> str:
    if mode == "standard":
        return runner.SYSTEM_PROMPT
    if mode == "thinking":
        return (
            "You are solving a hard benchmark question. Think carefully in the "
            "model's reasoning channel if one is available. The final answer "
            "must follow the requested format exactly."
        )
    if mode == "answer_only":
        return "Solve the benchmark question. Output only the required final answer line."
    raise ValueError(f"unsupported prompt mode: {mode}")


def cmd_prepare_llama(args: argparse.Namespace) -> None:
    source_root = Path(args.source_root)
    if not (source_root / ".git").exists():
        source_root.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", args.repo, str(source_root)])
    _run(["git", "fetch", "origin", args.ref], cwd=source_root)
    fetched = _out(["git", "rev-parse", "FETCH_HEAD"], cwd=source_root)
    if args.commit and fetched != args.commit:
        raise SystemExit(f"fetched {fetched}, expected {args.commit}")
    _run(["git", "checkout", "--detach", args.commit or fetched], cwd=source_root)
    _run([
        "cmake",
        "-B",
        args.build_dir,
        "-DGGML_CUDA=ON",
        f"-DCMAKE_CUDA_COMPILER={args.cuda_compiler}",
        f"-DCMAKE_CUDA_ARCHITECTURES={args.cuda_arch}",
        "-DCMAKE_BUILD_TYPE=Release",
    ], cwd=source_root)
    targets = args.build_target or DEFAULT_LLAMA_TARGETS
    _run([
        "cmake",
        "--build",
        args.build_dir,
        "--target",
        *targets,
        "-j",
        str(args.jobs),
    ], cwd=source_root)


def cmd_download(args: argparse.Namespace) -> None:
    from huggingface_hub import hf_hub_download, snapshot_download

    root = Path(args.models_root)
    log_path = Path(args.log_jsonl)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(obj: dict) -> None:
        obj = dict(obj)
        obj["time"] = time.time()
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(obj, sort_keys=True) + "\n")

    variants = args.variant or list(GGUF_FILES)
    for variant in variants:
        filename = GGUF_FILES[variant]
        local_dir = root / GGUF_REPO
        log({"event": "start_file", "repo": GGUF_REPO, "filename": filename, "local_dir": str(local_dir)})
        path = hf_hub_download(
            repo_id=GGUF_REPO,
            filename=filename,
            local_dir=str(local_dir),
            local_dir_use_symlinks=False,
            resume_download=True,
        )
        log({"event": "done_file", "repo": GGUF_REPO, "filename": filename, "path": path, "bytes": Path(path).stat().st_size})
    if args.snapshots:
        for repo in SNAPSHOT_REPOS:
            local_dir = root / repo
            log({"event": "start_snapshot", "repo": repo, "local_dir": str(local_dir)})
            path = snapshot_download(repo_id=repo, local_dir=str(local_dir), local_dir_use_symlinks=False, resume_download=True)
            total = sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file())
            log({"event": "done_snapshot", "repo": repo, "path": path, "bytes": total})


def cmd_write_requests(args: argparse.Namespace) -> None:
    runner = _load_runner(Path(args.eval_runner))
    cases = runner.parse_eval_cases(Path(args.source_c))
    cases = [case for case in cases if case.get("source") == args.source]
    if args.limit:
        cases = cases[: args.limit]
    out = Path(args.out_jsonl)
    out.parent.mkdir(parents=True, exist_ok=True)
    system_prompt = _system_prompt(args.prompt_mode, runner)
    with out.open("w", encoding="utf-8") as handle:
        for idx, case in enumerate(cases):
            question_prompt = runner.build_question_prompt(case, response_style=args.response_style)
            payload = {
                "format": runner.REQUEST_FORMAT,
                "request_id": f"diffusiongemma-{args.prompt_mode}-{idx:03d}-{case['id']}",
                "max_output_tokens": args.max_output_tokens,
                "temperature": 0.0,
                "input": {
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": question_prompt},
                    ],
                    "prompt": question_prompt,
                    "metadata": {
                        "prompt_mode": args.prompt_mode,
                        "ds4_eval": runner._eval_metadata(case, idx),
                    },
                },
            }
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    _write_json(out.with_suffix(".manifest.json"), {
        "format": "diffusiongemma-gguf-requests-v1",
        "source": args.source,
        "source_c": str(args.source_c),
        "response_style": args.response_style,
        "prompt_mode": args.prompt_mode,
        "max_output_tokens": args.max_output_tokens,
        "request_count": len(cases),
    })
    print(json.dumps({"out_jsonl": str(out), "count": len(cases), "prompt_mode": args.prompt_mode}, sort_keys=True))


def _run_case(proc: subprocess.Popen[str], out_dir: Path, row: dict, seed: int, n_blocks: int) -> dict:
    request_id = str(row["request_id"])
    req_path = out_dir / "request_files" / f"{request_id}.json"
    _write_json(req_path, {
        "seed": seed,
        "n_blocks": n_blocks,
        "messages": row["input"]["messages"],
    })
    assert proc.stdin is not None and proc.stdout is not None
    started = time.time()
    proc.stdin.write(str(req_path) + "\n")
    proc.stdin.flush()
    cumulative: list[str] = []
    frames = 0
    errors: list[str] = []
    while True:
        line = proc.stdout.readline()
        if line == "":
            raise RuntimeError(f"server exited while waiting for {request_id}")
        line = line.rstrip("\n")
        if line.startswith("F "):
            frames += 1
        elif line.startswith("C "):
            parts = line.split(" ", 2)
            if len(parts) == 3:
                cumulative.append(json.loads(parts[2]))
        elif line == "DONE":
            break
        elif line.startswith("ERR "):
            errors.append(line)
            break
    text = cumulative[-1] if cumulative else ""
    return {
        "request": {"request_id": request_id},
        "result": {
            "request_id": request_id,
            "output": {"text": text},
            "usage": {"completion_tokens": len(text.split())},
            "diffusion": {
                "elapsed_s": round(time.time() - started, 6),
                "frames": frames,
                "blocks": len(cumulative),
                "errors": errors,
            },
        },
    }


def _http_json(host: str, port: int, method: str, path: str, payload: dict | None = None, timeout: float = 10.0) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="replace")
    finally:
        conn.close()
    if resp.status >= 400:
        raise RuntimeError(f"{method} {path} returned {resp.status}: {raw[:400]}")
    if raw.strip() == "":
        return {}
    return json.loads(raw)


def _wait_for_http_server(host: str, port: int, timeout_s: float, stderr_path: Path) -> None:
    deadline = time.time() + timeout_s
    last_err = ""
    while time.time() < deadline:
        try:
            _http_json(host, port, "GET", "/health", timeout=2.0)
            return
        except Exception as exc:
            last_err = str(exc)
            time.sleep(1.0)
    raise RuntimeError(f"server did not become healthy: {last_err}; stderr={stderr_path}")


def _openai_text_and_tokens(reply: dict) -> tuple[str, int]:
    choices = reply.get("choices") or []
    choice = choices[0] if choices else {}
    message = choice.get("message") or {}
    text = message.get("content")
    if text is None:
        text = choice.get("text", "")
    usage = reply.get("usage") or {}
    completion_tokens = usage.get("completion_tokens")
    if not isinstance(completion_tokens, int):
        completion_tokens = len(str(text).split())
    return str(text), completion_tokens


def cmd_run_gguf(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = _load_jsonl(Path(args.requests_jsonl))
    if args.limit:
        rows = rows[: args.limit]
    env = os.environ.copy()
    env["NGL"] = str(args.ngl)
    env["MAXTOK"] = str(args.maxtok)
    env["FA"] = "1" if args.flash_attn else "0"
    stderr_path = out_dir / "server.stderr.log"
    with stderr_path.open("w", encoding="utf-8") as serr:
        proc = subprocess.Popen(
            [args.server_bin, args.model],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=serr,
            text=True,
            bufsize=1,
            env=env,
        )
        assert proc.stdout is not None
        ready = proc.stdout.readline().rstrip("\n")
        if not ready.startswith("READY "):
            proc.kill()
            raise RuntimeError(f"server did not become ready: {ready!r}; stderr={stderr_path}")
        results: list[dict] = []
        started = time.time()
        try:
            for idx, row in enumerate(rows):
                print(f"[{idx + 1}/{len(rows)}] {row['request_id']}", file=sys.stderr)
                results.append(_run_case(proc, out_dir, row, args.seed + idx, args.n_blocks))
                _write_json(out_dir / "collect.partial.json", {"format": "diffusiongemma-collect-v1", "results": results})
        finally:
            if proc.stdin is not None:
                try:
                    proc.stdin.write("QUIT\n")
                    proc.stdin.flush()
                except BrokenPipeError:
                    pass
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
        collect = {
            "format": "diffusiongemma-collect-v1",
            "model": args.model,
            "server_bin": args.server_bin,
            "requests_jsonl": args.requests_jsonl,
            "run_s": round(time.time() - started, 6),
            "n_blocks": args.n_blocks,
            "maxtok": args.maxtok,
            "ngl": args.ngl,
            "flash_attn": bool(args.flash_attn),
            "seed": args.seed,
            "results": results,
        }
        _write_json(out_dir / "collect.json", collect)
        print(json.dumps({"out_dir": str(out_dir), "count": len(results), "run_s": collect["run_s"]}, sort_keys=True))


def cmd_run_openai_server(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = _load_jsonl(Path(args.requests_jsonl))
    if args.limit:
        rows = rows[: args.limit]
    cmd = [
        args.server_bin,
        "-m",
        args.model,
        "--host",
        args.host,
        "--port",
        str(args.port),
        "-c",
        str(args.ctx_size),
        "-ngl",
        str(args.ngl),
        "--diffusion-steps",
        str(args.diffusion_steps),
        "--diffusion-cuda-mmq-max-x",
        str(args.diffusion_cuda_mmq_max_x),
    ]
    if args.metrics:
        cmd.append("--metrics")
    if args.slots:
        cmd.append("--slots")
    stderr_path = out_dir / "server.stderr.log"
    stdout_path = out_dir / "server.stdout.log"
    with stderr_path.open("w", encoding="utf-8") as serr, stdout_path.open("w", encoding="utf-8") as sout:
        proc = subprocess.Popen(cmd, stdout=sout, stderr=serr, text=True)
        try:
            _wait_for_http_server(args.host, args.port, args.startup_timeout_s, stderr_path)
            results: list[dict] = []
            started = time.time()
            for idx, row in enumerate(rows):
                request_id = str(row["request_id"])
                print(f"[{idx + 1}/{len(rows)}] {request_id}", file=sys.stderr)
                max_tokens = int(row.get("max_output_tokens") or args.max_tokens)
                payload = {
                    "model": args.model_name,
                    "messages": row["input"]["messages"],
                    "max_tokens": max_tokens,
                    "temperature": float(row.get("temperature", 0.0)),
                }
                t0 = time.time()
                reply = _http_json(args.host, args.port, "POST", "/v1/chat/completions", payload, timeout=args.request_timeout_s)
                text, completion_tokens = _openai_text_and_tokens(reply)
                results.append({
                    "request": {"request_id": request_id},
                    "result": {
                        "request_id": request_id,
                        "output": {"text": text},
                        "usage": {"completion_tokens": completion_tokens},
                        "diffusion": {"elapsed_s": round(time.time() - t0, 6), "server": "openai"},
                    },
                })
                _write_json(out_dir / "collect.partial.json", {"format": "diffusiongemma-collect-v1", "results": results})
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
    collect = {
        "format": "diffusiongemma-collect-v1",
        "model": args.model,
        "server_bin": args.server_bin,
        "requests_jsonl": args.requests_jsonl,
        "run_s": round(time.time() - started, 6) if "started" in locals() else 0.0,
        "runner": "openai-server",
        "ctx_size": args.ctx_size,
        "ngl": args.ngl,
        "diffusion_steps": args.diffusion_steps,
        "diffusion_cuda_mmq_max_x": args.diffusion_cuda_mmq_max_x,
        "results": results if "results" in locals() else [],
    }
    _write_json(out_dir / "collect.json", collect)
    print(json.dumps({"out_dir": str(out_dir), "count": len(collect["results"]), "run_s": collect["run_s"]}, sort_keys=True))


def cmd_grade(args: argparse.Namespace) -> None:
    runner = _load_runner(Path(args.eval_runner))
    requests_by_id = runner._request_meta_by_id(_load_jsonl(Path(args.requests_jsonl)))
    collect = json.loads(Path(args.collect_json).read_text(encoding="utf-8"))
    summary = runner.grade_collect(requests_by_id, collect)
    if args.out_json:
        _write_json(Path(args.out_json), summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reproducible DiffusionGemma GGUF qualification helper.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare-llama")
    p.add_argument("--source-root", required=True)
    p.add_argument("--repo", default=DEFAULT_LLAMA_REPO)
    p.add_argument("--ref", default=DEFAULT_LLAMA_REF)
    p.add_argument("--commit", default=DEFAULT_LLAMA_COMMIT)
    p.add_argument("--build-dir", default="build-cuda")
    p.add_argument("--cuda-compiler", default=DEFAULT_CUDA_COMPILER)
    p.add_argument("--cuda-arch", default="121a-real")
    p.add_argument("--jobs", type=int, default=8)
    p.add_argument("--build-target", action="append", help="CMake target to build; repeat for multiple targets.")
    p.set_defaults(func=cmd_prepare_llama)
    d = sub.add_parser("download")
    d.add_argument("--models-root", required=True)
    d.add_argument("--log-jsonl", required=True)
    d.add_argument("--variant", choices=sorted(GGUF_FILES), action="append")
    d.add_argument("--snapshots", action="store_true")
    d.set_defaults(func=cmd_download)
    w = sub.add_parser("write-requests")
    w.add_argument("--eval-runner", default=str(DEFAULT_EVAL_RUNNER))
    w.add_argument("--source-c", default=str(DEFAULT_SOURCE_C))
    w.add_argument("--out-jsonl", required=True)
    w.add_argument("--source", default="COMPSEC")
    w.add_argument("--response-style", default="compsec_strict")
    w.add_argument("--prompt-mode", choices=("standard", "thinking", "answer_only"), default="standard")
    w.add_argument("--max-output-tokens", type=int, default=2048)
    w.add_argument("--limit", type=int, default=0)
    w.set_defaults(func=cmd_write_requests)
    r = sub.add_parser("run-gguf")
    r.add_argument("--server-bin", required=True)
    r.add_argument("--model", required=True)
    r.add_argument("--requests-jsonl", required=True)
    r.add_argument("--out-dir", required=True)
    r.add_argument("--n-blocks", type=int, default=8)
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--ngl", default="99")
    r.add_argument("--maxtok", default="4096")
    r.add_argument("--flash-attn", action=argparse.BooleanOptionalAction, default=True)
    r.add_argument("--limit", type=int, default=0)
    r.set_defaults(func=cmd_run_gguf)
    o = sub.add_parser("run-openai-server")
    o.add_argument("--server-bin", required=True)
    o.add_argument("--model", required=True)
    o.add_argument("--model-name", default="diffusion-gemma")
    o.add_argument("--requests-jsonl", required=True)
    o.add_argument("--out-dir", required=True)
    o.add_argument("--host", default="127.0.0.1")
    o.add_argument("--port", type=int, default=18081)
    o.add_argument("--ctx-size", type=int, default=8096)
    o.add_argument("--ngl", default="999")
    o.add_argument("--diffusion-steps", type=int, default=48)
    o.add_argument("--diffusion-cuda-mmq-max-x", type=int, default=64)
    o.add_argument("--max-tokens", type=int, default=1024)
    o.add_argument("--startup-timeout-s", type=float, default=300.0)
    o.add_argument("--request-timeout-s", type=float, default=600.0)
    o.add_argument("--metrics", action=argparse.BooleanOptionalAction, default=True)
    o.add_argument("--slots", action=argparse.BooleanOptionalAction, default=True)
    o.add_argument("--limit", type=int, default=0)
    o.set_defaults(func=cmd_run_openai_server)
    g = sub.add_parser("grade")
    g.add_argument("--eval-runner", default=str(DEFAULT_EVAL_RUNNER))
    g.add_argument("--requests-jsonl", required=True)
    g.add_argument("--collect-json", required=True)
    g.add_argument("--out-json")
    g.set_defaults(func=cmd_grade)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
