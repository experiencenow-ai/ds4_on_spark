#!/usr/bin/env python3
"""Patch vLLM DeepSeek-V4 mHC kernels to use the reference path on SM12x Spark."""

from __future__ import annotations

import argparse
import json
import sys
from functools import partial
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._lib.vllm_patch_utils import locate_vllm_package_dir
from scripts._lib.vllm_patch_utils import replace_count
from scripts._lib.vllm_patch_utils import replace_once
from scripts._lib.vllm_patch_utils import write_patch_file


PATCH_ID = "ds4-vllm-deepseek-v4-sm121-mhc-reference"


class PatchError(RuntimeError):
    pass


_replace = partial(replace_once, error_type=PatchError)
_replace_count = partial(replace_count, error_type=PatchError)
_write = write_patch_file
locate_package_dir = partial(locate_vllm_package_dir, error_type=PatchError)


def patch_mhc(text: str) -> str:
    reference_guard = "if _ds4_use_torch_mhc_reference():"
    if text.count(reference_guard) != 4:
        text, _ = _replace_count(
            text,
            "if current_platform.is_rocm():",
            reference_guard,
            3,
            "mHC reference guards",
        )
    text, _ = _replace(
        text,
        """@cache
def compute_num_split(block_k: int, k: int | None, grid_size: int) -> int:
""",
        """def _ds4_use_torch_mhc_reference() -> bool:
    if current_platform.is_rocm():
        return True
    if not torch.cuda.is_available():
        return False
    major, _minor = torch.cuda.get_device_capability()
    return major >= 12


@cache
def compute_num_split(block_k: int, k: int | None, grid_size: int) -> int:
""",
        "SM121 mHC reference helper",
    )
    text, _ = _replace(
        text,
        """    if num_tokens <= fma_token_threshold:
        mhc_fused_tilelang(
""",
        """    if _ds4_use_torch_mhc_reference():
        residual_cur = mhc_post(x, residual, post_layer_mix, comb_res_mix)
        post_mix_cur, comb_mix_cur, layer_input_cur = mhc_pre(
            residual_cur,
            fn,
            hc_scale,
            hc_base,
            rms_eps,
            hc_pre_eps,
            hc_sinkhorn_eps,
            hc_post_mult_value,
            sinkhorn_repeat,
            n_splits,
        )
        return (
            residual_cur.view(*outer_shape, hc_mult, hidden_size),
            post_mix_cur.view(*outer_shape, hc_mult, 1),
            comb_mix_cur.view(*outer_shape, hc_mult, hc_mult),
            layer_input_cur.view(*outer_shape, hidden_size),
        )

    if num_tokens <= fma_token_threshold:
        mhc_fused_tilelang(
""",
        "fused post-pre SM121 reference path",
    )
    return text


def apply_patch(package_dir: Path, *, backup_suffix: str, write: bool) -> dict[str, Any]:
    path = package_dir / "model_executor" / "layers" / "mhc.py"
    if not path.exists():
        raise PatchError(f"missing target file: {path}")
    original = path.read_text(encoding="utf-8")
    patched = patch_mhc(original)
    files = {"mhc": _write(path, original, patched, backup_suffix=backup_suffix, write=write)}
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
    parser.add_argument("--backup-suffix", default=".ds4_sm121_mhc_reference_bak")
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
