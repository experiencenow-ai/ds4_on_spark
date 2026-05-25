# Legacy reconciliation

The old v1 substrate is retired. The v2 contracts absorb only the pieces that
are still product-surface requirements:

| Former surface | v2 destination |
|---|---|
| SparkRunner lazy adapter | `ds4-sparkrunner-queue` / `v2/scripts/sparkrunner_queue_adapter.sh` |
| Diamond proposal loop calling SparkRunner | Direct `ds4-infer` queue JSONL via `--response-format inference` |
| Lazy proxy | Removed; Spark-local endpoints are used through `--runner spark` |
| Model gateway operational knowledge | `v2/docs/model-gateway-operational-notes.md` |
| 200G transfer policy | `v2/docs/spark-transfer.md` and `ds4_transfer` direct Spark-to-Spark plans |
| CPU batch services | `ds4_tools.cpu_batch` and `tool:ds4.cpu.batch` |
| Spark telemetry | Keep out of the inference substrate; collect as ops telemetry |
| Audit and diamond-quality substrate | Centaur owns the engine; DS4 keeps baselines, model-contract fixtures, and a thin Centaur audit wrapper |

The important boundary is that ds4_on_spark routes model work. Centaur owns
verification, promotion, archive management, and diamond/audit semantics.
