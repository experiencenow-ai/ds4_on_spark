#!/usr/bin/env python3
"""Run vLLM from one exact source root, with DS4 runtime compatibility shims."""

from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import runpy
import sys
from typing import Iterable


DEFAULT_MODULE = "vllm.entrypoints.cli.main"
SOURCE_ROOT_ERROR = "DS4 source-root guard requires --source-root or DS4_VLLM_SOURCE_ROOT"


def _resolve_path(raw: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(raw))).resolve()


def _looks_like_vllm_source_root(path_text: str) -> bool:
    if path_text == "":
        return False
    try:
        path = _resolve_path(path_text)
    except OSError:
        return False
    return (path / "vllm" / "__init__.py").is_file()


def _sanitize_sys_path(source_root: Path, original: Iterable[str]) -> list[str]:
    sanitized = [str(source_root)]
    seen = {str(source_root)}
    for entry in original:
        if entry == "":
            continue
        try:
            resolved = _resolve_path(entry)
        except OSError:
            continue
        resolved_text = str(resolved)
        if resolved == source_root:
            continue
        if _looks_like_vllm_source_root(resolved_text):
            continue
        if resolved_text in seen:
            continue
        sanitized.append(resolved_text)
        seen.add(resolved_text)
    return sanitized


def _package_root(module_file: str) -> Path:
    init_path = Path(module_file).resolve()
    return init_path.parent.parent


def _v2_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ds4_src_root() -> Path:
    return _v2_root() / "src"


def _sitecustomize_root() -> Path:
    return _ds4_src_root() / "ds4_vllm_runtime"


def _ensure_ds4_src_path(source_root: Path | None = None) -> None:
    path = _ds4_src_root()
    if source_root is not None:
        _insert_after_source_root(source_root, path)
        return
    path_text = str(path.resolve())
    if path_text not in sys.path:
        sys.path.insert(0, path_text)


def _insert_after_source_root(source_root: Path, path: Path) -> None:
    path_text = str(path.resolve())
    if path_text in sys.path:
        return
    try:
        source_index = sys.path.index(str(source_root))
    except ValueError:
        source_index = 0
    sys.path.insert(source_index + 1, path_text)


def _configure_child_pythonpath(source_root: Path) -> None:
    _ensure_ds4_src_path(source_root)
    from ds4_vllm_runtime.patches import env_flag

    entries = [str(source_root)]
    if env_flag("DS4_VLLM_SM12_FLASHMLA_SPARSE"):
        entries.extend([str(_sitecustomize_root()), str(_ds4_src_root())])
        os.environ["DS4_VLLM_RUNTIME_PATCHES_STRICT"] = "1"
    os.environ["PYTHONPATH"] = os.pathsep.join(entries)


def _proof(source_root: Path, module: str) -> dict[str, object]:
    vllm_module = importlib.import_module("vllm")
    actual_root = _package_root(str(vllm_module.__file__))
    return {
        "source_root": str(source_root),
        "module": module,
        "vllm_file": str(Path(str(vllm_module.__file__)).resolve()),
        "vllm_root": str(actual_root),
        "cwd": os.getcwd(),
        "sys_path_first": sys.path[:8],
        "python": sys.executable,
    }


def _allow_sm12_flashmla_sparse() -> str:
    _ensure_ds4_src_path(_resolve_path(os.getcwd()))
    from ds4_vllm_runtime.patches import allow_sm12_flashmla_sparse

    return allow_sm12_flashmla_sparse()


def _apply_runtime_patches() -> list[str]:
    patches = []
    if _env_flag("DS4_VLLM_SM12_FLASHMLA_SPARSE"):
        patches.append(_allow_sm12_flashmla_sparse())
    return patches


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        default=os.getenv("DS4_VLLM_SOURCE_ROOT", ""),
        help="vLLM source checkout or wheel overlay that must provide vllm",
    )
    parser.add_argument("--module", default=DEFAULT_MODULE)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument(
        "--proof-json",
        default=os.getenv("DS4_VLLM_IMPORT_PROOF_JSON", ""),
        help="optional path to write import-resolution proof JSON",
    )
    parser.add_argument("module_args", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def _prepare_source_root(args: argparse.Namespace) -> Path | int:
    if not args.source_root:
        print(SOURCE_ROOT_ERROR, file=sys.stderr)
        return 64
    source_root = _resolve_path(args.source_root)
    if not (source_root / "vllm" / "__init__.py").is_file():
        print(f"DS4 source-root guard: not a vLLM source root: {source_root}", file=sys.stderr)
        return 64
    os.chdir(source_root)
    sys.path[:] = _sanitize_sys_path(source_root, sys.path)
    _configure_child_pythonpath(source_root)
    return source_root


def _verified_proof(source_root: Path, module: str) -> dict[str, object] | int:
    proof = _proof(source_root, module)
    if Path(str(proof["vllm_root"])) != source_root:
        print("DS4 source-root guard: vLLM import drift detected", file=sys.stderr)
        print(json.dumps(proof, indent=2, sort_keys=True), file=sys.stderr)
        return 65
    return proof


def _write_proof(proof: dict[str, object], proof_json: str) -> None:
    if not proof_json:
        return
    proof_path = _resolve_path(proof_json)
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n")


def _print_proof(source_root: Path, proof: dict[str, object], patches: list[str]) -> None:
    print(
        "DS4 source-root guard: "
        f"imported vllm from {proof['vllm_file']} using source_root={source_root}; "
        f"runtime_patches={patches}",
        flush=True,
    )


def _run_module(module: str, module_args: list[str]) -> None:
    if module_args and module_args[0] == "--":
        module_args = module_args[1:]
    sys.argv = [module, *module_args]
    runpy.run_module(module, run_name="__main__", alter_sys=False)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    source_root = _prepare_source_root(args)
    if isinstance(source_root, int):
        return source_root
    proof = _verified_proof(source_root, args.module)
    if isinstance(proof, int):
        return proof
    patches = _apply_runtime_patches()
    proof["runtime_patches"] = patches
    _write_proof(proof, args.proof_json)
    _print_proof(source_root, proof, patches)
    if args.check_only:
        return 0
    _run_module(args.module, list(args.module_args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
