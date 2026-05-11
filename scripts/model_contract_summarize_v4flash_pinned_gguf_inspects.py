#!/usr/bin/env python3

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOCS_DIR = ROOT / "docs"
DEFAULT_OUT = ROOT / "fixtures" / "model_contract" / "deepseek_v4_flash" / "pinned_gguf_inspects_summary.json"

PINNED_DOCS = [
	"gguf-inspect-preyazz-6c6d74c-q4-k-m.json",
	"gguf-inspect-nsparks-0b34e0b-fp4-fp8-native.json",
	"gguf-inspect-antirez-b0c3326-iq2xxs-chat-v2.json",
	"gguf-inspect-antirez-b0c3326-mtp-sidecar.json",
	"gguf-inspect-antirez-b0c3326-iq2xxs-chat-v2-mtp-set.json",
]


def load_json(path: Path) -> Any:
	with path.open("r", encoding="utf-8") as f:
		return json.load(f)


def dump_json(path: Path, obj: Any) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp = path.with_suffix(path.suffix + ".tmp")
	with tmp.open("w", encoding="utf-8") as f:
		json.dump(obj, f, indent=2, sort_keys=True)
		f.write("\n")
	tmp.replace(path)


def _get_bool(obj: Any, key: str) -> Optional[bool]:
	if not isinstance(obj, dict):
		return None
	v = obj.get(key)
	if isinstance(v, bool):
		return v
	return None


def _get_str(obj: Any, key: str) -> Optional[str]:
	if not isinstance(obj, dict):
		return None
	v = obj.get(key)
	if isinstance(v, str):
		return v
	return None


def _get_int(obj: Any, key: str) -> Optional[int]:
	if not isinstance(obj, dict):
		return None
	v = obj.get(key)
	if isinstance(v, int):
		return int(v)
	return None


def summarize_quantization_contract(qc: Any) -> Optional[dict[str, Any]]:
	if not isinstance(qc, dict) or qc.get("checked") is not True:
		return None
	return {
		"dense_fp8_like": _get_bool(qc, "dense_fp8_like"),
		"expert_fp4_like": _get_bool(qc, "expert_fp4_like"),
		"observed": qc.get("observed"),
		"expected": qc.get("expected"),
	}


def summarize_topology_contract(tc: Any) -> Optional[dict[str, Any]]:
	if not isinstance(tc, dict) or tc.get("checked") is not True:
		return None
	mismatches = tc.get("mismatches", [])
	if not isinstance(mismatches, list):
		mismatches = []
	return {
		"block_count_ok": _get_bool(tc, "block_count_ok"),
		"mismatch_count": int(len(mismatches)),
		"mismatches_sample": list(mismatches)[:10],
	}


def summarize_mtp_contract(mc: Any) -> Optional[dict[str, Any]]:
	if not isinstance(mc, dict) or mc.get("checked") is not True:
		return None
	return {
		"complete": _get_bool(mc, "complete"),
		"missing_required_count": _get_int(mc, "missing_required_count"),
		"forbidden_present_count": int(len(list(mc.get("forbidden_present", []) or []))),
	}


def summarize_mtp_trust(mt: Any) -> Optional[dict[str, Any]]:
	if not isinstance(mt, dict) or mt.get("checked") is not True:
		return None
	reasons = mt.get("reasons", [])
	if not isinstance(reasons, list):
		reasons = []
	return {
		"status": _get_str(mt, "status"),
		"trusted": _get_bool(mt, "trusted"),
		"reasons_sample": list(reasons)[:10],
	}


def summarize_mtp_preservation(mp: Any) -> Optional[dict[str, Any]]:
	if not isinstance(mp, dict) or mp.get("checked") is not True:
		return None
	reasons = mp.get("reasons", [])
	if not isinstance(reasons, list):
		reasons = []
	return {
		"status": _get_str(mp, "status"),
		"preserves": _get_bool(mp, "preserves"),
		"reasons_sample": list(reasons)[:10],
	}


def summarize_single_doc(doc_obj: dict[str, Any], rel_path: str) -> dict[str, Any]:
	return {
		"doc_path": rel_path,
		"artifact_type": _get_str(doc_obj, "artifact_type"),
		"path": _get_str(doc_obj, "path"),
		"tensor_key_namespace_guess": _get_str(doc_obj, "tensor_key_namespace_guess"),
		"weight_keys_sha256": _get_str(doc_obj, "weight_keys_sha256"),
		"mtp_present": _get_bool(doc_obj, "mtp_present"),
		"mtp_tensor_count": _get_int(doc_obj, "mtp_tensor_count"),
		"mtp_keys_sha256": _get_str(doc_obj, "mtp_keys_sha256"),
		"mtp_contract": summarize_mtp_contract(doc_obj.get("mtp_contract")),
		"mtp_preservation": summarize_mtp_preservation(doc_obj.get("mtp_preservation")),
		"mtp_trust": summarize_mtp_trust(doc_obj.get("mtp_trust")),
		"quantization_contract": summarize_quantization_contract(doc_obj.get("quantization_contract")),
		"topology_contract": summarize_topology_contract(doc_obj.get("topology_contract")),
	}


def summarize_combined_doc(doc_obj: dict[str, Any], rel_path: str) -> dict[str, Any]:
	combined = doc_obj.get("combined", {})
	if not isinstance(combined, dict):
		combined = {}
	return {
		"doc_path": rel_path,
		"artifact_set": True,
		"paths": combined.get("paths"),
		"weight_keys_union_sha256": _get_str(combined, "weight_keys_union_sha256"),
		"mtp_present": _get_bool(combined, "mtp_present"),
		"mtp_keys_union_sha256": _get_str(combined, "mtp_keys_union_sha256"),
		"mtp_contract": summarize_mtp_contract(combined.get("mtp_contract")),
		"mtp_preservation": summarize_mtp_preservation(combined.get("mtp_preservation")),
		"mtp_trust": summarize_mtp_trust(combined.get("mtp_trust")),
		"quantization_contract": summarize_quantization_contract(combined.get("quantization_contract")),
		"topology_contract": summarize_topology_contract(combined.get("topology_contract")),
	}


def build_summary(docs_dir: Path, generated_at_utc: Optional[str]) -> dict[str, Any]:
	if generated_at_utc is None:
		generated_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
	items: list[dict[str, Any]] = []
	for name in PINNED_DOCS:
		path = (docs_dir / name).resolve()
		if not path.exists():
			raise FileNotFoundError(f"missing pinned inspect doc: {path}")
		obj = load_json(path)
		try:
			rel = str(path.relative_to(ROOT))
		except Exception:
			rel = str(path)
		if isinstance(obj, dict) and "combined" in obj and "artifacts" in obj:
			items.append(summarize_combined_doc(obj, rel))
		elif isinstance(obj, dict):
			items.append(summarize_single_doc(obj, rel))
		else:
			raise ValueError(f"unexpected JSON root (expected object) in {path}")
	return {
		"generated_at_utc": generated_at_utc,
		"pinned_docs": list(PINNED_DOCS),
		"items": items,
	}


def main() -> int:
	ap = argparse.ArgumentParser(description="Summarize pinned DeepSeek V4 Flash GGUF inspect JSONs into a small machine-readable fixture.")
	ap.add_argument("--docs-dir", default=str(DEFAULT_DOCS_DIR), help="Directory containing gguf-inspect-*.json docs (default: docs/).")
	ap.add_argument("--out", default=str(DEFAULT_OUT), help="Output JSON path (default: fixtures/model_contract/deepseek_v4_flash/pinned_gguf_inspects_summary.json).")
	ap.add_argument("--check", action="store_true", help="Fail if --out is missing or stale instead of rewriting it.")
	args = ap.parse_args()

	docs_dir = Path(args.docs_dir).resolve()
	out_path = Path(args.out)

	if args.check:
		if not out_path.exists():
			raise SystemExit(f"missing summary fixture: {out_path}")
		current = load_json(out_path)
		current_generated_at = None
		if isinstance(current, dict):
			v = current.get("generated_at_utc")
			if isinstance(v, str) and v:
				current_generated_at = v
		summary = build_summary(docs_dir, current_generated_at)
		if current != summary:
			raise SystemExit(f"stale summary fixture: {out_path} (re-run {Path(__file__).name})")
		return 0

	summary = build_summary(docs_dir, None)
	dump_json(out_path, summary)
	print(f"OK: wrote pinned GGUF inspect summary to {out_path}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
