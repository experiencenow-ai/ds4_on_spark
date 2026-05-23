# Mtp

> Supersedes: `docs/mtp-one-token-draft-probe.md`, `docs/mtp-ds4-reference.md`, `docs/mtp-verifier-cost-redesign.md`, `docs/mtp-q4k-dot-validation.md`, `docs/mtp-acceptance-sweep.md`, `docs/mtp-dummy-movement-proof.md`

This is the canonical document for this topic. Update this file instead of adding a new overlapping note.

## Scope

- Consolidates 6 previous document(s) into one non-overlapping reference.
- Preserves stable commands, constraints, and source inventory; removes per-iteration narrative duplication.
- Historical probe/status fragments should live in git history, not as active docs.

## Current Guidance

- `mtp-one-token-draft-probe.md`: One-Token MTP Draft Probe (llama.cpp Spark/CUDA) (239 lines).
- `mtp-ds4-reference.md`: antirez/ds4 MTP reference (DeepSeek V4 Flash) (107 lines).
- `mtp-verifier-cost-redesign.md`: MTP Verifier Cost Redesign (23 lines).
- `mtp-q4k-dot-validation.md`: Q4_K dot math validation (llama.cpp fixture) (55 lines).
- `mtp-acceptance-sweep.md`: MTP Acceptance Sweep (Trace Summary) (34 lines).
- `mtp-dummy-movement-proof.md`: MTP Dummy Movement Proof (61 lines).

## Command Inventory

- `mtp-one-token-draft-probe.md`: `python3 scripts/verify_mtp_sidecar_payload_fingerprint.py --probe-json /path/to/mtp_sidecar_probe.json --json`
- `mtp-one-token-draft-probe.md`: `python3 scripts/model_contract_validate_mtp_one_token_draft_probe.py --probe-json /path/to/mtp_one_token_probe.json`
- `mtp-one-token-draft-probe.md`: `python3 scripts/model_contract_validate_mtp_one_token_draft_probe.py --probe-json /path/to/mtp_one_token_probe.json --sidecar-probe-json /path/to/mtp_sidecar_probe.json`
- `mtp-one-token-draft-probe.md`: `python3 scripts/diff_mtp_one_token_draft_probe.py --a /path/to/oracle_probe.json --b /path/to/candidate_probe.json --json`
- `mtp-one-token-draft-probe.md`: `python3 scripts/verify_mtp_one_token_draft_probe_captures.py --probe-json /path/to/oracle_probe.json --json`
- `mtp-one-token-draft-probe.md`: `python3 scripts/verify_mtp_one_token_draft_probe_captures.py --probe-json /path/to/candidate_probe.json --json`
- `mtp-one-token-draft-probe.md`: `python3 scripts/summarize_mtp_one_token_draft_probe_diff.py --a /path/to/oracle_probe.json --b /path/to/candidate_probe.json --json`
- `mtp-one-token-draft-probe.md`: `python3 scripts/verify_mtp_one_token_draft_probe_captures.py --profile minimal --probe-json /path/to/oracle_probe.json --json`
- `mtp-one-token-draft-probe.md`: `python3 scripts/verify_mtp_one_token_draft_probe_captures.py --profile minimal --probe-json /path/to/candidate_probe.json --json`
- `mtp-one-token-draft-probe.md`: `python3 scripts/compare_mtp_one_token_hc_layout.py --a /path/to/oracle_probe.json --b /path/to/candidate_probe.json --json`
- `mtp-one-token-draft-probe.md`: `python3 scripts/verify_mtp_one_token_draft_probe_captures.py --profile extended --probe-json /path/to/oracle_probe.json --json`
- `mtp-one-token-draft-probe.md`: `python3 scripts/verify_mtp_one_token_draft_probe_captures.py --profile extended --probe-json /path/to/candidate_probe.json --json`
- `mtp-ds4-reference.md`: `./scripts/fetch_upstreams.sh ds4`
- `mtp-ds4-reference.md`: `python3 scripts/verify_mtp_sidecar_expected_tensors_vs_ds4.py --ds4-c upstreams/ds4/ds4.c --python-probe scripts/model_contract_probe_mtp_sidecar.py`
- `mtp-q4k-dot-validation.md`: `python3 scripts/verify_antirez_ds4_q4k_dot_math.py --fixture fixtures/quant/q4k_llamacpp_b9110_rowdot_fixture.json`
- `mtp-q4k-dot-validation.md`: `python3 -m unittest tests/q4k_llamacpp_fixture_test.py`
- `mtp-acceptance-sweep.md`: `python3 scripts/summarize_mtp_acceptance_trace.py --in-jsonl /path/to/runtime.log.jsonl --draft-len 2`
- `mtp-acceptance-sweep.md`: `python3 scripts/summarize_mtp_acceptance_trace.py --in-jsonl /path/to/runtime.log.jsonl --draft-len 2 --extract-substrings 0`
- `mtp-dummy-movement-proof.md`: `./scripts/run_mtp_dummy_movement_proof_spark.sh spark0@172.16.11.228`

## Source Map

| Source | Lines | Main heading | Subsections |
|---|---:|---|---|
| `docs/mtp-one-token-draft-probe.md` | 239 | One-Token MTP Draft Probe (llama.cpp Spark/CUDA) | Inputs, Required probe output, Validation, Oracle diff (required before acceptance sweeps), Spark runner (llama.cpp skeleton patch; available now) |
| `docs/mtp-ds4-reference.md` | 107 | antirez/ds4 MTP reference (DeepSeek V4 Flash) | Tensor bindings (`mtp.0.*` contract), Separate MTP raw cache + speculative state, Draft generation (one-token gate), `gamma=1` draft step (operation order, DS4 source of truth), Verification + partial accept + rollback |
| `docs/mtp-verifier-cost-redesign.md` | 23 | MTP Verifier Cost Redesign | Why draft=2 still pays target/output-head 21 times, What can be made cheaper, Cache state required for strictness, Minimal next code change |
| `docs/mtp-q4k-dot-validation.md` | 55 | Q4_K dot math validation (llama.cpp fixture) | What is validated, Run the check (no CUDA required), Fixture provenance, Regenerating the fixture (gated) |
| `docs/mtp-acceptance-sweep.md` | 34 | MTP Acceptance Sweep (Trace Summary) | Required per-step fields (runtime log), Summarize acceptance |
| `docs/mtp-dummy-movement-proof.md` | 61 | MTP Dummy Movement Proof | - |
