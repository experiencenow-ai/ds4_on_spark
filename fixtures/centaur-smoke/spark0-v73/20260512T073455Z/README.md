# Spark0 Centaur v73 smoke bundle (PASS)

Run id: `20260512T073455Z`

Produced from a Mac checkout of `experiencenow-ai/ds4_on_spark` by running:

```bash
export SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
export CENTAUR_RUN_ID="20260512T073455Z"
sh ./scripts/centaur_spark0_v73_run.sh spark0@aitopatom-9ab9.local
sh ./scripts/centaur_spark0_v73_fetch_artifacts.sh spark0@aitopatom-9ab9.local "$CENTAUR_RUN_ID" ~/centaur-smoke/v73 fixtures/centaur-smoke/spark0-v73/"$CENTAUR_RUN_ID"
```

Centaur zip (Mac-local):

- Path: `/Users/mac/Downloads/centaur_spec_impl_v73.zip`
- `zip_sha256`: `3d61b1258aac815d294b3c8fdb4e72ac7851e1b47d02a0daff55117f2885af5a`
- `decomposer_version`: `centaur-impl-0.68`

Spark0 environment (from `smoke.log`):

- `python3 -V`: `Python 3.12.3` (`aarch64`)
- `pip freeze`: `numpy==2.4.4`, `scipy==1.17.1`, `scikit-learn==1.8.0`

Contents (sanitized, bounded):

- `smoke.log`: full command transcript + JSON outputs (no secrets)
- `effective_manifests/`: `hyor-sync-effective` manifest(s)
- `hyor_effective/`: materialized effective view for `spark0`
- `hyor_dashboard/`: HTML/JSON dashboard output

