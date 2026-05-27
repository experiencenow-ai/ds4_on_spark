# Spark 200G Transfer

Bulk model payloads must use the Spark fabric, not the office/control-plane
network. Plain `sparkN` names are for control commands. Bulk data targets are
`sparkN-200g`, which must resolve to `10.10.100.N`, or the explicit
`10.10.100.N` address from `profiles/transfer/spark_200g.json`.

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

## Full Fan-Out

The default fan-out for a spark3 seed is:

```text
stage 1: spark3 -> spark2, spark3 -> spark4
stage 2: spark2 -> spark1, spark4 -> spark5
stage 3: spark1 -> spark0, spark5 -> spark6
stage 4: spark6 -> spark7
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

## Policy

- Do not use the office/control-plane hostname for model payload bytes.
- Do not serialize cluster replication from one seed to seven destinations.
- Do not add compressed or encrypted payload paths to the 200G transfer docs.
- Keep `sparkN-200g` resolver entries in sync with `10.10.100.N`.
- For file trees produced by Hugging Face downloads, the copier excludes
  `.cache/` and transfers only completed files.
