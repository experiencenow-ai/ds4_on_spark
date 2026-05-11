#!/usr/bin/env python3
"""Build a compact DSv4 pairwise judge prompt (verifier budget).

This script does not call any paid API. It prints a prompt template that can be
fed into a DSv4 judge runner, requesting strictly-minified JSON output.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Dict


SYSTEM = (
    "You are a strict pairwise judge. Return minified JSON only.\n"
    "No markdown. No extra keys. No explanations.\n"
    "Return exactly one JSON object on one line.\n"
    "Target judge_out <= ~{judge_out_target} tokens by keeping reason/train_hint short.\n"
    "reason and train_hint must each be <= 18 words.\n"
    "If winner is tie, margin must be 0 and score_a must equal score_b."
)


def build_system(judge_out_target: int) -> str:
    return SYSTEM.format(judge_out_target=int(judge_out_target))


def build_user(prompt: str, a: str, b: str) -> str:
    schema_hint = {
        "winner": "A|B|tie",
        "margin": "0..3 (tie=>0)",
        "score_a": "0..10",
        "score_b": "0..10",
        "reason": "<=18 words",
        "train_hint": "<=18 words",
        "tags": ["short", "strings"],
    }
    return (
        "Compare the two candidates for the same prompt. Prefer correctness, helpfulness, and instruction-following.\n"
        "If both are similarly good/bad, choose tie.\n"
        "Output JSON matching this shape: " + json.dumps(schema_hint, separators=(",", ":")) + "\n"
        "\n"
        "PROMPT:\n"
        + prompt.strip()
        + "\n\n"
        "A:\n"
        + a.strip()
        + "\n\n"
        "B:\n"
        + b.strip()
        + "\n"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True, help="path to prompt text file")
    ap.add_argument("--a", required=True, help="path to candidate A output text file")
    ap.add_argument("--b", required=True, help="path to candidate B output text file")
    ap.add_argument("--judge-out-target", type=int, default=64, help="target judge output tokens (budget guidance only)")
    args = ap.parse_args()

    if int(args.judge_out_target) <= 0:
        raise SystemExit("--judge-out-target must be an integer > 0")

    with open(args.prompt, "r", encoding="utf-8") as f:
        prompt = f.read()
    with open(args.a, "r", encoding="utf-8") as f:
        a = f.read()
    with open(args.b, "r", encoding="utf-8") as f:
        b = f.read()

    print("=== system ===")
    print(build_system(int(args.judge_out_target)))
    print("=== user ===")
    print(build_user(prompt, a, b))


if __name__ == "__main__":
    main()
