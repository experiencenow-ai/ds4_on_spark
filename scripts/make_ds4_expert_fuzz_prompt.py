#!/usr/bin/env python3
"""Build a deterministic multi-domain prompt for DS4 expert-routing probes."""

from __future__ import annotations

import argparse
from pathlib import Path


SUBJECTS = [
    "Redis streams",
    "CUDA occupancy",
    "MoE routing",
    "Qwen model quality",
    "network bootstrapping",
    "ring topology",
    "cache eviction",
    "tokenization",
    "branch prediction",
    "matrix quantization",
    "legal contract clauses",
    "medical triage summary",
    "financial risk model",
    "poetry translation",
    "SQL query plan",
    "Rust ownership",
    "C memory layout",
    "distributed consensus",
    "attention kernels",
    "expert scheduling",
]

VERBS = [
    "explain briefly",
    "compare two options for",
    "find the bug in",
    "write pseudocode for",
    "rank tradeoffs in",
]

STYLES = [
    "as bullet notes",
    "as a terse benchmark memo",
    "with one counterexample",
    "for a skeptical engineer",
    "using exact numbers",
]


def build_prompt(count: int) -> str:
    lines = [
        "You are testing router diversity. Answer nothing yet; read the following independent prompts as separate workload samples."
    ]
    idx = 0
    while idx < count:
        for subject in SUBJECTS:
            for verb in VERBS:
                idx += 1
                style = STYLES[idx % len(STYLES)]
                checksum = (idx * 7919) % 100000
                lines.append(
                    f"Prompt {idx:03d}: {verb} {subject} {style}. Include id={idx} and checksum={checksum}."
                )
                if idx >= count:
                    break
            if idx >= count:
                break
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.count < 1:
        raise SystemExit("--count must be positive")
    out = Path(args.output)
    out.write_text(build_prompt(args.count), encoding="utf-8")
    print(f"wrote {args.count} prompts to {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
