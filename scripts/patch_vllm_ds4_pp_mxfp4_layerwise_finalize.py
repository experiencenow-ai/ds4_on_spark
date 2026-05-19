#!/usr/bin/env python3
"""Patch vLLM 0.21 DeepSeek-V4 PP loading to finalize MXFP4 MoE layers early."""

from __future__ import annotations

import argparse
import difflib
import glob
import json
import shutil
from pathlib import Path
from typing import Any


PATCH_ID = "ds4-vllm-deepseek-v4-pp-mxfp4-layerwise-finalize"


class PatchError(RuntimeError):
    pass


def _replace(text: str, old: str, new: str, label: str) -> tuple[str, bool]:
    if new in text:
        return text, False
    if old not in text:
        raise PatchError(f"missing expected block: {label}")
    return text.replace(old, new, 1), True


def _replace_count(
    text: str, old: str, new: str, count: int, label: str
) -> tuple[str, bool]:
    if text.count(new) == count:
        return text, False
    found = text.count(old)
    if found != count:
        raise PatchError(f"expected {count} blocks for {label}, found {found}")
    return text.replace(old, new, count), True


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


def patch_deepseek_v4(text: str) -> str:
    helper_old = """        # Pre-compute expert mapping ONCE.
        expert_mapping = self.get_expert_mapping()

        for name, loaded_weight in weights:
"""
    helper_new = """        # Pre-compute expert mapping ONCE.
        expert_mapping = self.get_expert_mapping()
        expert_layer_load_hits: dict[int, set[tuple[int, str, bool]]] = {}

        def maybe_finalize_layer_experts(
            mapped_name: str, expert_id: int, shard_id: str
        ) -> None:
            layer_idx = extract_layer_index(mapped_name)
            layer = self.layers[layer_idx]
            ffn = getattr(layer, "ffn", None)
            experts = getattr(ffn, "experts", None)
            if experts is None:
                return
            layer_hits = expert_layer_load_hits.setdefault(layer_idx, set())
            layer_hits.add((expert_id, shard_id, "weight_scale" in mapped_name))
            expected_hits = int(getattr(ffn, "n_local_experts", self.config.n_routed_experts)) * 6
            if len(layer_hits) != expected_hits:
                return
            if getattr(experts, "_ds4_layerwise_finalized", False):
                del expert_layer_load_hits[layer_idx]
                return
            if getattr(ffn, "use_mega_moe", False):
                ffn.finalize_mega_moe_weights()
            else:
                quant_method = getattr(experts, "quant_method", None)
                process = getattr(quant_method, "process_weights_after_loading", None)
                if not callable(process):
                    return
                process(experts)
            experts._ds4_layerwise_finalized = True
            for param_key in list(params_dict):
                if param_key.startswith(f"layers.{layer_idx}.ffn.experts."):
                    del params_dict[param_key]
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            del expert_layer_load_hits[layer_idx]

        for name, loaded_weight in weights:
"""
    helper_previous = helper_new.replace(
        """            for param_key in list(params_dict):
                if param_key.startswith(f"layers.{layer_idx}.ffn.experts."):
                    del params_dict[param_key]
""",
        "",
    )
    if helper_new not in text and helper_previous in text:
        text = text.replace(helper_previous, helper_new, 1)
    else:
        text, _ = _replace(text, helper_old, helper_new, "DeepseekV4 layerwise helper")
    text, _ = _replace(
        text,
        """                        if success:
                            name = name_mapped
                            break
                    loaded_params.add(name_mapped)
""",
        """                        if success:
                            name = name_mapped
                            maybe_finalize_layer_experts(
                                name_mapped, expert_id, shard_id
                            )
                            break
                    loaded_params.add(name_mapped)
""",
        "DeepseekV4 expert success hook",
    )
    return text


def patch_mxfp4(text: str) -> str:
    old = """    def process_weights_after_loading(self, layer):
        w13 = layer.w13_weight
        w2 = layer.w2_weight
        w13_scale = layer.w13_weight_scale
        w2_scale = layer.w2_weight_scale
        w13_bias = getattr(layer, "w13_bias", None)
        w2_bias = getattr(layer, "w2_bias", None)

        if self.mxfp4_backend == Mxfp4MoeBackend.NONE:
            return

        self._setup_kernel(layer, w13, w2, w13_scale, w2_scale, w13_bias, w2_bias)
"""
    new = """    def process_weights_after_loading(self, layer):
        if getattr(layer, "_ds4_layerwise_finalized", False):
            return
        w13 = layer.w13_weight
        w2 = layer.w2_weight
        w13_scale = layer.w13_weight_scale
        w2_scale = layer.w2_weight_scale
        w13_bias = getattr(layer, "w13_bias", None)
        w2_bias = getattr(layer, "w2_bias", None)

        if self.mxfp4_backend == Mxfp4MoeBackend.NONE:
            return

        self._setup_kernel(layer, w13, w2, w13_scale, w2_scale, w13_bias, w2_bias)
        layer._ds4_layerwise_finalized = True
"""
    text, _ = _replace_count(text, old, new, 2, "MXFP4 process_weights_after_loading guards")
    return text


def apply_patch(package_dir: Path, *, backup_suffix: str, write: bool) -> dict[str, Any]:
    targets = {
        "deepseek_v4": (
            package_dir / "model_executor" / "models" / "deepseek_v4.py",
            patch_deepseek_v4,
        ),
        "mxfp4": (
            package_dir / "model_executor" / "layers" / "quantization" / "mxfp4.py",
            patch_mxfp4,
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
    parser.add_argument("--backup-suffix", default=".ds4_mxfp4_layerwise_finalize_bak")
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
