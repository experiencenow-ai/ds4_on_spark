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

Newer bundles may also include:

- `smoke_facts.json` (structured zip/python/pip/requirements facts)
- `pip_freeze.txt` (sanitized dependency versions)

To create new commit-ready bundles from fetched artifacts (after review/redaction), use:

- Spark0 smoke: `scripts/centaur_spark0_v73_fixture_pack.sh`
- Spark12 ring sim: `scripts/centaur_spark12_v73_ring_sim_fixture_pack.sh`
- Spark12 ring rsync: `scripts/centaur_spark12_v73_ring_rsync_fixture_pack.sh`

- Spark0 v73 smoke PASS (artifact bundle):
  - `fixtures/centaur-smoke/spark0-v73/20260512T030829Z/`
  - `fixtures/centaur-smoke/spark0-v73/20260512T073455Z/`

- Spark12 v73 ring sim PASS (Spark0-local, artifact bundle):
  - `fixtures/centaur-smoke/spark12-v73/ring_sim/20260512T041207Z/`
  - `fixtures/centaur-smoke/spark12-v73/ring_sim/20260512T074400Z/`
