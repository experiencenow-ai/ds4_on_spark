# Centaur smoke fixtures

These fixtures are intentionally tiny, synthetic inputs used by Centaur-on-Spark smoke scripts.

Rules:

- No secrets (no tokens, no private keys).
- No model weights.
- Safe to commit.

Current fixtures:

- `fixtures/centaur-smoke/spark0-v73/unit_model_catalog.json`: one synthetic model candidate for `hyor-model-catalog-import`.

## Sanitized smoke bundles (outputs)

We also commit *small, sanitized* Centaur smoke artifact bundles for reproducibility and bug reports.
These are not inputs, but they are intentionally bounded (no venvs, no zips, no secrets, no model weights).

- Spark0 v73 smoke PASS (artifact bundle):
  - `fixtures/centaur-smoke/spark0-v73/20260512T030829Z/`
