# Spark Transfer Service

The Spark fabric is a major resource. Transfers should not hairpin through the controller when two Sparks can move data directly over the 200Gbps fabric.

The transfer service is a safe planner/executor for direct Spark-to-Spark file movement. It currently emits source-initiated rsync-over-SSH commands:

```text
controller -> ssh source_spark -> rsync /source destination_spark:/destination
```

That keeps the payload path:

```text
source Spark -> destination Spark
```

not:

```text
source Spark -> controller -> destination Spark
```

## Plan a transfer

```bash
PYTHONPATH=src python3 -m ds4_transfer.cli plan \
  --topology profiles/transfer/spark_200g.json \
  --request-json '{
    "format":"ds4-transfer-request-v1",
    "request_id":"copy-batch-001",
    "source_node":"spark0",
    "source_path":"/mnt/data/batch/",
    "destination_node":"spark4",
    "destination_path":"/mnt/data/batch/"
  }'
```

The plan includes both an argv list and a shell-rendered string for review.

## Execute or dry-run

```bash
PYTHONPATH=src python3 -m ds4_transfer.cli run \
  --topology profiles/transfer/spark_200g.json \
  --dry-run \
  --request-json '{...}'
```

The topology allowlists root paths per Spark. Requests outside the allowlist are rejected before execution.

## Policy

- Compression is disabled by default.
- The source Spark initiates transfer.
- Paths must be absolute and allowlisted.
- Controller never expands arbitrary shell.
- The first method is rsync because it is already good for incremental artifacts. Future transfer methods can add tar-streaming or parallel file-list shards behind the same request schema.
