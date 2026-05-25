# ds4_on_spark

The live DS4 Spark service substrate is now `v2/`.

The legacy top-level lab/probe tree was intentionally purged after the
Centaur-owned archive, audit, and diamond machinery moved to the Centaur
repository. Git history is the archive for old v1 scripts, fixtures, probes,
and gateway experiments.

Start here:

```bash
cd v2
python3 -m compileall -q src tests
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Useful entry points:

- `ds4-infer`: profile routing, queueing, and Spark-local model execution.
- `ds4-spark-chat -m ds4v`: manual chat with full local history, model call on Spark.
- `ds4-sparkrunner-queue`: SparkRunner-compatible JSONL adapter backed by the v2 queue.
- `ds4-tools`: bounded tool registry.
- `ds4-transfer`: direct Spark-to-Spark transfer planning.

See `v2/README.md` and `v2/docs/spark-queue-runbook.md`.
