#!/usr/bin/env python3
"""Build a compact DSv4 pairwise judge prompt (verifier budget).

This script does not call any paid API. It prints a prompt template that can be
fed into a DSv4 judge runner, requesting strictly-minified JSON output.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Literal


PromptSchemaVersion = Literal["v1", "v2"]
DecisionSchemaVersion = Literal["v1", "v2"]


SYSTEM_V1 = (
    "You are a strict pairwise judge. Return minified JSON only.\n"
    "No markdown. No extra keys. No explanations.\n"
    "Return exactly one JSON object on one line.\n"
    "Target judge_out <= ~{judge_out_target} tokens by keeping reason/train_hint short.\n"
    "If you exceed the budget, shorten reason first, then set train_hint to empty, then drop extra tags.\n"
    "reason must be non-empty and <= 18 words (prefer <= 12).\n"
    "train_hint may be empty, but if present must be <= 18 words (prefer <= 12).\n"
    "train_hint must be an actionable improvement hint for the loser; if tie, prefer empty.\n"
    "All string values must be single-line (no newlines).\n"
    "If winner is tie, margin must be 0 and score_a must equal score_b.\n"
    "Keep margin consistent with |score_a-score_b|: 1->0/1, 2->1/2, 3->2, >=4->3."
)

SYSTEM_V2 = (
    "You are a strict pairwise judge.\n"
    "Return exactly one minified JSON object on one line (no prose/markdown, no extra keys).\n"
    "Keys: winner(A|B|tie), margin(0..3), score_a(0..10), score_b(0..10), reason<=18 words, train_hint<=18 words, tags(0..3).\n"
    "Tie => margin=0 and score_a==score_b.\n"
    "winner=A => score_a>score_b; winner=B => score_b>score_a.\n"
    "Margin must match |score_a-score_b|: 1->{{0,1}}, 2->{{1,2}}, 3->{{2}}, >=4->{{3}}.\n"
    "Keep within ~{judge_out_target} output tokens; shorten reason, then empty train_hint, then drop tags.\n"
    "All strings must be single-line (no newlines); tag strings must be <=24 chars."
)

SYSTEM_V2_DECISION_V2 = (
    "You are a strict pairwise judge.\n"
    "Return exactly one minified JSON object on one line (no prose/markdown, no extra keys).\n"
    "Keys: w(A|B|tie), m(0..3), sa(0..10), sb(0..10), r<=18 words, h<=18 words, t(0..3).\n"
    "Tie => m=0 and sa==sb.\n"
    "w=A => sa>sb; w=B => sb>sa.\n"
    "m must match |sa-sb|: 1->{{0,1}}, 2->{{1,2}}, 3->{{2}}, >=4->{{3}}.\n"
    "Keep within ~{judge_out_target} output tokens; shorten r, then empty h, then drop t.\n"
    "All strings must be single-line (no newlines); tag strings must be <=24 chars."
)


def build_system(judge_out_target: int, schema_version: PromptSchemaVersion, decision_version: DecisionSchemaVersion) -> str:
    if schema_version == "v2":
        if decision_version == "v2":
            return SYSTEM_V2_DECISION_V2.format(judge_out_target=int(judge_out_target))
        return SYSTEM_V2.format(judge_out_target=int(judge_out_target))
    return SYSTEM_V1.format(judge_out_target=int(judge_out_target))


def build_user_v1(prompt: str, a: str, b: str, decision_version: DecisionSchemaVersion) -> str:
    schema_hint = build_schema_hint(decision_version=decision_version)
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

def build_user_v2(prompt: str, a: str, b: str) -> str:
    return (
        "Compare A vs B for the same PROMPT. Prefer correctness and instruction-following. If close, tie.\n"
        "Return JSON only.\n"
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


def build_schema_hint(decision_version: DecisionSchemaVersion) -> Dict[str, Any]:
    if decision_version == "v2":
        return {
            "w": "A|B|tie",
            "m": "0..3 (tie=>0)",
            "sa": "0..10",
            "sb": "0..10",
            "r": "<=18 words, 1 line",
            "h": "<=18 words, 1 line",
            "t": ["<=3", "short", "strings"],
        }
    return {
        "winner": "A|B|tie",
        "margin": "0..3 (tie=>0)",
        "score_a": "0..10",
        "score_b": "0..10",
        "reason": "<=18 words, 1 line",
        "train_hint": "<=18 words, 1 line",
        "tags": ["<=3", "short", "strings"],
    }


def build_messages(
    prompt: str,
    a: str,
    b: str,
    judge_out_target: int,
    schema_version: PromptSchemaVersion,
    decision_version: DecisionSchemaVersion,
) -> Dict[str, Any]:
    return {
        "schema": ("ds4_pairwise_judge_prompt_v2" if schema_version == "v2" else "ds4_pairwise_judge_prompt_v1"),
        "judge_out_target": int(judge_out_target),
        "system": build_system(int(judge_out_target), schema_version=schema_version, decision_version=decision_version),
        "user": (build_user_v2(prompt, a, b) if schema_version == "v2" else build_user_v1(prompt, a, b, decision_version=decision_version)),
        "schema_hint": build_schema_hint(decision_version=decision_version),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True, help="path to prompt text file")
    ap.add_argument("--a", required=True, help="path to candidate A output text file")
    ap.add_argument("--b", required=True, help="path to candidate B output text file")
    ap.add_argument("--judge-out-target", type=int, default=64, help="target judge output tokens (budget guidance only)")
    ap.add_argument("--schema-version", choices=["v1", "v2"], default="v2", help="prompt schema version (default v2)")
    ap.add_argument("--decision-version", choices=["v1", "v2"], default="v1", help="decision schema version (default v1; v2 uses compact keys w/m/sa/sb/r/h/t)")
    ap.add_argument("--format", choices=["blocks", "json"], default="blocks", help="output format (default blocks)")
    args = ap.parse_args()

    if int(args.judge_out_target) <= 0:
        raise SystemExit("--judge-out-target must be an integer > 0")

    with open(args.prompt, "r", encoding="utf-8") as f:
        prompt = f.read()
    with open(args.a, "r", encoding="utf-8") as f:
        a = f.read()
    with open(args.b, "r", encoding="utf-8") as f:
        b = f.read()

    if str(args.format) == "json":
        msg = build_messages(
            prompt,
            a,
            b,
            judge_out_target=int(args.judge_out_target),
            schema_version=str(args.schema_version),
            decision_version=str(args.decision_version),
        )
        print(json.dumps(msg, separators=(",", ":"), ensure_ascii=False))
        return

    print("=== system ===")
    print(build_system(int(args.judge_out_target), schema_version=str(args.schema_version), decision_version=str(args.decision_version)))
    print("=== user ===")
    if str(args.schema_version) == "v2":
        print(build_user_v2(prompt, a, b))
    else:
        print(build_user_v1(prompt, a, b, decision_version=str(args.decision_version)))


if __name__ == "__main__":
    main()
