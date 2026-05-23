#!/usr/bin/env python3
"""Verify that the antirez/ds4 MTP one-token oracle JSON patch is present.

This verifier is intentionally lightweight: it does not require cloning/building
`antirez/ds4`. It checks that the patch file includes the critical pieces that
make the oracle JSON probe usable as a stable correctness reference:

- `--dump-mtp-one-token-json` CLI mode is wired up and forces deterministic params
- `ds4_engine_mtp_one_token_probe(...)` exists and captures the expected tensors
- The JSON output includes the required keys used by the local contract/diff tools
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
	sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._lib.patch_verify import require_substrings
from scripts._lib.patch_verify import run_patch_verifier


def validate_patch_text(patch_text: str) -> list[str]:
	errors: list[str] = []
	require_substrings(errors, patch_text, [
		"diff --git a/ds4.c b/ds4.c",
		"diff --git a/ds4.h b/ds4.h",
		"diff --git a/ds4_cli.c b/ds4_cli.c",
		"int ds4_engine_mtp_one_token_probe(",
		"typedef struct {",
		"} ds4_mtp_one_token_probe;",
		"--dump-mtp-one-token-json",
		"static int run_mtp_one_token_json_dump(",
		'\\"runtime_repo\\":\\"https://github.com/antirez/ds4\\"',
		'\\"runtime_commit\\":\\"3630e64\\"',
		'\\"trunk_gguf_path\\":',
		'\\"mtp_sidecar_path\\":',
		'\\"prompt\\":',
		'\\"seed\\":',
		'\\"temperature\\":',
		'\\"top_k\\":1',
		'\\"top_p\\":',
		'\\"verify_step_idx\\":0',
		'\\"base_next_token_id\\":',
		'\\"mtp_draft_token_id\\":',
		'\\"trunk_token_embd_fnv64\\":',
		'\\"trunk_pre_hc_head_fnv64\\":',
		'\\"mtp_input_hc_fnv64\\":',
		'\\"mtp_block_out_hc_fnv64\\":',
		'\\"mtp_head_norm_fnv64\\":',
		'\\"mtp_params\\":{',
		'\\"ok\\":true',
		'\\"errors\\":[]',
		"c.gen.temperature = 0.0f;",
		"c.gen.top_p = 1.0f;",
		"c.gen.n_predict = 1;",
	])

	# Guardrail: ensure the generator path is wired before the normal generation loop.
	if "if (cfg->gen.dump_mtp_one_token_json)" not in patch_text:
		errors.append("missing expected generation wiring marker for dump_mtp_one_token_json")

	# Guardrail: ensure the dump mode advertises it requires --mtp to avoid silent misuse.
	mtp_hint_markers = [
		"requires --mtp",
		"requires a graph backend (metal/cuda)",
	]
	if not any(m in patch_text for m in mtp_hint_markers):
		errors.append("missing expected usage/error text indicating --mtp + gpu backend requirement")

	return errors


def main() -> None:
	run_patch_verifier(validate_patch_text)


if __name__ == "__main__":
	main()
