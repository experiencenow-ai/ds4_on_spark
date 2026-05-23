#!/usr/bin/env python3

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


def get_dict(doc: dict[str, Any], key: str) -> Optional[dict[str, Any]]:
	val = doc.get(key, None)
	if isinstance(val, dict):
		return val
	return None


def get_list(doc: dict[str, Any], key: str) -> Optional[list[Any]]:
	val = doc.get(key, None)
	if isinstance(val, list):
		return val
	return None


def summarize_probe(doc: dict[str, Any]) -> str:
	arch = optional_string_field(doc, "architecture") or "(missing)"
	ok = doc.get("ok", None)
	return f"ok={ok!r} arch={arch}"


DERIVED_OVERLAP_KEYS = [
	"n_embd",
	"n_head",
	"n_head_dim",
	"n_hc",
	"n_lora_q",
	"n_expert",
	"n_ff_exp",
]


def main() -> int:
	parser = ArgumentParser()
	parser.add_argument("--contract-probe-json", type=str, required=True)
	parser.add_argument("--llamacpp-probe-json", type=str, required=True)
	parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary.")
	args = parser.parse_args()

	errors: list[str] = []
	warnings: list[str] = []

	contract_path = Path(args.contract_probe_json)
	llama_path = Path(args.llamacpp_probe_json)

	contract = load_json_object(contract_path, errors, "contract")
	llama = load_json_object(llama_path, errors, "llamacpp")
	if contract is None or llama is None:
		if args.json:
			return emit_json_result(errors, warnings)
		for e in errors:
			print(f"error: {e}")
		return 1

	if contract.get("ok", None) is not True:
		errors.append(f"contract probe is not ok: {summarize_probe(contract)}")
	if llama.get("ok", None) is not True:
		errors.append(f"llamacpp probe is not ok: {summarize_probe(llama)}")

	arch_contract = optional_string_field(contract, "architecture")
	arch_llama = optional_string_field(llama, "architecture")
	if arch_contract is not None and arch_llama is not None and arch_contract != arch_llama:
		errors.append(f"architecture mismatch: contract={arch_contract!r} llamacpp={arch_llama!r}")

	derived_contract = get_dict(contract, "derived_params") or {}
	derived_llama = get_dict(llama, "derived_params") or {}
	for k in DERIVED_OVERLAP_KEYS:
		a = optional_int_field(derived_contract, k)
		b = optional_int_field(derived_llama, k)
		if a is None or b is None:
			continue
		if int(a) != int(b):
			errors.append(f"derived_params mismatch for {k}: contract={a} llamacpp={b}")

	t_contract = get_list(contract, "tensors")
	t_llama = get_list(llama, "tensors")
	if t_contract is None:
		errors.append("contract: missing tensors[] list")
		t_contract = []
	if t_llama is None:
		errors.append("llamacpp: missing tensors[] list")
		t_llama = []

	contract_map: dict[str, dict[str, Any]] = {}
	for i, t in enumerate(t_contract):
		if not isinstance(t, dict):
			errors.append(f"contract: tensors[{i}] is not an object")
			continue
		name = optional_string_field(t, "name")
		if name is None:
			errors.append(f"contract: tensors[{i}] missing name")
			continue
		if name in contract_map:
			errors.append(f"contract: duplicate tensor name: {name}")
			continue
		contract_map[name] = t

	llama_map: dict[str, dict[str, Any]] = {}
	for i, t in enumerate(t_llama):
		if not isinstance(t, dict):
			errors.append(f"llamacpp: tensors[{i}] is not an object")
			continue
		name = optional_string_field(t, "name")
		if name is None:
			errors.append(f"llamacpp: tensors[{i}] missing name")
			continue
		if name in llama_map:
			errors.append(f"llamacpp: duplicate tensor name: {name}")
			continue
		llama_map[name] = t

	for name in sorted(contract_map.keys()):
		ct = contract_map[name]
		lt = llama_map.get(name, None)
		if lt is None:
			errors.append(f"llamacpp: missing tensor present in contract: {name}")
			continue

		present = lt.get("present", None)
		if present is not True:
			errors.append(f"llamacpp: tensor {name} present={present!r}, expected true")

		ct_dims = ct.get("dims", None)
		lt_dims = lt.get("dims", None)
		if isinstance(ct_dims, list) and isinstance(lt_dims, list) and ct_dims != lt_dims:
			errors.append(f"tensor dims mismatch for {name}: contract={ct_dims} llamacpp={lt_dims}")

		ct_type = optional_int_field(ct, "type_code")
		lt_type = optional_int_field(lt, "type")
		if ct_type is not None and lt_type is not None and int(ct_type) != int(lt_type):
			errors.append(f"tensor type mismatch for {name}: contract={ct_type} llamacpp={lt_type}")

		ct_nbytes = optional_int_field(ct, "payload_bytes")
		lt_nbytes = optional_int_field(lt, "nbytes")
		if ct_nbytes is not None and lt_nbytes is not None and int(ct_nbytes) != int(lt_nbytes):
			errors.append(f"tensor nbytes mismatch for {name}: contract={ct_nbytes} llamacpp={lt_nbytes}")

		ct_offs = optional_int_field(ct, "abs_offset")
		lt_offs = optional_int_field(lt, "offset")
		if ct_offs is not None and lt_offs is not None and int(ct_offs) != int(lt_offs):
			errors.append(f"tensor offset mismatch for {name}: contract={ct_offs} llamacpp={lt_offs}")

	extra_llama = sorted(set(llama_map.keys()) - set(contract_map.keys()))
	if extra_llama:
		warnings.append(f"llamacpp probe contains tensors not present in contract: {extra_llama}")

	if args.json:
		return emit_json_result(errors, warnings)

	for w in warnings[:64]:
		print(f"warning: {w}")
	for e in errors[:64]:
		print(f"error: {e}")
	print(f"ok: {str(len(errors) == 0).lower()}")
	return 0 if len(errors) == 0 else 1


if __name__ == "__main__":
	sys.exit(main())
