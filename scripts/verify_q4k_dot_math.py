#!/usr/bin/env python3

import base64
import json
import math
import struct
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Optional


Q4K_QK = 256
Q4K_BLOCK_BYTES = 144  # 2*f16 + scales[12] + qs[128]


def f16_to_f32(u: int) -> float:
	s = (u >> 15) & 1
	e = (u >> 10) & 0x1F
	f = u & 0x03FF
	if e == 0:
		if f == 0:
			return -0.0 if s else 0.0
		return ((-1.0 if s else 1.0) * (2.0 ** (-14.0)) * (float(f) / 1024.0))
	if e == 31:
		if f == 0:
			return float("-inf") if s else float("inf")
		return float("nan")
	return ((-1.0 if s else 1.0) * (2.0 ** float(e - 15)) * (1.0 + (float(f) / 1024.0)))


def fnv1a64(b: bytes) -> str:
	h = 1469598103934665603
	for x in b:
		h ^= int(x)
		h = ((h * 1099511628211) & 0xFFFFFFFFFFFFFFFF)
	return f"{h:016x}"


def decode_scales_cuda_style(scales: bytes) -> tuple[list[int], list[int]]:
	if len(scales) != 12:
		raise ValueError(f"expected scales[12], got {len(scales)} bytes")
	u0 = int.from_bytes(scales[0:4], "little", signed=False)
	u1 = int.from_bytes(scales[4:8], "little", signed=False)
	u2 = int.from_bytes(scales[8:12], "little", signed=False)
	kmask1 = 0x3F3F3F3F
	kmask2 = 0x0F0F0F0F
	kmask3 = 0x03030303
	sc0 = u0 & kmask1
	sc1 = (u2 & kmask2) | (((u0 >> 6) & kmask3) << 4)
	mn0 = u1 & kmask1
	mn1 = ((u2 >> 4) & kmask2) | (((u1 >> 6) & kmask3) << 4)

	def u32_byte(v: int, i: int) -> int:
		return int((v >> (8 * i)) & 0xFF)

	sc = [u32_byte(sc0, i) for i in range(4)] + [u32_byte(sc1, i) for i in range(4)]
	mn = [u32_byte(mn0, i) for i in range(4)] + [u32_byte(mn1, i) for i in range(4)]
	return (sc, mn)


def decode_scales_explicit(scales: bytes) -> tuple[list[int], list[int]]:
	if len(scales) != 12:
		raise ValueError(f"expected scales[12], got {len(scales)} bytes")
	sc = [0] * 8
	mn = [0] * 8
	for i in range(4):
		sc[i] = int(scales[i] & 0x3F)
		mn[i] = int(scales[4 + i] & 0x3F)
		sc[4 + i] = int((scales[8 + i] & 0x0F) | (((scales[i] >> 6) & 0x03) << 4))
		mn[4 + i] = int(((scales[8 + i] >> 4) & 0x0F) | (((scales[4 + i] >> 6) & 0x03) << 4))
	return (sc, mn)


def dequant_q4k_block(block: bytes) -> tuple[float, float, list[int], list[int], list[float]]:
	if len(block) != Q4K_BLOCK_BYTES:
		raise ValueError(f"expected block_q4_K bytes={Q4K_BLOCK_BYTES}, got {len(block)}")
	(d_u16, dmin_u16) = struct.unpack("<HH", block[0:4])
	d = f16_to_f32(int(d_u16))
	dmin = f16_to_f32(int(dmin_u16))
	scales = block[4:16]
	qs = block[16:]
	if len(qs) != (Q4K_QK // 2):
		raise ValueError(f"expected qs bytes={Q4K_QK//2}, got {len(qs)}")

	(sc0, mn0) = decode_scales_cuda_style(scales)
	(sc1, mn1) = decode_scales_explicit(scales)
	if sc0 != sc1 or mn0 != mn1:
		raise ValueError("scale/min unpack mismatch (cuda_style vs explicit)")

	out = [0.0] * Q4K_QK
	for g in range(8):
		scale = d * float(sc0[g])
		minv = dmin * float(mn0[g])
		base = (g // 2) * 32
		for i in range(32):
			packed = int(qs[base + i])
			q = float((packed >> 4) if (g & 1) else (packed & 0x0F))
			out[(g * 32) + i] = (scale * q) - minv
	return (d, dmin, sc0, mn0, out)


def dot_q4k_f32_stream(block: bytes, x: list[float]) -> float:
	if len(x) != Q4K_QK:
		raise ValueError(f"expected x len={Q4K_QK}, got {len(x)}")
	(d, dmin, sc, mn, _) = dequant_q4k_block(block)
	qs = block[16:]
	acc = 0.0
	for g in range(8):
		scale = d * float(sc[g])
		minv = dmin * float(mn[g])
		base = (g // 2) * 32
		for i in range(32):
			packed = int(qs[base + i])
			q = float((packed >> 4) if (g & 1) else (packed & 0x0F))
			acc += ((scale * q) - minv) * float(x[(g * 32) + i])
	return float(acc)


def dot_q4k_f32_ref(block: bytes, x: list[float]) -> float:
	if len(x) != Q4K_QK:
		raise ValueError(f"expected x len={Q4K_QK}, got {len(x)}")
	(_, _, _, _, w) = dequant_q4k_block(block)
	acc = 0.0
	for i in range(Q4K_QK):
		acc += float(w[i]) * float(x[i])
	return float(acc)


def lcg_f32(seed: int, n: int) -> list[float]:
	# Deterministic float generator (no dependency on Python's random module).
	state = int(seed) & 0xFFFFFFFF
	out: list[float] = []
	for _ in range(int(n)):
		state = (1664525 * state + 1013904223) & 0xFFFFFFFF
		u = float(state) / 4294967296.0
		out.append((2.0 * u) - 1.0)
	return out


def load_json_obj(path: Path) -> dict[str, Any]:
	try:
		with path.open("r", encoding="utf-8") as f:
			doc = json.load(f)
	except Exception as e:
		raise ValueError(f"failed to load JSON {path}: {e}") from e
	if not isinstance(doc, dict):
		raise ValueError(f"JSON {path} top-level is not an object")
	return doc


def get_payload_sample_block(doc: dict[str, Any], tensor: str) -> bytes:
	ps = doc.get("payload_samples", None)
	if not isinstance(ps, dict):
		raise ValueError("probe JSON missing payload_samples (run model_contract_probe_mtp_sidecar.py with --payload-sample-bytes and --payload-sample-include-bytes)")
	entry = ps.get(tensor, None)
	if not isinstance(entry, dict):
		raise ValueError(f"probe JSON missing payload sample for tensor {tensor}")
	b64 = entry.get("bytes_b64", None)
	if not isinstance(b64, str) or not b64:
		raise ValueError(f"payload_samples[{tensor}].bytes_b64 missing (set --payload-sample-include-bytes)")
	raw = base64.b64decode(b64)
	if len(raw) < Q4K_BLOCK_BYTES:
		raise ValueError(f"payload sample too short for q4_K block: got {len(raw)} bytes, need {Q4K_BLOCK_BYTES}")
	return raw[:Q4K_BLOCK_BYTES]


def main() -> int:
	parser = ArgumentParser()
	parser.add_argument("--probe-json", type=str, default="", help="JSON output from scripts/model_contract_probe_mtp_sidecar.py with --payload-sample-include-bytes.")
	parser.add_argument("--tensor", type=str, default="mtp.0.ffn_gate_exps.weight", help="Tensor name to extract the first q4_K block from.")
	parser.add_argument("--block-b64", type=str, default="", help="Base64-encoded q4_K block bytes (144 bytes decoded).")
	parser.add_argument("--x-seed", type=int, default=1, help="Seed for deterministic x[256] float vector.")
	parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
	args = parser.parse_args()

	block: Optional[bytes] = None
	src: str = ""
	if args.block_b64:
		raw = base64.b64decode(str(args.block_b64))
		if len(raw) != Q4K_BLOCK_BYTES:
			raise SystemExit(f"--block-b64 decoded bytes={len(raw)}, expected {Q4K_BLOCK_BYTES}")
		block = raw
		src = "block_b64"
	elif args.probe_json:
		doc = load_json_obj(Path(str(args.probe_json)))
		block = get_payload_sample_block(doc, str(args.tensor))
		src = f"probe_json:{args.tensor}"
	else:
		raise SystemExit("must provide --probe-json or --block-b64")

	x = lcg_f32(int(args.x_seed), Q4K_QK)
	(d, dmin, sc, mn, _) = dequant_q4k_block(block)
	dot_stream = dot_q4k_f32_stream(block, x)
	dot_ref = dot_q4k_f32_ref(block, x)
	abs_err = abs(dot_stream - dot_ref)
	rel_err = abs_err / max(1.0e-12, abs(dot_ref))
	ok = (math.isfinite(dot_stream) and math.isfinite(dot_ref) and abs_err <= 1.0e-6 and rel_err <= 1.0e-6)

	if args.json:
		out = {
			"ok": bool(ok),
			"src": str(src),
			"block_fnv1a64": fnv1a64(block),
			"d": float(d),
			"dmin": float(dmin),
			"scales": [int(x) for x in sc],
			"mins": [int(x) for x in mn],
			"dot_stream": float(dot_stream),
			"dot_ref": float(dot_ref),
			"abs_err": float(abs_err),
			"rel_err": float(rel_err),
		}
		print(json.dumps(out, indent=2, sort_keys=True))
	else:
		print(f"src={src}")
		print(f"block_fnv1a64={fnv1a64(block)}")
		print(f"d={d} dmin={dmin}")
		print(f"scales={sc} mins={mn}")
		print(f"dot_stream={dot_stream}")
		print(f"dot_ref={dot_ref}")
		print(f"abs_err={abs_err} rel_err={rel_err}")
		print(f"ok={str(bool(ok)).lower()}")

	return 0 if ok else 1


if __name__ == "__main__":
	sys.exit(main())

