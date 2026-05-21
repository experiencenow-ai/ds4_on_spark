#!/usr/bin/env python3
"""Patch vLLM MXFP4 MoE to prototype no-DP BatchedMarlin on DS4."""

from __future__ import annotations

import argparse
import difflib
import glob
import json
import shutil
from pathlib import Path
from typing import Any


PATCH_ID = "ds4-vllm-no-dp-batched-marlin-prototype"


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
	return({"path": str(path), "changed": changed, "diff": diff})


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
	return(Path(matches[0]))


def patch_config(text: str) -> str:
	text, _ = _replace(
		text,
		"from dataclasses import dataclass\n",
		"from dataclasses import dataclass\nimport os\n",
		"config os import",
	)
	text, _ = _replace(
		text,
		"""    @property
    def use_batched_activation_format(self):
        return self.use_deepep_ll_kernels or self.use_nixl_ep_kernels
""",
		"""    @property
    def use_batched_activation_format(self):
        return (
            self.use_deepep_ll_kernels
            or self.use_nixl_ep_kernels
            or (
                os.environ.get("DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN") == "1"
                and not self.use_all2all_kernels
                and self.dp_size == 1
            )
        )
""",
		"batched activation force gate",
	)
	return(text)


def patch_all2all_utils(text: str) -> str:
	text, _ = _replace(
		text,
		"from typing import Any\n",
		"import os\nfrom typing import Any\n",
		"all2all os import",
	)
	old_standard = """        else:
            return make_moe_prepare_and_finalize_no_dp_ep(use_monolithic)
"""
	old_global = """        else:
            if (
                os.environ.get("DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN") == "1"
                and not use_monolithic
                and moe.dp_size == 1
            ):
                from vllm.model_executor.layers.fused_moe.prepare_finalize.batched import (
                    BatchedPrepareAndFinalize,
                )

                logger.warning_once(
                    "DS4 forcing no-DP BatchedPrepareAndFinalize for MXFP4 MoE "
                    "prototype: global_experts=%d local_experts=%d max_tokens=%d",
                    moe.num_experts,
                    moe.num_local_experts,
                    moe.max_num_tokens,
                )
                return BatchedPrepareAndFinalize(
                    max_num_tokens=moe.max_num_tokens,
                    num_local_experts=moe.num_experts,
                    num_dispatchers=1,
                    rank=0,
                )
            return make_moe_prepare_and_finalize_no_dp_ep(use_monolithic)
"""
	new_local = """        else:
            if (
                os.environ.get("DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN") == "1"
                and not use_monolithic
                and moe.dp_size == 1
            ):
                from vllm.model_executor.layers.fused_moe.prepare_finalize.batched import (
                    BatchedPrepareAndFinalize,
                )

                logger.warning_once(
                    "DS4 forcing no-DP BatchedPrepareAndFinalize for MXFP4 MoE "
                    "prototype: global_experts=%d local_experts=%d ep_rank=%d "
                    "max_tokens=%d",
                    moe.num_experts,
                    moe.num_local_experts,
                    moe.ep_rank,
                    moe.max_num_tokens,
                )
                return BatchedPrepareAndFinalize(
                    max_num_tokens=moe.max_num_tokens,
                    num_local_experts=moe.num_local_experts,
                    num_dispatchers=1,
                    rank=moe.ep_rank,
                )
            return make_moe_prepare_and_finalize_no_dp_ep(use_monolithic)
"""
	if new_local not in text:
		if old_global in text:
			text = text.replace(old_global, new_local, 1)
		elif old_standard in text:
			text = text.replace(old_standard, new_local, 1)
		else:
			raise PatchError("missing expected block: no-DP batched prepare/finalize force")
	return(text)


def patch_marlin_moe(text: str) -> str:
	text = text.replace(
		"from collections.abc import Callable\nimport os\n",
		"from collections.abc import Callable\n",
	)
	old_global = """        num_dispatchers = self.num_dispatchers
        num_experts = (
            global_num_experts
            if os.environ.get("DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN") == "1"
            else local_num_experts
        )
        max_num_tokens = self.max_num_tokens
"""
	new_local = """        num_dispatchers = self.num_dispatchers
        num_experts = local_num_experts
        max_num_tokens = self.max_num_tokens
"""
	if old_global in text:
		text = text.replace(old_global, new_local, 1)
	elif new_local not in text:
		raise PatchError("missing expected block: batched marlin local expert workspace")
	return(text)


def patch_batched_prepare_finalize(text: str) -> str:
	text, _ = _replace(
		text,
		"import torch\n",
		"import os\nimport torch\n",
		"batched prepare/finalize os import",
	)
	old_standard = """        tokens_per_expert = torch.zeros(num_experts, dtype=torch.int, device=a1.device)

        num_local_experts = self.num_local_experts
"""
	new_local_counter = """        num_local_experts = self.num_local_experts
        token_counter_experts = (
            num_local_experts
            if os.environ.get("DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN") == "1"
            else num_experts
        )
        tokens_per_expert = torch.zeros(
            token_counter_experts,
            dtype=torch.int,
            device=a1.device,
        )
"""
	if new_local_counter not in text:
		if old_standard in text:
			text = text.replace(old_standard, new_local_counter, 1)
		else:
			raise PatchError("missing expected block: batched prepare local token counter")
	return(text)


def apply_patch(package_dir: Path, *, backup_suffix: str, write: bool) -> dict[str, Any]:
	targets = {
		"config": (
			package_dir / "model_executor" / "layers" / "fused_moe" / "config.py",
			patch_config,
		),
		"all2all_utils": (
			package_dir / "model_executor" / "layers" / "fused_moe" / "all2all_utils.py",
			patch_all2all_utils,
		),
		"marlin_moe": (
			package_dir / "model_executor" / "layers" / "fused_moe" / "experts" / "marlin_moe.py",
			patch_marlin_moe,
		),
		"batched_prepare_finalize": (
			package_dir / "model_executor" / "layers" / "fused_moe" / "prepare_finalize" / "batched.py",
			patch_batched_prepare_finalize,
		),
	}
	files: dict[str, Any] = {}
	for name, (path, fn) in targets.items():
		if not path.exists():
			raise PatchError(f"missing target file: {path}")
		original = path.read_text(encoding="utf-8")
		patched = fn(original)
		files[name] = _write(path, original, patched, backup_suffix=backup_suffix, write=write)
	return({
		"patch_id": PATCH_ID,
		"package_dir": str(package_dir),
		"env_flag": "DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN=1",
		"write": write,
		"changed": any(item["changed"] for item in files.values()),
		"files": files,
	})


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--runtime-root")
	parser.add_argument("--vllm-package-dir")
	parser.add_argument("--backup-suffix", default=".ds4_no_dp_batched_marlin_bak")
	parser.add_argument("--check", action="store_true", help="Show whether changes are needed without writing.")
	args = parser.parse_args()
	package_dir = locate_package_dir(
		Path(args.runtime_root).expanduser() if args.runtime_root else None,
		Path(args.vllm_package_dir).expanduser() if args.vllm_package_dir else None,
	)
	result = apply_patch(package_dir, backup_suffix=args.backup_suffix, write=not args.check)
	print(json.dumps(result, indent=2, sort_keys=True))
	return(0)


if __name__ == "__main__":
	raise SystemExit(main())
