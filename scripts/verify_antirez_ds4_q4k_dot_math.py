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
import random
import struct

QK_K = 256


def f16_to_f32(bits_u16: int) -> float:
    return struct.unpack("e", struct.pack("H", bits_u16 & 0xFFFF))[0]


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


def ggml_dequantize_row_q4_k(scales: bytes, qs: bytes, d_bits: int, dmin_bits: int) -> list[float]:
    if len(scales) != 12:
        raise ValueError("expected scales[12]")
    if len(qs) != QK_K // 2:
        raise ValueError("expected qs[128]")

    d = f16_to_f32(d_bits)
    mn = f16_to_f32(dmin_bits)

    out: list[float] = []
    q_off = 0
    is_ = 0
    for j in range(0, QK_K, 64):
        sc0, m0 = get_scale_min_k4(is_ + 0, scales)
        sc1, m1 = get_scale_min_k4(is_ + 1, scales)
        d1 = d * float(sc0)
        m1f = mn * float(m0)
        d2 = d * float(sc1)
        m2f = mn * float(m1)
        # 32 bytes => 64 nibbles
        q = qs[q_off : q_off + 32]
        out.extend([(d1 * float(b & 0xF) - m1f) for b in q])
        out.extend([(d2 * float(b >> 4) - m2f) for b in q])
        q_off += 32
        is_ += 2

    if len(out) != QK_K:
        raise AssertionError("bad dequant length")
    return out


def cuda_style_dot_q4_k(scales: bytes, qs: bytes, d_bits: int, dmin_bits: int, x: list[float]) -> float:
    if len(x) != QK_K:
        raise ValueError("expected x[256]")

    d = f16_to_f32(d_bits)
    mn = f16_to_f32(dmin_bits)

    d_scales, m_scales = unpack_scales_mins_k4(scales)

    acc = 0.0
    q_off = 0
    is_ = 0
    for j in range(0, QK_K, 64):
        d1 = d * float(d_scales[is_ + 0])
        m1f = mn * float(m_scales[is_ + 0])
        d2 = d * float(d_scales[is_ + 1])
        m2f = mn * float(m_scales[is_ + 1])
        q = qs[q_off : q_off + 32]
        for l, b in enumerate(q):
            acc += (d1 * float(b & 0xF) - m1f) * x[j + l]
        for l, b in enumerate(q):
            acc += (d2 * float(b >> 4) - m2f) * x[j + 32 + l]
        q_off += 32
        is_ += 2

    return acc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=500)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    rng = random.Random(args.seed)

    max_abs_err = 0.0
    for _ in range(args.trials):
        scales = bytes(rng.getrandbits(8) for _ in range(12))
        qs = bytes(rng.getrandbits(8) for _ in range(QK_K // 2))
        d_bits = rng.getrandbits(16)
        dmin_bits = rng.getrandbits(16)
        x = [rng.uniform(-3.0, 3.0) for _ in range(QK_K)]

        # Cross-check the two scale/min unpacking paths for every random block.
        d_scales, m_scales = unpack_scales_mins_k4(scales)
        for j in range(8):
            gd, gm = get_scale_min_k4(j, scales)
            if (gd != d_scales[j]) or (gm != m_scales[j]):
                raise SystemExit(
                    f"scale unpack mismatch j={j} get=({gd},{gm}) unpack=({d_scales[j]},{m_scales[j]})"
                )

        w = ggml_dequantize_row_q4_k(scales, qs, d_bits, dmin_bits)
        ref = sum(w[i] * x[i] for i in range(QK_K))
        got = cuda_style_dot_q4_k(scales, qs, d_bits, dmin_bits, x)
        err = abs(ref - got)
        if err > max_abs_err:
            max_abs_err = err
        if err > 1.0e-5:
            raise SystemExit(f"mismatch: ref={ref} got={got} abs_err={err}")

    print(f"ok: trials={args.trials} max_abs_err={max_abs_err:.3e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
