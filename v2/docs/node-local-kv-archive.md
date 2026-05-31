# DS4 node-local external KV archive invariant

DS4 external KV is a manifest-coordinated, node-local data plane. Spark0 owns queue state, leases, and object manifests. Spark0 must not aggregate full KV payloads, and the Mac Studio/client must not be required to receive full KV payloads.

## Invariant

For pipeline services such as `qwen-fast`, `qwen`, and `dsv4`:

```text
spark0:
  control plane only
  queue database
  object-level KV manifest
  lease / pin / state transitions
  result files

sparkN:
  owns the KV shard for its pipeline stage
  writes and archives its own shard
  reports shard-ready / shard-archived status to spark0
```

A KV object is available only when all required stage shards are ready. Partial shard commits leave the object in `partial` state.

## Manifest Shape

A KV lookup returns routing metadata that makes the split explicit:

```json
{
  "routing": {
    "sharding": "pipeline_layers",
    "control_node_id": "spark0",
    "data_plane": "node_local_shards",
    "spark0_aggregates_shards": false,
    "client_receives_shards": false
  },
  "archive": {
    "mode": "node_local_shards",
    "object_manifest_on_control_node_only": true,
    "shard_owner_is_node": true
  }
}
```

`storage_uri` is interpreted on the owning node. A storage root such as `/home/spark/ds4_nvme/ds4_kv` becomes `node-local://sparkN/home/spark/ds4_nvme/ds4_kv/...`, not a spark0 path.

## Declare

Spark0 declares the object and expected shards:

```bash
curl -s http://spark0:8700/ds4/kvcache/declare \
  -H 'content-type: application/json' \
  -d '{
    "namespace": "centaur.longmem",
    "kv_key": "project-x:prefix-0001",
    "service_id": "qwen27_nvfp4_pp8",
    "total_bytes": 8589934592,
    "total_tokens": 131072,
    "storage_root": "/home/spark/ds4_nvme/ds4_kv"
  }'
```

The lower-level queue API rejects external KV declarations without explicit shard manifests. That prevents representing a pipeline KV object as one spark0-owned blob.

## Per-Node Shard Commit

Each Spark reports its own shard independently:

```bash
curl -s http://spark0:8700/ds4/kvcache/shard/commit \
  -H 'content-type: application/json' \
  -d '{
    "namespace": "centaur.longmem",
    "kv_key": "project-x:prefix-0001",
    "service_id": "qwen27_nvfp4_pp8",
    "node_id": "spark5",
    "bytes": 1073741824,
    "storage_uri": "node-local://spark5/home/spark/ds4_nvme/ds4_kv/centaur.longmem/qwen27_nvfp4_pp8/project-x-prefix-0001/stage-05",
    "content_hash": "sha256:...",
    "state": "ready_on_ssd"
  }'
```

The same endpoint can acknowledge archival by setting `state` to `archived` and passing `archive_uri`.

## Waterfall Prepare

The waterfall prepare step should move manifests and shard readiness around the ring, not full object aggregation through spark0.

```text
1. spark0 resolves object manifest.
2. spark0 sends each node its own shard descriptor.
3. each node checks local SSD/archive for its shard.
4. missing shards are fetched by the owning node, not aggregated at spark0.
5. each node posts shard commit/archive acknowledgement to spark0.
6. spark0 dispatches inference once all required shard states are ready.
```
