#!/usr/bin/env python3
"""Patch vLLM CUTLASS scaled-mm to bypass SM12x ScalarType 44 stable-op failure."""

from __future__ import annotations

import argparse
import difflib
import glob
import json
import shutil
from pathlib import Path
from typing import Any


PATCH_ID = "ds4-vllm-sm121-cutlass-scalartype44-fallback"


class PatchError(RuntimeError):
    pass


def _replace(text: str, old: str, new: str, label: str) -> tuple[str, bool]:
    if new in text:
        return text, False
    if old not in text:
        raise PatchError(f"missing expected block: {label}")
    return text.replace(old, new, 1), True


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


def patch_custom_ops(text: str) -> str:
    helper = '''
def _ds4_should_fallback_cutlass_scaled_mm(exc: RuntimeError) -> bool:
    if "Not yet supported ScalarType 44" not in str(exc):
        return False
    if not current_platform.is_cuda() or not torch.cuda.is_available():
        return False
    major, _minor = torch.cuda.get_device_capability()
    return major >= 12


def _ds4_expand_scaled_mm_scale(scale: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    scale = scale.to(torch.float32)
    if scale.ndim == 0:
        return scale
    if scale.ndim == 1 and target.ndim == 2:
        if scale.shape[0] == target.shape[0]:
            scale = scale.view(-1, 1)
        else:
            scale = scale.view(1, -1)
    while scale.ndim < target.ndim:
        scale = scale.unsqueeze(0)
    for dim, extent in enumerate(target.shape):
        scale_extent = scale.shape[dim]
        if scale_extent == extent:
            continue
        if extent % scale_extent != 0:
            raise RuntimeError(
                "cannot expand CUTLASS scale shape "
                f"{tuple(scale.shape)} to target shape {tuple(target.shape)}"
            )
        scale = scale.repeat_interleave(extent // scale_extent, dim=dim)
    return scale


def _ds4_cutlass_scaled_mm_torch_fallback(
    a: torch.Tensor,
    b: torch.Tensor,
    scale_a: torch.Tensor,
    scale_b: torch.Tensor,
    out_dtype: torch.dtype,
    bias: torch.Tensor | None,
) -> torch.Tensor:
    a = a.view(-1, a.shape[-1])
    scale_a = _ds4_expand_scaled_mm_scale(scale_a, a)
    scale_b = _ds4_expand_scaled_mm_scale(scale_b, b)
    out = torch.matmul(a.to(torch.float32) * scale_a, b.to(torch.float32) * scale_b)
    if bias is not None:
        out = out + bias.to(out.dtype)
    return out.to(out_dtype)


'''
    text, _ = _replace(
        text,
        "\ndef cutlass_scaled_mm(\n",
        "\n" + helper + "def cutlass_scaled_mm(\n",
        "ScalarType 44 fallback helpers",
    )
    text, _ = _replace(
        text,
        """    else:
        out = torch.empty((a.shape[0], b.shape[1]), dtype=out_dtype, device=a.device)
        torch.ops._C.cutlass_scaled_mm(out, a, b, scale_a, scale_b, bias)

    return out.view(*target_shape)
""",
        """    else:
        out = torch.empty((a.shape[0], b.shape[1]), dtype=out_dtype, device=a.device)
        try:
            torch.ops._C.cutlass_scaled_mm(out, a, b, scale_a, scale_b, bias)
        except RuntimeError as exc:
            if not _ds4_should_fallback_cutlass_scaled_mm(exc):
                raise
            out = _ds4_cutlass_scaled_mm_torch_fallback(
                a, b, scale_a, scale_b, out_dtype, bias
            )

    return out.view(*target_shape)
""",
        "ScalarType 44 fallback call site",
    )
    return text


def apply_patch(package_dir: Path, *, backup_suffix: str, write: bool) -> dict[str, Any]:
    path = package_dir / "_custom_ops.py"
    if not path.exists():
        raise PatchError(f"missing target file: {path}")
    original = path.read_text(encoding="utf-8")
    patched = patch_custom_ops(original)
    files = {"custom_ops": _write(path, original, patched, backup_suffix=backup_suffix, write=write)}
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
    parser.add_argument("--backup-suffix", default=".ds4_scalar44_fallback_bak")
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
