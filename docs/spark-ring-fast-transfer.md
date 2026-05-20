# Spark Ring Fast Transfer

Use this when moving model/runtime payloads between directly connected Spark
neighbors. The 200G fabric is fast enough that SSH payload copies are the wrong
default for bulk data.

## Rule

SSH is for control. The payload should move on raw TCP over the declared 200G
ring IPs in `sparknetwork.json`.

Avoid these for initial bulk movement:

- `scp`
- `rsync -e ssh`
- `tar | ssh`
- compressed streams for already-compressed model artifacts

Those tools are still fine for manifests, metadata checks, and final small
delta passes.

## Utility

Use `scripts/spark_ring_fast_copy.py`. It reads `sparknetwork.json`, refuses
non-neighbor transfers, starts receivers over SSH, then sends the data over the
200G neighbor IPs with multiple unencrypted TCP streams.

For regular files, the default `--engine auto` path uses native `dd` and
OpenBSD `nc` on the Sparks. SSH only starts the workers. For directories, the
tool falls back to its Python helper so it can walk the tree, create
directories, and preserve symlinks.

Examples:

```bash
scripts/spark_ring_fast_copy.py --engine native --parallel 32 --chunk-mib 512 spark2:/models/deepseek.gguf spark3:/models/
scripts/spark_ring_fast_copy.py --engine python --parallel 16 spark3:/models/runtime/ spark4:/models/
scripts/spark_ring_fast_copy.py --dry-run spark5:/models/foo.gguf spark6:/models/
```

The current seven-node ring order is:

```text
spark0 -> spark1 -> spark2 -> spark3 -> spark4 -> spark5 -> spark6
```

So `spark2:/x -> spark3:/x` is valid, and `spark2:/x -> spark5:/x` is a
multi-hop transfer rather than one direct high-speed neighbor copy. Stage it
hop-by-hop:

```bash
scripts/spark_ring_fast_copy.py --engine native --parallel 32 --chunk-mib 512 spark2:/models/foo.gguf spark3:/models/
scripts/spark_ring_fast_copy.py --engine native --parallel 32 --chunk-mib 512 spark3:/models/foo.gguf spark4:/models/
scripts/spark_ring_fast_copy.py --engine native --parallel 32 --chunk-mib 512 spark4:/models/foo.gguf spark5:/models/
```

## Tuning

Start with:

```bash
scripts/spark_ring_fast_copy.py --engine native --parallel 32 --chunk-mib 512 spark2:/src/file spark3:/dst/
```

Then tune:

- Increase `--parallel` to `48` or `64` for one huge file if CPU and IRQ load
  are still low.
- Use `--link both` by default to spread streams across both parallel 200G
  neighbor links.
- Use `--link first` or `--link second` to isolate a bad cable/NIC.
- Use larger `--chunk-mib` for huge model files, such as `512`, `1024`, or
  `2048`.
- Keep compression off for GGUF, safetensors, zip, zstd, tar.zst, and other
  already-compressed artifacts.
- Do not use `/dev/shm` for durable payloads. It is useful for link testing,
  but files there can disappear when a login session ends.

## Verification

Verify the fabric first:

```bash
ssh spark3 'for ip in 10.10.5.2 10.10.6.2 10.10.7.2 10.10.8.2; do ping -M do -s 8972 -c 1 "$ip"; done'
ssh spark5 'for ip in 10.10.9.1 10.10.10.1 10.10.11.2 10.10.12.2; do ping -M do -s 8972 -c 1 "$ip"; done'
```

For raw network ceiling, use iperf with parallel streams on the exact neighbor
IP when `iperf3` is installed on both nodes. Example for Spark2 to Spark3:

```bash
ssh spark3 'iperf3 -s -B 10.10.5.1 -1'
ssh spark2 'iperf3 -c 10.10.5.1 -P 16 -w 16M -t 20'
```

If `iperf3` is missing, use the native `nc`/`dd` ceiling test. This sends 4 GiB
over both Spark2-Spark3 ring links and drops it at the receiver:

```bash
ssh spark3 'for i in $(seq 0 63); do port=$((25700+i)); (nc -l $port | dd of=/dev/null bs=64M status=none) & done; wait'
ssh spark2 '/usr/bin/time -f elapsed=%e sh -c '\''for i in $(seq 0 63); do port=$((25700+i)); ip=10.10.5.1; if [ $((i%2)) -eq 1 ]; then ip=10.10.6.1; fi; (dd if=/dev/zero bs=64M count=1 status=none | nc -N $ip $port) & done; wait'\'''
```

That test is intentionally network-only. If it is fast but file copies are
slow, the next bottleneck is the source read path, destination write path, IRQ
placement, or PCIe/NVMe layout.

For data integrity on large files, compare checksums after transfer:

```bash
ssh spark2 'sha256sum /models/foo.gguf'
ssh spark3 'sha256sum /models/foo.gguf'
```

For directories, run a final metadata/delta pass after the fast copy if needed:

```bash
rsync -a --dry-run --checksum -e ssh spark2:/models/foo/ spark3:/models/foo/
```

That final rsync should be tiny. If it wants to move the whole payload, the fast
copy did not land in the intended destination.

## Current Spark2-Spark3 Smoke Tests

Verified on 2026-05-20:

- `scripts/spark_ring_fast_copy.py --engine native --parallel 16 --chunk-mib 16`
  copied a 256 MiB file from Spark2 to Spark3 over `10.10.5.1,10.10.6.1`; both
  SHA-256 hashes matched.
- Native `nc`/`dd` network-only ceiling over 64 parallel streams moved 4 GiB to
  `/dev/null` in `0.43s` as timed on Spark2.
- Single-file writes to `/tmp` were slower than the network-only test. Treat
  that as a storage/write-path issue to fix, not as permission to use SSH for
  bulk payloads.

## DS4 Standard Model Staging Evidence

Artifact:
`fixtures/spark_ring_fast_transfer/ds4_vllm_pp7_standard_model_stage_20260520.example.json`

The standard DeepSeek-V4-Flash model and vLLM runtime were staged onto
Spark3-Spark6 for PP=7 experiments. The full model payload is `159633386574`
bytes across `55` files. SSH/rsync was abandoned after it left most of the 200G
fabric idle; raw ring transfers completed the payload hops:

| Hop | Path | Streams | Seconds | GiB/s |
|-----|------|---------|---------|-------|
| Spark2 -> Spark3 | `10.10.5.x` | single raw `tar | nc` | `148.25` | `1.003` |
| Spark3 -> Spark4 | `10.10.7.x` + `10.10.8.x` | dual raw `tar | nc` | `97.81` | `1.520` |
| Spark4 -> Spark5 | `10.10.9.x` + `10.10.10.x` | dual raw `tar | nc` | `93.03` | `1.598` |
| Spark5 -> Spark6 | `10.10.11.x` + `10.10.12.x` | dual raw `tar | nc` | `135.48` | `1.097` |

Every destination ended with `55` files and total size `159633386574` bytes.
The next tuning target is more parallel file/chunk streams and cleaner receive
workers, because observed model-copy throughput is storage/syscall limited well
before the network-only ceiling.

## Why This Exists

On this cluster, `rsync` over SSH can leave more than 90% of the fabric unused:
one encrypted stream, one SSH process, filesystem metadata round-trips, and CPU
limits. That is not a network limit. Bulk payload movement should use multiple
raw TCP streams over the ring, then use SSH/rsync only for control and final
validation.
