# Model Provider Tiers

> Supersedes: `docs/model-provider-tiers.md`, `docs/model-quality-speed.md`, `docs/model-contract.md`, `docs/model-comparators.md`

This is the canonical document for this topic. Update this file instead of adding a new overlapping note.

## Scope

- Consolidates 4 previous document(s) into one non-overlapping reference.
- Preserves stable commands, constraints, and source inventory; removes per-iteration narrative duplication.
- Historical probe/status fragments should live in git history, not as active docs.

## Current Guidance

- `model-provider-tiers.md`: Model Provider Tiers (213 lines).
- `model-quality-speed.md`: Model Quality And Speed (215 lines).
- `model-contract.md`: Model Contract (214 lines).
- `model-comparators.md`: Model Comparators (Lightweight Contract Notes) (89 lines).

## Command Inventory

- `model-provider-tiers.md`: `python3 scripts/validate_model_provider_profiles.py`
- `model-provider-tiers.md`: `python3 scripts/validate_model_provider_profiles.py --json`
- `model-provider-tiers.md`: `python3 scripts/select_model_provider.py --tier near_frontier_local --lane hard_reasoning --batch-tokens 16384`
- `model-provider-tiers.md`: `python3 scripts/select_model_provider.py --tier local_small --lane candidate_prefilter --batch-tokens 32`
- `model-provider-tiers.md`: `python3 scripts/select_model_provider.py --tier local_coder --lane schema_repair --batch-tokens 32`
- `model-provider-tiers.md`: `python3 scripts/route_model_provider_requests.py fixtures/model_provider_routes/centaur_provider_route_requests_20260522.example.json --allow-blocked`
- `model-provider-tiers.md`: `python3 scripts/route_model_provider_requests.py fixtures/model_provider_routes/centaur_provider_route_small_models_20260523.example.json`
- `model-provider-tiers.md`: `python3 scripts/validate_model_provider_routing.py`
- `model-provider-tiers.md`: `python3 scripts/route_model_provider_requests.py fixtures/model_provider_routes/centaur_provider_route_budget_policy_20260523.example.json`
- `model-contract.md`: `python3 scripts/verify_mtp_one_token_draft_probe_captures.py --probe-json oracle.json --json`
- `model-contract.md`: `python3 scripts/verify_mtp_one_token_draft_probe_captures.py --probe-json candidate.json --json`
- `model-contract.md`: `python3 scripts/summarize_mtp_one_token_draft_probe_diff.py --a oracle.json --b candidate.json --json`

## Source Map

| Source | Lines | Main heading | Subsections |
|---|---:|---|---|
| `docs/model-provider-tiers.md` | 213 | Model Provider Tiers | Tier Vocabulary, Provider Profile V1, Fixtures, Validation, Selection |
| `docs/model-quality-speed.md` | 215 | Model Quality And Speed | Public Quality Prior, Local Spark Quality, Combined Score, Scorer, Scope Hygiene |
| `docs/model-contract.md` | 214 | Model Contract | What “contract” means here, DeepSeek V4 Flash, Correctness Oracles (requirements), Comparator models (Ling / Qwen / DFlash pairs) |
| `docs/model-comparators.md` | 89 | Model Comparators (Lightweight Contract Notes) | What to record (any comparator model), Metadata-only fetch (fixtures), Ling 2.6 Flash, Qwen-family (generic), DFlash draft pairs (target + DFlash speculative decoding) |
