#!/usr/bin/env python3
"""Patch vLLM 0.21 DeepSeek-V4 PP loading to skip tensors before materialization."""

from __future__ import annotations

import argparse
import difflib
import glob
import json
import shutil
from pathlib import Path
from typing import Any


PATCH_ID = "ds4-vllm-deepseek-v4-pp-safetensors-early-filter"


class PatchError(RuntimeError):
    pass


def _replace(text: str, old: str, new: str, label: str) -> tuple[str, bool]:
    if new in text:
        return text, False
    if old not in text:
        raise PatchError(f"missing expected block: {label}")
    return text.replace(old, new, 1), True


def _replace_any(text: str, variants: list[tuple[str, str]], label: str) -> tuple[str, bool]:
    for old, new in variants:
        if new in text:
            return text, False
        if old in text:
            return text.replace(old, new, 1), True
    raise PatchError(f"missing expected block: {label}")


def _write(path: Path, original: str, patched: str, *, backup_suffix: str, write: bool) -> dict[str, Any]:
    changed = original != patched
    if changed and write:
        backup = path.with_name(path.name + backup_suffix)
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(patched, encoding="utf-8")
    diff = ""
    if changed:
        diff = "".join(
            difflib.unified_diff(
                original.splitlines(True),
                patched.splitlines(True),
                fromfile=str(path),
                tofile=str(path),
            )
        )
    return {"path": str(path), "changed": changed, "diff": diff}


def locate_package_dir(runtime_root: Path | None, package_dir: Path | None) -> Path:
    if package_dir is not None:
        if not package_dir.exists():
            raise PatchError(f"vLLM package dir not found: {package_dir}")
        return package_dir
    if runtime_root is None:
        raise PatchError("either --runtime-root or --vllm-package-dir is required")
    matches = sorted(glob.glob(str(runtime_root / "lib" / "python*" / "site-packages" / "vllm")))
    if len(matches) != 1:
        raise PatchError(f"expected one vLLM package dir under {runtime_root}, found {matches}")
    return Path(matches[0])


def patch_weight_utils(text: str) -> str:
    text, _ = _replace(
        text,
        "    local_expert_ids: set[int] | None = None,\n    *,\n    safetensors_prefetch_num_threads: int = DEFAULT_SAFETENSORS_PREFETCH_NUM_THREADS,\n",
        "    local_expert_ids: set[int] | None = None,\n    *,\n    weight_name_filter: Callable[[str], bool] | None = None,\n    safetensors_prefetch_num_threads: int = DEFAULT_SAFETENSORS_PREFETCH_NUM_THREADS,\n",
        "safetensors_weights_iterator signature",
    )
    text, _ = _replace(
        text,
        "    When *local_expert_ids* is provided, expert weights not belonging to\n    this rank are skipped **before** reading from disk, which drastically\n    reduces storage I/O for MoE models under EP.\n",
        "    When *local_expert_ids* is provided, expert weights not belonging to\n    this rank are skipped **before** reading from disk, which drastically\n    reduces storage I/O for MoE models under EP. When *weight_name_filter*\n    is provided, model-specific PP or auxiliary weights can also be skipped\n    before calling safe_open(...).get_tensor(name).\n",
        "safetensors_weights_iterator docstring",
    )
    text, _ = _replace(
        text,
        "            for name, param in state_dict.items():\n                if not should_skip_weight(name, local_expert_ids):\n                    yield name, param\n",
        "            for name, param in state_dict.items():\n                if should_skip_weight(name, local_expert_ids):\n                    continue\n                if weight_name_filter is not None and not weight_name_filter(name):\n                    continue\n                yield name, param\n",
        "eager state_dict filter",
    )
    text, _ = _replace(
        text,
        "                for name in f.keys():  # noqa: SIM118\n                    if should_skip_weight(name, local_expert_ids):\n                        continue\n                    state_dict[name] = f.get_tensor(name)\n",
        "                for name in f.keys():  # noqa: SIM118\n                    if should_skip_weight(name, local_expert_ids):\n                        continue\n                    if weight_name_filter is not None and not weight_name_filter(name):\n                        continue\n                    state_dict[name] = f.get_tensor(name)\n",
        "torchao safe_open filter",
    )
    text, _ = _replace(
        text,
        "                for name in f.keys():  # noqa: SIM118\n                    if should_skip_weight(name, local_expert_ids):\n                        continue\n                    param = f.get_tensor(name)\n                    yield name, param\n",
        "                for name in f.keys():  # noqa: SIM118\n                    if should_skip_weight(name, local_expert_ids):\n                        continue\n                    if weight_name_filter is not None and not weight_name_filter(name):\n                        continue\n                    param = f.get_tensor(name)\n                    yield name, param\n",
        "default safe_open filter",
    )
    return text


def patch_default_loader(text: str) -> str:
    text, _ = _replace(
        text,
        "from collections.abc import Generator, Iterable\n",
        "from collections.abc import Callable, Generator, Iterable\n",
        "default_loader collections import",
    )
    text, _ = _replace(
        text,
        "    def _get_weights_iterator(\n        self, source: \"Source\"\n    ) -> Generator[tuple[str, torch.Tensor], None, None]:\n",
        "    def _get_weights_iterator(\n        self,\n        source: \"Source\",\n        weight_name_filter: Callable[[str], bool] | None = None,\n    ) -> Generator[tuple[str, torch.Tensor], None, None]:\n",
        "default_loader iterator signature",
    )
    text, _ = _replace_any(
        text,
        [
            (
                "                        local_expert_ids=self.local_expert_ids,\n                        safetensors_prefetch_num_threads=(\n",
                "                        local_expert_ids=self.local_expert_ids,\n                        weight_name_filter=weight_name_filter,\n                        safetensors_prefetch_num_threads=(\n",
            ),
            (
                "            local_expert_ids=self.local_expert_ids,\n            safetensors_prefetch_num_threads=(\n",
                "            local_expert_ids=self.local_expert_ids,\n            weight_name_filter=weight_name_filter,\n            safetensors_prefetch_num_threads=(\n",
            ),
        ],
        "default_loader safetensors call",
    )
    text, _ = _replace(
        text,
        "        )\n        yield from self._get_weights_iterator(primary_weights)\n",
        "        )\n        weight_name_filter = getattr(model, \"should_load_checkpoint_weight\", None)\n        yield from self._get_weights_iterator(primary_weights, weight_name_filter)\n",
        "default_loader get_all_weights predicate",
    )
    return text


def patch_deepseek_v4(text: str) -> str:
    method = """    def should_load_checkpoint_weight(self, name: str) -> bool:
        mapped_name = self.hf_to_vllm_mapper._map_name(name)
        if mapped_name is None:
            return False
        if "mtp." in mapped_name:
            return False
        return not is_pp_missing_parameter(mapped_name, self)

"""
    text, _ = _replace(
        text,
        "    def load_weights(self, weights: Iterable[tuple[str, torch.Tensor]]) -> set[str]:\n        loader = AutoWeightsLoader(self, skip_substrs=[\"mtp.\"])\n",
        method + "    def load_weights(self, weights: Iterable[tuple[str, torch.Tensor]]) -> set[str]:\n        loader = AutoWeightsLoader(self, skip_substrs=[\"mtp.\"])\n",
        "DeepseekV4ForCausalLM checkpoint predicate",
    )
    return text


def apply_patch(package_dir: Path, *, backup_suffix: str, write: bool) -> dict[str, Any]:
    targets = {
        "weight_utils": (
            package_dir / "model_executor" / "model_loader" / "weight_utils.py",
            patch_weight_utils,
        ),
        "default_loader": (
            package_dir / "model_executor" / "model_loader" / "default_loader.py",
            patch_default_loader,
        ),
        "deepseek_v4": (
            package_dir / "model_executor" / "models" / "deepseek_v4.py",
            patch_deepseek_v4,
        ),
    }
    files: dict[str, Any] = {}
    for name, (path, fn) in targets.items():
        if not path.exists():
            raise PatchError(f"missing target file: {path}")
        original = path.read_text(encoding="utf-8")
        patched = fn(original)
        files[name] = _write(path, original, patched, backup_suffix=backup_suffix, write=write)
    return {
        "patch_id": PATCH_ID,
        "package_dir": str(package_dir),
        "write": write,
        "changed": any(item["changed"] for item in files.values()),
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root")
    parser.add_argument("--vllm-package-dir")
    parser.add_argument("--backup-suffix", default=".ds4_pp_filter_bak")
    parser.add_argument("--check", action="store_true", help="Show whether changes are needed without writing.")
    args = parser.parse_args()
    package_dir = locate_package_dir(
        Path(args.runtime_root).expanduser() if args.runtime_root else None,
        Path(args.vllm_package_dir).expanduser() if args.vllm_package_dir else None,
    )
    result = apply_patch(package_dir, backup_suffix=args.backup_suffix, write=not args.check)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
