#!/usr/bin/env python3
"""Patch vLLM DeepSeek-V4 fused Q/KV RMSNorm with an SM12x JIT-free fallback."""

from __future__ import annotations

import argparse
import difflib
import glob
import json
import shutil
from pathlib import Path
from typing import Any


PATCH_ID = "ds4-vllm-sm121-fused-qk-rmsnorm-reference"


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


def patch_fused_qk_rmsnorm(text: str) -> str:
    helper = '''
def _ds4_should_fallback_fused_qk_rmsnorm(exc: BaseException, ref: torch.Tensor) -> bool:
    message = str(exc)
    if "Python.h" not in message and "Failed to compile launcher" not in message and "cuda_utils.c" not in message:
        return False
    return _ds4_is_sm12x_cuda(ref)


def _ds4_is_sm12x_cuda(ref: torch.Tensor) -> bool:
    if not ref.is_cuda or not torch.cuda.is_available():
        return False
    major, _minor = torch.cuda.get_device_capability(ref.device)
    return major >= 12


def _ds4_missing_python_header() -> bool:
    sysconfig = __import__("sysconfig")
    os_module = __import__("os")
    os_path = os_module.path
    for env_name in ("CPATH", "C_INCLUDE_PATH"):
        for include_dir in os_module.environ.get(env_name, "").split(os_module.pathsep):
            if include_dir and os_path.exists(os_path.join(include_dir, "Python.h")):
                return False
    include_dir = sysconfig.get_path("include")
    if not include_dir:
        return False
    return not os_path.exists(os_path.join(include_dir, "Python.h"))


def _ds4_should_use_fused_qk_rmsnorm_reference(ref: torch.Tensor) -> bool:
    return _ds4_is_sm12x_cuda(ref) and _ds4_missing_python_header()


def _ds4_rmsnorm_reference(
    x: torch.Tensor,
    weight: torch.Tensor,
    eps: float,
) -> torch.Tensor:
    x_fp32 = x.to(torch.float32)
    variance = torch.mean(x_fp32 * x_fp32, dim=-1, keepdim=True)
    y = x_fp32 * torch.rsqrt(variance + eps) * weight.to(torch.float32)
    return y.to(x.dtype)


def _ds4_fused_q_kv_rmsnorm_reference(
    qr: torch.Tensor,
    kv: torch.Tensor,
    q_weight: torch.Tensor,
    kv_weight: torch.Tensor,
    eps: float,
) -> tuple[torch.Tensor, torch.Tensor]:
    return (
        _ds4_rmsnorm_reference(qr, q_weight, eps),
        _ds4_rmsnorm_reference(kv, kv_weight, eps),
    )


'''
    if "_ds4_should_fallback_fused_qk_rmsnorm" not in text:
        text, _ = _replace(
            text,
            "\ndef fused_q_kv_rmsnorm(\n",
            "\n" + helper + "def fused_q_kv_rmsnorm(\n",
            "fused_q_kv_rmsnorm reference helpers",
        )
    text = text.replace(
        "def _ds4_should_fallback_fused_qk_rmsnorm(exc: RuntimeError, ref: torch.Tensor) -> bool:",
        "def _ds4_should_fallback_fused_qk_rmsnorm(exc: BaseException, ref: torch.Tensor) -> bool:",
        1,
    )
    text = text.replace(
        '    if "Python.h" not in message and "Failed to compile launcher" not in message:\n'
        "        return False\n"
        "    if not ref.is_cuda or not torch.cuda.is_available():\n"
        "        return False\n"
        "    major, _minor = torch.cuda.get_device_capability(ref.device)\n"
        "    return major >= 12\n\n\n"
        "def _ds4_rmsnorm_reference(",
        '    if "Python.h" not in message and "Failed to compile launcher" not in message and "cuda_utils.c" not in message:\n'
        "        return False\n"
        "    return _ds4_is_sm12x_cuda(ref)\n\n\n"
        "def _ds4_is_sm12x_cuda(ref: torch.Tensor) -> bool:\n"
        "    if not ref.is_cuda or not torch.cuda.is_available():\n"
        "        return False\n"
        "    major, _minor = torch.cuda.get_device_capability(ref.device)\n"
        "    return major >= 12\n\n\n"
        "def _ds4_missing_python_header() -> bool:\n"
        '    sysconfig = __import__("sysconfig")\n'
        '    os_module = __import__("os")\n'
        "    os_path = os_module.path\n"
        '    for env_name in ("CPATH", "C_INCLUDE_PATH"):\n'
        '        for include_dir in os_module.environ.get(env_name, "").split(os_module.pathsep):\n'
        '            if include_dir and os_path.exists(os_path.join(include_dir, "Python.h")):\n'
        "                return False\n"
        '    include_dir = sysconfig.get_path("include")\n'
        "    if not include_dir:\n"
        "        return False\n"
        '    return not os_path.exists(os_path.join(include_dir, "Python.h"))\n\n\n'
        "def _ds4_should_use_fused_qk_rmsnorm_reference(ref: torch.Tensor) -> bool:\n"
        "    return _ds4_is_sm12x_cuda(ref) and _ds4_missing_python_header()\n\n\n"
        "def _ds4_rmsnorm_reference(",
        1,
    )
    text = text.replace(
        'def _ds4_missing_python_header() -> bool:\n'
        '    sysconfig = __import__("sysconfig")\n'
        '    os_path = __import__("os").path\n'
        '    include_dir = sysconfig.get_path("include")\n'
        '    if not include_dir:\n'
        '        return False\n'
        '    return not os_path.exists(os_path.join(include_dir, "Python.h"))\n',
        'def _ds4_missing_python_header() -> bool:\n'
        '    sysconfig = __import__("sysconfig")\n'
        '    os_module = __import__("os")\n'
        "    os_path = os_module.path\n"
        '    for env_name in ("CPATH", "C_INCLUDE_PATH"):\n'
        '        for include_dir in os_module.environ.get(env_name, "").split(os_module.pathsep):\n'
        '            if include_dir and os_path.exists(os_path.join(include_dir, "Python.h")):\n'
        "                return False\n"
        '    include_dir = sysconfig.get_path("include")\n'
        '    if not include_dir:\n'
        '        return False\n'
        '    return not os_path.exists(os_path.join(include_dir, "Python.h"))\n',
        1,
    )
    original_call = """    _fused_q_kv_rmsnorm_kernel[(num_tokens, 2)](
        qr,
        qr_out,
        q_weight,
        qr.stride(0),
        qr_out.stride(0),
        kv,
        kv_out,
        kv_weight,
        kv.stride(0),
        kv_out.stride(0),
        eps,
        Q_SIZE=q_size,
        KV_SIZE=kv_size,
        BLOCK_SIZE=block_size,
    )
    return qr_out, kv_out
"""
    patched_call = """    try:
        _fused_q_kv_rmsnorm_kernel[(num_tokens, 2)](
            qr,
            qr_out,
            q_weight,
            qr.stride(0),
            qr_out.stride(0),
            kv,
            kv_out,
            kv_weight,
            kv.stride(0),
            kv_out.stride(0),
            eps,
            Q_SIZE=q_size,
            KV_SIZE=kv_size,
            BLOCK_SIZE=block_size,
        )
    except Exception as exc:
        if not _ds4_should_fallback_fused_qk_rmsnorm(exc, qr):
            raise
        return _ds4_fused_q_kv_rmsnorm_reference(qr, kv, q_weight, kv_weight, eps)
    return qr_out, kv_out
"""
    if original_call in text:
        text = text.replace(original_call, patched_call, 1)
    elif "    except RuntimeError as exc:\n" in text and "_ds4_fused_q_kv_rmsnorm_reference" in text:
        pass
    elif patched_call not in text:
        raise PatchError("missing expected block: fused_q_kv_rmsnorm reference call site")
    text = text.replace("    except RuntimeError as exc:\n", "    except Exception as exc:\n", 1)
    text = text.replace(
        """    if num_tokens == 0:
        return qr_out, kv_out

    block_size = triton.next_power_of_2(max(q_size, kv_size))
""",
        """    if num_tokens == 0:
        return qr_out, kv_out
    if _ds4_should_use_fused_qk_rmsnorm_reference(qr):
        return _ds4_fused_q_kv_rmsnorm_reference(qr, kv, q_weight, kv_weight, eps)

    block_size = triton.next_power_of_2(max(q_size, kv_size))
""",
        1,
    )
    return text


def apply_patch(package_dir: Path, *, backup_suffix: str, write: bool) -> dict[str, Any]:
    path = package_dir / "v1" / "attention" / "ops" / "deepseek_v4_ops" / "fused_qk_rmsnorm.py"
    if not path.exists():
        raise PatchError(f"missing target file: {path}")
    original = path.read_text(encoding="utf-8")
    patched = patch_fused_qk_rmsnorm(original)
    files = {"fused_qk_rmsnorm": _write(path, original, patched, backup_suffix=backup_suffix, write=write)}
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
    parser.add_argument("--backup-suffix", default=".ds4_rmsnorm_reference_bak")
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
