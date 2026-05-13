#!/usr/bin/env python3
"""Validate the Q4_K dot-product math used by the antirez/ds4 CUDA fallback.

This is a *host-side* math check only.

It compares two equivalent implementations:

1) A direct translation of ggml's `dequantize_row_q4_K` (+ dot).
2) A direct translation of the CUDA helper in `docs/antirez-patches/*q4k*.patch`.

This does not require CUDA, a GPU, or any model weights.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import struct

QK_K = 256


def f16_to_f32(bits_u16: int) -> float:
    return struct.unpack("e", struct.pack("H", bits_u16 & 0xFFFF))[0]


def f32(x: float) -> float:
    # Round to IEEE754 float32 (matches ggml's float math behavior).
    return struct.unpack("f", struct.pack("f", float(x)))[0]


def get_scale_min_k4(j: int, scales: bytes) -> tuple[int, int]:
    if j < 4:
        d = scales[j] & 63
        m = scales[j + 4] & 63
        return d, m
    d = (scales[j + 4] & 0xF) | (((scales[j - 4] >> 6) & 0x3) << 4)
    m = (scales[j + 4] >> 4) | (((scales[j - 0] >> 6) & 0x3) << 4)
    return d, m


def unpack_scales_mins_k4(scales: bytes) -> tuple[list[int], list[int]]:
    if len(scales) != 12:
        raise ValueError("expected scales[12]")

    d = [0] * 8
    m = [0] * 8

    # Indices 0..3: low 6 bits are stored directly.
    for j in range(4):
        d[j] = int(scales[j] & 63)
        m[j] = int(scales[j + 4] & 63)

    # Indices 4..7: low 4 bits come from scales[8..11], high 2 bits are packed
    # into the top two bits of the earlier bytes.
    for j in range(4, 8):
        d[j] = int((scales[j + 4] & 0x0F) | (((scales[j - 4] >> 6) & 0x03) << 4))
        m[j] = int((scales[j + 4] >> 4) | (((scales[j - 0] >> 6) & 0x03) << 4))

    return d, m


def _u32le(b: bytes) -> int:
    if len(b) != 4:
        raise ValueError("expected 4 bytes")
    return int.from_bytes(b, "little", signed=False)


def patch_unpack_scales_mins_k4(scales: bytes) -> tuple[list[int], list[int]]:
    """Match the antirez/ds4 CUDA patch's unpacking for scales/mins.

    The patch reads scales with u32 loads + bit masks and expands to 8 scale
    bytes + 8 min bytes (each 0..63).
    """
    if len(scales) != 12:
        raise ValueError("expected scales[12]")

    u0 = _u32le(scales[0:4])
    u1 = _u32le(scales[4:8])
    u2 = _u32le(scales[8:12])

    kmask1 = 0x3F3F3F3F
    kmask2 = 0x0F0F0F0F
    kmask3 = 0x03030303

    sc0 = u0 & kmask1
    sc1 = (u2 & kmask2) | (((u0 >> 6) & kmask3) << 4)
    mn0 = u1 & kmask1
    mn1 = ((u2 >> 4) & kmask2) | (((u1 >> 6) & kmask3) << 4)

    sbytes = sc0.to_bytes(4, "little") + sc1.to_bytes(4, "little")
    mbytes = mn0.to_bytes(4, "little") + mn1.to_bytes(4, "little")
    d = [int(x) for x in sbytes]
    m = [int(x) for x in mbytes]
    if len(d) != 8 or len(m) != 8:
        raise AssertionError("bad unpack length")
    return d, m


def ggml_dequantize_row_q4_k(scales: bytes, qs: bytes, d_bits: int, dmin_bits: int) -> list[float]:
    if len(scales) != 12:
        raise ValueError("expected scales[12]")
    if len(qs) != QK_K // 2:
        raise ValueError("expected qs[128]")

    d = f32(f16_to_f32(d_bits))
    mn = f32(f16_to_f32(dmin_bits))

    out: list[float] = []
    q_off = 0
    is_ = 0
    for j in range(0, QK_K, 64):
        sc0, m0 = get_scale_min_k4(is_ + 0, scales)
        sc1, m1 = get_scale_min_k4(is_ + 1, scales)
        d1 = f32(d * float(sc0))
        m1f = f32(mn * float(m0))
        d2 = f32(d * float(sc1))
        m2f = f32(mn * float(m1))
        # 32 bytes => 64 nibbles
        q = qs[q_off : q_off + 32]
        out.extend([f32(f32(d1 * float(b & 0xF)) - m1f) for b in q])
        out.extend([f32(f32(d2 * float(b >> 4)) - m2f) for b in q])
        q_off += 32
        is_ += 2

    if len(out) != QK_K:
        raise AssertionError("bad dequant length")
    return out


def cuda_style_dot_q4_k(scales: bytes, qs: bytes, d_bits: int, dmin_bits: int, x: list[float]) -> float:
    if len(x) != QK_K:
        raise ValueError("expected x[256]")

    d = f32(f16_to_f32(d_bits))
    mn = f32(f16_to_f32(dmin_bits))

    d_scales, m_scales = unpack_scales_mins_k4(scales)

    acc = 0.0
    q_off = 0
    is_ = 0
    for j in range(0, QK_K, 64):
        d1 = f32(d * float(d_scales[is_ + 0]))
        m1f = f32(mn * float(m_scales[is_ + 0]))
        d2 = f32(d * float(d_scales[is_ + 1]))
        m2f = f32(mn * float(m_scales[is_ + 1]))
        q = qs[q_off : q_off + 32]
        for l, b in enumerate(q):
            w = f32(f32(d1 * float(b & 0xF)) - m1f)
            acc += f32(w * f32(x[j + l]))
        for l, b in enumerate(q):
            w = f32(f32(d2 * float(b >> 4)) - m2f)
            acc += f32(w * f32(x[j + 32 + l]))
        q_off += 32
        is_ += 2

    return acc


def cuda_patch_style_dot_q4_k(scales: bytes, qs: bytes, d_bits: int, dmin_bits: int, x: list[float]) -> float:
    """Match the antirez/ds4 CUDA patch's dot kernel indexing."""
    if len(x) != QK_K:
        raise ValueError("expected x[256]")
    if len(scales) != 12:
        raise ValueError("expected scales[12]")
    if len(qs) != QK_K // 2:
        raise ValueError("expected qs[128]")

    d = f32(f16_to_f32(d_bits))
    mn = f32(f16_to_f32(dmin_bits))

    d_scales, m_scales = patch_unpack_scales_mins_k4(scales)

    acc = 0.0
    for g in range(8):
        base = (g >> 1) * 32
        scale = f32(d * float(d_scales[g]))
        minv = f32(mn * float(m_scales[g]))
        for i in range(32):
            packed = qs[base + i]
            q = float((packed >> 4) if (g & 1) else (packed & 0xF))
            w = f32(f32(scale * q) - minv)
            acc += f32(w * f32(x[(g * 32) + i]))

    return acc


def xorshift32(s: int) -> int:
    x = int(s) & 0xFFFFFFFF
    x ^= (x << 13) & 0xFFFFFFFF
    x ^= (x >> 17) & 0xFFFFFFFF
    x ^= (x << 5) & 0xFFFFFFFF
    return int(x) & 0xFFFFFFFF


def fixture_x(seed_x: int) -> list[float]:
    # Match the fixture generator mapping:
    # t = (u & 0x00FFFFFF) / 2^24; x = t*6 - 3
    s = int(seed_x) & 0xFFFFFFFF
    out: list[float] = []
    for _ in range(QK_K):
        s = xorshift32(s)
        t = f32(float(s & 0x00FFFFFF) / float(0x01000000))
        out.append(f32(f32(t * 6.0) - 3.0))
    return out


def parse_block_q4_k(block: bytes) -> tuple[int, int, bytes, bytes]:
    # ggml block_q4_K layout (little-endian):
    # - ggml_half d; ggml_half dmin; uint8_t scales[12]; uint8_t qs[128]
    if len(block) != 144:
        raise ValueError(f"expected block_q4_K bytes=144, got {len(block)}")
    d_bits = int.from_bytes(block[0:2], "little", signed=False)
    dmin_bits = int.from_bytes(block[2:4], "little", signed=False)
    scales = block[4:16]
    qs = block[16:144]
    if len(scales) != 12 or len(qs) != 128:
        raise AssertionError("bad block slicing")
    return d_bits, dmin_bits, scales, qs


def run_llamacpp_fixture(path: str) -> None:
    with open(path, "r", encoding="utf-8") as f:
        fx = json.load(f)
    vectors = fx.get("vectors") or []
    if not isinstance(vectors, list) or not vectors:
        raise ValueError("fixture missing vectors[]")

    max_abs_err = 0.0
    max_abs_weight_diff = 0.0
    max_abs_dot_ref_err = 0.0
    max_abs_dot_patch_err = 0.0
    for i, v in enumerate(vectors):
        block_hex = v.get("block_hex")
        seed_x = v.get("seed_x")
        want_dot = v.get("dot")
        if not isinstance(block_hex, str) or not isinstance(seed_x, int):
            raise ValueError(f"fixture vector {i}: missing block_hex/seed_x")
        if not isinstance(want_dot, (int, float)):
            raise ValueError(f"fixture vector {i}: missing dot")

        block = bytes.fromhex(block_hex)
        d_bits, dmin_bits, scales, qs = parse_block_q4_k(block)
        x = fixture_x(seed_x)
        w = ggml_dequantize_row_q4_k(scales, qs, d_bits, dmin_bits)
        got = sum(float(w[j]) * float(x[j]) for j in range(QK_K))
        err = abs(float(want_dot) - float(got))
        if err > max_abs_err:
            max_abs_err = err
        if err > 1.0e-5:
            raise SystemExit(f"fixture mismatch i={i} want={want_dot} got={got} abs_err={err}")

        # For validating the CUDA dot-product path, compare against the dequantized
        # row but force float32 rounding per multiply (the CUDA kernel runs in
        # float32, while the fixture's dot value may be computed in wider precision).
        dot_ref_f32 = sum(f32(float(w[j]) * float(x[j])) for j in range(QK_K))
        dot_simple = cuda_style_dot_q4_k(scales, qs, d_bits, dmin_bits, x)
        dot_patch = cuda_patch_style_dot_q4_k(scales, qs, d_bits, dmin_bits, x)
        dot_ref_err = abs(dot_ref_f32 - dot_simple)
        dot_patch_err = abs(dot_ref_f32 - dot_patch)
        if dot_ref_err > max_abs_dot_ref_err:
            max_abs_dot_ref_err = dot_ref_err
        if dot_patch_err > max_abs_dot_patch_err:
            max_abs_dot_patch_err = dot_patch_err
        if dot_ref_err > 1.0e-5:
            raise SystemExit(
                f"fixture dot mismatch i={i} ref_f32={dot_ref_f32} got_simple={dot_simple} abs_err={dot_ref_err}"
            )
        if dot_patch_err > 1.0e-5:
            raise SystemExit(
                f"fixture dot mismatch i={i} ref_f32={dot_ref_f32} got_patch={dot_patch} abs_err={dot_patch_err}"
            )

        # Patch-style unpacking should reproduce the same 256-element float row.
        d_scales, m_scales = patch_unpack_scales_mins_k4(scales)
        d = f32(f16_to_f32(d_bits))
        mn = f32(f16_to_f32(dmin_bits))
        w_patch = [0.0] * QK_K
        for g in range(8):
            base = (g >> 1) * 32
            scale = f32(d * float(d_scales[g]))
            minv = f32(mn * float(m_scales[g]))
            for j in range(32):
                packed = qs[base + j]
                q = float((packed >> 4) if (g & 1) else (packed & 0xF))
                w_patch[(g * 32) + j] = f32(f32(scale * q) - minv)
        for j in range(QK_K):
            diff = abs(float(w[j]) - float(w_patch[j]))
            if diff > max_abs_weight_diff:
                max_abs_weight_diff = diff
            if diff > 1.0e-6:
                raise SystemExit(
                    f"fixture weight mismatch i={i} j={j} want={w[j]} got_patch={w_patch[j]} abs_err={diff}"
                )

    print(
        f"ok: llama.cpp fixture vectors={len(vectors)} max_abs_err={max_abs_err:.3e} "
        f"max_abs_weight_diff={max_abs_weight_diff:.3e} max_abs_dot_ref_err={max_abs_dot_ref_err:.3e} "
        f"max_abs_dot_patch_err={max_abs_dot_patch_err:.3e}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--fixture",
        type=str,
        default="fixtures/quant/q4k_llamacpp_b9110_rowdot_fixture.json",
        help="Optional llama.cpp-generated fixture JSON to validate against.",
    )
    ap.add_argument("--no-fixture", action="store_true", help="Skip fixture validation.")
    ap.add_argument("--trials", type=int, default=500)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    if not args.no_fixture:
        if os.path.exists(args.fixture):
            run_llamacpp_fixture(args.fixture)
        else:
            # Only hard-fail when the user explicitly overrides the default.
            if args.fixture != "fixtures/quant/q4k_llamacpp_b9110_rowdot_fixture.json":
                raise SystemExit(f"missing fixture: {args.fixture}")

    rng = random.Random(args.seed)

    max_abs_err = 0.0
    for _ in range(args.trials):
        scales = bytes(rng.getrandbits(8) for _ in range(12))
        qs = bytes(rng.getrandbits(8) for _ in range(QK_K // 2))
        d_bits = rng.getrandbits(16)
        dmin_bits = rng.getrandbits(16)
        x = [f32(rng.uniform(-3.0, 3.0)) for _ in range(QK_K)]

        # Cross-check the two scale/min unpacking paths for every random block.
        d_scales, m_scales = unpack_scales_mins_k4(scales)
        d_scales_patch, m_scales_patch = patch_unpack_scales_mins_k4(scales)
        for j in range(8):
            gd, gm = get_scale_min_k4(j, scales)
            if (gd != d_scales[j]) or (gm != m_scales[j]):
                raise SystemExit(
                    f"scale unpack mismatch j={j} get=({gd},{gm}) unpack=({d_scales[j]},{m_scales[j]})"
                )
            if (gd != d_scales_patch[j]) or (gm != m_scales_patch[j]):
                raise SystemExit(
                    f"scale unpack mismatch j={j} get=({gd},{gm}) patch=({d_scales_patch[j]},{m_scales_patch[j]})"
                )

        w = ggml_dequantize_row_q4_k(scales, qs, d_bits, dmin_bits)
        ref = sum(f32(float(w[i]) * float(x[i])) for i in range(QK_K))
        got = cuda_style_dot_q4_k(scales, qs, d_bits, dmin_bits, x)
        got_patch = cuda_patch_style_dot_q4_k(scales, qs, d_bits, dmin_bits, x)
        err = abs(ref - got)
        err_patch = abs(ref - got_patch)
        if err > max_abs_err:
            max_abs_err = err
        if err_patch > max_abs_err:
            max_abs_err = err_patch
        if err > 1.0e-5 or err_patch > 1.0e-5:
            raise SystemExit(f"mismatch: ref={ref} got={got} abs_err={err} got_patch={got_patch} abs_err_patch={err_patch}")

    print(f"ok: trials={args.trials} max_abs_err={max_abs_err:.3e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
