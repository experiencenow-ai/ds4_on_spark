# Legacy reconciliation

The old v1 substrate is retired. The v2 contracts absorb only the pieces that
are still product-surface requirements:

| Former surface | v2 destination |
|---|---|
| SparkRunner lazy adapter | `ds4-sparkrunner-queue` / `v2/scripts/sparkrunner_queue_adapter.sh` |
| Diamond proposal loop calling SparkRunner | Direct `ds4-infer` queue JSONL via `--response-format inference` |
| Lazy proxy | Removed; Spark-local endpoints are used through `--runner spark` |
| CPU batch services | Re-expose only as `ds4-tools` entries when Centaur needs them |
| Spark telemetry | Keep out of the inference substrate; collect as ops telemetry |
| Audit and diamond-quality substrate | Centaur owns it |

The important boundary is that ds4_on_spark routes model work. Centaur owns
verification, promotion, archive management, and diamond/audit semantics.
