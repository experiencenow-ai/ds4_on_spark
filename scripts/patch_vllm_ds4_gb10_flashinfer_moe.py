#!/usr/bin/env python3
"""Opt-in vLLM patch to let GB10 try FlashInfer TRTLLM MXFP4 MoE."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from functools import partial
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
	sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._lib.vllm_patch_utils import replace_once


class PatchError(RuntimeError):
	pass


_replace = partial(replace_once, error_type=PatchError)


UNSAFE_WRITE_FLAG = "--unsafe-allow-gb10-flashinfer-runtime-failure"
UNSAFE_WRITE_DETAIL = (
	"The support gate can be forced on GB10, but the measured TP=2 startup "
	"selected FLASHINFER_TRTLLM_MXFP4_MXFP8 and then failed in FlashInfer "
	"0.6.11 trtllm_batched_gemm_runner.cu before API readiness."
)


def sha256_text(text: str) -> str:
	return(hashlib.sha256(text.encode("utf-8")).hexdigest())


def patch_trtllm_mxfp4_moe(text: str) -> str:
	text, _ = _replace(
		text,
		"import torch\n",
		"import os\n\nimport torch\n",
		"trtllm mxfp4 os import",
	)
	helper = """def _ds4_gb10_flashinfer_trtllm_moe_enabled() -> bool:
    if os.environ.get("DS4_VLLM_ENABLE_GB10_FLASHINFER_TRTLLM_MOE") != "1":
        return False
    if not current_platform.is_cuda():
        return False
    capability = current_platform.get_device_capability()
    if capability is None or capability.major != 12:
        return False
    try:
        device_name = torch.cuda.get_device_name()
    except Exception:
        device_name = ""
    return "GB10" in device_name.upper()


"""
	if helper not in text:
		text = text.replace("\n\nclass TrtLlmMxfp4ExpertsBase:\n", "\n\n" + helper + "class TrtLlmMxfp4ExpertsBase:\n", 1)
	old_support = """    @staticmethod
    def _supports_current_device() -> bool:
        p = current_platform
        return p.is_cuda() and p.is_device_capability_family(100) and has_flashinfer()
"""
	new_support = """    @staticmethod
    def _supports_current_device() -> bool:
        p = current_platform
        return (
            p.is_cuda()
            and has_flashinfer()
            and (
                p.is_device_capability_family(100)
                or _ds4_gb10_flashinfer_trtllm_moe_enabled()
            )
        )
"""
	text, _ = _replace(
		text,
		old_support,
		new_support,
		"trtllm mxfp4 current device support",
	)
	return(text)


def apply_patch(package_dir: Path, *, backup_suffix: str, write: bool) -> dict[str, Any]:
	targets = {
		"trtllm_mxfp4_moe": (
			package_dir / "model_executor" / "layers" / "fused_moe" / "experts" / "trtllm_mxfp4_moe.py",
			patch_trtllm_mxfp4_moe,
		),
	}
	files: dict[str, Any] = {}
	for name, (path, fn) in targets.items():
		if not path.exists():
			raise PatchError(f"missing file: {path}")
		before = path.read_text(encoding="utf-8")
		after = fn(before)
		changed = (after != before)
		files[name] = {
			"path": str(path),
			"changed": changed,
			"before_sha256": sha256_text(before),
			"after_sha256": sha256_text(after),
		}
		if write and changed:
			backup = path.with_name(path.name + backup_suffix)
			if not backup.exists():
				shutil.copy2(path, backup)
			path.write_text(after, encoding="utf-8")
	return({
		"patch_id": "ds4-vllm-gb10-flashinfer-trtllm-moe",
		"package_dir": str(package_dir),
		"changed": any(item["changed"] for item in files.values()),
		"files": files,
		"env_flag": "DS4_VLLM_ENABLE_GB10_FLASHINFER_TRTLLM_MOE=1",
	})


def main() -> int:
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("package_dir", type=Path)
	p.add_argument("--write", action="store_true")
	p.add_argument("--backup-suffix", default=".ds4gb10bak")
	p.add_argument(UNSAFE_WRITE_FLAG, action="store_true", help=argparse.SUPPRESS)
	args = p.parse_args()
	if args.write and not getattr(args, "unsafe_allow_gb10_flashinfer_runtime_failure"):
		p.error(f"refusing to write known GB10 FlashInfer runtime-failing prototype; pass {UNSAFE_WRITE_FLAG} only for isolated SM121 runtime experiments. {UNSAFE_WRITE_DETAIL}")
	result = apply_patch(args.package_dir, backup_suffix=args.backup_suffix, write=args.write)
	print(json.dumps(result, indent=2, sort_keys=True))
	return(0)


if __name__ == "__main__":
	raise SystemExit(main())
