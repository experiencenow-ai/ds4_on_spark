# Spark 200G Transfer

Bulk model payloads must use the Spark fabric, not the office/control-plane
network. Plain `sparkN` names are for control commands and fast internet
gateway checks. Bulk data targets are `sparkN-200g`, which must resolve to
`10.10.100.N`, or the explicit `10.10.100.N` address from
`profiles/transfer/spark_200g.json`.

The canonical copy method is `parallel_nc_fanout_200g_v1`:

- The Mac Studio starts and monitors the job only.
- File bytes flow directly from Spark to Spark over the 200G fabric.
- Each adjacent ring hop discovers both next hops with `ip route show`.
- Workers bind one unencrypted `nc` stream per rail and copy many files in
  parallel.
- Large cluster replication fans out from the seed node instead of copying from
  the seed to every node serially.

## Proof Check

Run this before a large model replication if the fabric was reconfigured:

```bash
ssh spark2 'iperf -s -p 49232 -f g'
ssh spark3 'iperf -c 10.10.100.12 -p 49232 -P 32 -t 5 -f g'
```

Expected healthy single-destination aggregate is tens of Gbit/s or better. A
live spark3-to-spark2 check on 2026-05-28 reached `79 Gbit/s` through the
`10.10.100.12` fabric address. Binding both direct rails separately reached
about `136 Gbit/s` aggregate:

```bash
ssh spark2 'iperf -s -B 10.10.5.1 -p 49233 -f g'
ssh spark2 'iperf -s -B 10.10.6.1 -p 49234 -f g'
ssh spark3 'iperf -c 10.10.5.1 -B 10.10.5.2 -p 49233 -P 16 -t 5 -f g'
ssh spark3 'iperf -c 10.10.6.1 -B 10.10.6.2 -p 49234 -P 16 -t 5 -f g'
```

## Single Edge

```bash
cd v2
PYTHONPATH=src python3 -m ds4_transfer.fast_copy \
  --topology profiles/transfer/spark_200g.json \
  --source-node spark3 \
  --source-path /home/spark3/models/hf/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4 \
  --destination-node spark2 \
  --destination-path /home/spark2/models/hf/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4 \
  --jobs-per-edge 16
```

## Partitioned Waterfall

For PP model layouts where each node keeps only its assigned shards, use the
waterfall copier instead of full fan-out. It reads one keep manifest per node,
copies only files needed downstream, and forwards a file to the next ring hop as
soon as the current hop has a complete size-verified copy. With
`--cleanup-transit`, a node deletes safetensor shards it does not keep after it
has forwarded them successfully.

```bash
cd v2
PYTHONPATH=src python3 -m ds4_transfer.waterfall_copy \
  --topology profiles/transfer/spark_200g.json \
  --source-node spark0 \
  --source-path /home/spark0/ds4_nvme/models/hf/moonshotai/Kimi-K2.7-Code \
  --destination-path-template '/home/{node}/models/hf/moonshotai/Kimi-K2.7-Code' \
  --manifest-dir /private/tmp/kimi27_waterfall_manifests \
  --keep-manifest-template '{node}_keep.txt' \
  --cleanup-transit
```

Use `--dry-run` first. The source node's full external seed copy is not removed;
cleanup applies only to transit safetensor files on downstream model
directories.

## Full Fan-Out

The default fan-out for a spark3 seed is:

```text
stage 1: spark3 -> spark2, spark3 -> spark4
stage 2: spark2 -> spark1, spark4 -> spark5
stage 3: spark1 -> spark0, spark5 -> spark6
stage 4: spark0 -> sparkc, spark6 -> spark7
stage 5: sparkc -> sparkb, spark7 -> spark8
stage 6: sparkb -> sparka, spark8 -> spark9
```

Run:

```bash
cd v2
PYTHONPATH=src python3 -m ds4_transfer.fast_copy \
  --topology profiles/transfer/spark_200g.json \
  --source-node spark3 \
  --source-path /home/spark3/models/hf/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4 \
  --fanout-all \
  --destination-path-template '/home/{node}/models/hf/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4' \
  --jobs-per-edge 16
```

Use `--dry-run` first to print the stage plan without opening data streams.

## 13-Node Ring Tests

The 13-node ring is:

```text
spark0 -> spark1 -> spark2 -> spark3 -> spark4 -> spark5 -> spark6
spark6 -> spark7 -> spark8 -> spark9 -> sparka -> sparkb -> sparkc -> spark0
```

Run a simultaneous one-transfer-per-edge health check:

```bash
scripts/ds4_parallel_iperf_ring.sh
```

A 2026-06-09 run using `iperf3 -P 8 -Z -t 8` on every adjacent edge at once
reported `1286.6 Gbit/s` summed sender throughput. The slowest edge was
`88.4 Gbit/s`; the fastest was `106.0 Gbit/s`.

Run a simultaneous bidirectional check on every adjacent edge:

```bash
scripts/ds4_bidirectional_iperf_ring.sh
```

This launches both directions across every physical edge at the same time and
sums all 26 sender directions. Use this to distinguish a one-direction
`100 Gbit/s` ceiling from full-duplex `200 Gbit/s` class behavior.

A 2026-06-09 run reported `1295.7 Gbit/s` summed sender throughput across all
26 directions. Individual directions were `41.5-57.8 Gbit/s`, which means the
current observed behavior is about `100 Gbit/s` combined per adjacent edge, not
`100 Gbit/s` in each direction at the same time.

Run a same-direction dual-rail check on every adjacent edge:

```bash
scripts/ds4_dual_rail_iperf_ring.sh
```

This is the benchmark that matches the DGX Spark 200G model: one physical link
has two logical halves. A 2026-06-09 run after assigning the missing tail rail
addresses reported `1897.2 Gbit/s` summed sender throughput across 26 rails;
the repo-driven validation script later measured `1961.7 Gbit/s` in a shorter
run.
The first seven edges mostly reached `157-188 Gbit/s` per adjacent pair. The
newly-addressed tail rails were reachable but weaker under TCP load; for
example, `spark9 -> sparka` measured about `98 Gbit/s` on `10.10.20/30` and
about `21.5 Gbit/s` on `10.10.19/30` when spot-checked. Treat `1.9 Tbit/s` as
the current measured ring ceiling until the tail cabling/port family is tuned.

The tail rail addresses can be printed, or applied on systems with suitable
sudo policy, with:

```bash
scripts/ds4_dual_rail_tail_addresses.sh
APPLY=1 scripts/ds4_dual_rail_tail_addresses.sh
```

Run first-byte pipeline latency around the full ring:

```bash
scripts/ds4_pipeline_ring_latency.sh
```

The pipeline test starts a receiver on `spark0`, reverse-starts forwarders from
`sparkc` back to `spark1`, then sends one byte from `spark0` to `spark1`. Each
node forwards as soon as it receives data. A 2026-06-09 five-run sample measured
`9.634 ms` min, `11.362 ms` median, `12.968 ms` max, and `11.452 ms` mean for
first-byte latency around all 13 hops. That first-byte overhead is not expected
to be a meaningful performance limiter for a 13-stage inference pipeline once
the pipeline is full; compute time and payload transfer size should dominate.

## Policy

- Do not use the office/control-plane hostname for model payload bytes.
- Do not serialize cluster replication from one seed to twelve destinations.
- Do not use `scp`, `sftp`, or `rsync` for model payload replication unless the
  transfer is intentionally small or administrative. They encrypt, serialize,
  or checksum in ways that leave most of the Spark fabric idle.
- Do not add compressed or encrypted payload paths to the 200G transfer docs.
- Keep `sparkN-200g` resolver entries in sync with `10.10.100.N`.
- For file trees produced by Hugging Face downloads, the copier excludes
  `.cache/` and transfers only completed files.
