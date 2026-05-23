#!/usr/bin/env python3

import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Optional

if __package__ in (None, ""):
	sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._lib.json_utils import emit_json_result
from scripts._lib.json_utils import load_json_object
from scripts._lib.json_utils import optional_int_field
from scripts._lib.json_utils import optional_string_field


def samples_as_map(doc: dict[str, Any], errors: list[str], label: str) -> dict[str, dict[str, Any]]:
	val = doc.get("payload_samples", None)
	if val is None:
		errors.append(f"{label}: missing payload_samples (run the probe with --payload-sample-bytes N)")
		return {}
	if isinstance(val, dict):
		out: dict[str, dict[str, Any]] = {}
		for k, v in val.items():
			if not isinstance(k, str) or not isinstance(v, dict):
				continue
			out[k] = v
		if not out:
			errors.append(f"{label}: payload_samples is empty or not a map of name->object")
		return out
	if isinstance(val, list):
		out = {}
		for item in val:
			if not isinstance(item, dict):
				continue
			name = item.get("name", None)
			if not isinstance(name, str) or name == "":
				continue
			out[name] = item
		if not out:
			errors.append(f"{label}: payload_samples is empty or not a list of objects with name fields")
		return out
	errors.append(f"{label}: payload_samples has type {type(val).__name__}, expected object or list")
	return {}


def get_sample_fields(sample: dict[str, Any]) -> tuple[Optional[int], Optional[str], Optional[int]]:
	n = sample.get("n", None)
	fnv = sample.get("fnv1a64", None)
	off = sample.get("offset", None)
	if not isinstance(n, int):
		n = None
	if not isinstance(fnv, str):
		fnv = None
	if not isinstance(off, int):
		off = None
	return (n, fnv, off)


def main() -> int:
	parser = ArgumentParser(description="Compare MTP sidecar payload sample fingerprints against a pinned reference.")
	parser.add_argument("--probe-json", type=str, required=True, help="Path to scripts/model_contract_probe_mtp_sidecar.py --json output.")
	parser.add_argument(
		"--reference-json",
		type=str,
		default="docs/mtp-sidecar-probe-antirez-3274cdc-payload64.json",
		help="Pinned reference JSON containing payload_samples.",
	)
	parser.add_argument(
		"--require-offset-match",
		action="store_true",
		help="Require sample offsets to match the reference (default: warn only).",
	)
	parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary.")
	args = parser.parse_args()

	errors: list[str] = []
	warnings: list[str] = []

	probe_path = Path(args.probe_json)
	ref_path = Path(args.reference_json)

	probe = load_json_object(probe_path, errors, "probe")
	ref = load_json_object(ref_path, errors, "reference")
	if probe is None or ref is None:
		if args.json:
			return emit_json_result(errors, warnings)
		for e in errors:
			print(f"error: {e}")
		return 1

	if probe.get("ok", None) is not True:
		warnings.append(f"probe ok={probe.get('ok', None)!r} (fingerprint compare may be meaningless on failing probes)")
	if ref.get("ok", None) is not True:
		warnings.append(f"reference ok={ref.get('ok', None)!r} (unexpected: pinned reference should be ok=true)")

	arch_probe = optional_string_field(probe, "architecture")
	arch_ref = optional_string_field(ref, "architecture")
	if arch_probe is not None and arch_ref is not None and arch_probe != arch_ref:
		errors.append(f"architecture mismatch: probe={arch_probe!r} reference={arch_ref!r}")

	s_probe = samples_as_map(probe, errors, "probe")
	s_ref = samples_as_map(ref, errors, "reference")
	if not s_probe or not s_ref:
		if args.json:
			return emit_json_result(errors, warnings)
		for w in warnings[:64]:
			print(f"warning: {w}")
		for e in errors[:64]:
			print(f"error: {e}")
		print(f"ok: {str(len(errors) == 0).lower()}")
		return 0 if len(errors) == 0 else 1

	want_sample_bytes = optional_int_field(ref, "payload_sample_bytes")
	got_sample_bytes = optional_int_field(probe, "payload_sample_bytes")
	if want_sample_bytes is not None and got_sample_bytes is not None and int(want_sample_bytes) != int(got_sample_bytes):
		errors.append(f"payload_sample_bytes mismatch: probe={got_sample_bytes} reference={want_sample_bytes}")
	elif want_sample_bytes is not None and got_sample_bytes is None:
		warnings.append(f"probe missing payload_sample_bytes (reference expects {want_sample_bytes})")

	ref_names = set(s_ref.keys())
	probe_names = set(s_probe.keys())

	missing = sorted(ref_names - probe_names)
	extra = sorted(probe_names - ref_names)
	if missing:
		errors.append(f"missing {len(missing)} reference payload sample(s) (e.g. {missing[0]!r})")
	if extra:
		warnings.append(f"probe has {len(extra)} extra payload sample(s) not in reference (e.g. {extra[0]!r})")

	mismatches: list[dict[str, Any]] = []
	offset_mismatches: list[dict[str, Any]] = []
	for name in sorted(ref_names & probe_names):
		(n_ref, fnv_ref, off_ref) = get_sample_fields(s_ref[name])
		(n_probe, fnv_probe, off_probe) = get_sample_fields(s_probe[name])
		if n_ref is None or fnv_ref is None:
			errors.append(f"reference sample for {name} missing n/fnv1a64")
			continue
		if n_probe is None or fnv_probe is None:
			errors.append(f"probe sample for {name} missing n/fnv1a64")
			continue
		if int(n_ref) != int(n_probe) or str(fnv_ref) != str(fnv_probe):
			mismatches.append(
				{
					"name": name,
					"probe": {"n": n_probe, "fnv1a64": fnv_probe, "offset": off_probe},
					"reference": {"n": n_ref, "fnv1a64": fnv_ref, "offset": off_ref},
				}
			)
			continue
		if off_ref is not None and off_probe is not None and int(off_ref) != int(off_probe):
			offset_mismatches.append({"name": name, "probe_offset": int(off_probe), "reference_offset": int(off_ref)})

	if mismatches:
		errors.append(f"{len(mismatches)} payload sample mismatch(es) (fnv1a64 and/or n differ)")
	if offset_mismatches:
		msg = f"{len(offset_mismatches)} payload sample offset mismatch(es)"
		if args.require_offset_match:
			errors.append(msg)
		else:
			warnings.append(msg)

	if args.json:
		out = {
			"ok": (len(errors) == 0),
			"errors": errors,
			"warnings": warnings,
			"probe_json": str(probe_path),
			"reference_json": str(ref_path),
			"payload_sample_bytes_probe": got_sample_bytes,
			"payload_sample_bytes_reference": want_sample_bytes,
			"missing_samples": missing,
			"extra_samples": extra[:64],
			"mismatches": mismatches[:64],
			"offset_mismatches": offset_mismatches[:64],
		}
		print(json.dumps(out, indent=2, sort_keys=True))
		return 0 if out["ok"] else 1

	for w in warnings[:64]:
		print(f"warning: {w}")
	for e in errors[:64]:
		print(f"error: {e}")
	print(f"ok: {str(len(errors) == 0).lower()}")
	return 0 if len(errors) == 0 else 1


if __name__ == "__main__":
	sys.exit(main())
