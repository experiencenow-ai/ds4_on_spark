# Spark Ring Fast Transfer

Use this path for model weights, runtime tarballs, cache shards, and other
large Spark-to-Spark payloads. The Mac and Wi-Fi are the control plane. The
200Gbps ring is the data plane.

## Rule

Do not move initial bulk payloads with `scp`, Mac-local `rsync`, or anything
that hairpins bytes through the operator laptop. Use:

```bash
scripts/spark_ring_fast_copy.py SRC DST --engine native --parallel 32 --chunk-mib 512 --link both
```

`SRC` and `DST` use `sparkN:/absolute/path` syntax. The SSH connection starts
workers on the Sparks, but the payload TCP streams use the 200G addresses.

## Common Cases

Adjacent model copy over both raw rails:

```bash
scripts/spark_ring_fast_copy.py spark0:/home/spark0/models/ds4/model.gguf spark1:/home/spark1/models/ds4/model.gguf --engine native --parallel 32 --chunk-mib 512 --link both
```

Single-rail debug copy:

```bash
scripts/spark_ring_fast_copy.py spark0:/tmp/runtime.tar spark1:/tmp/runtime.tar --engine native --parallel 8 --chunk-mib 256 --link first
```

Directory tree copy over the ring:

```bash
scripts/spark_ring_fast_copy.py spark0:/home/spark0/models/ds4 spark1:/home/spark1/models/ds4 --engine python --parallel 8
```

Preview the route without starting workers:

```bash
scripts/spark_ring_fast_copy.py spark7:/tmp/a.gguf spark0:/tmp/a.gguf --dry-run
```

## Choosing A Link

- `--link both`: adjacent Spark pairs only; alternate chunks over both raw
  `/30` rails.
- `--link first`: adjacent Spark pairs only; use the first raw rail.
- `--link second`: adjacent Spark pairs only; use the second raw rail.

Use `both` for large regular files between neighbors. Use `first` or `second`
when debugging one physical rail. For non-neighbor copies, copy hop-by-hop along
the path printed by the helper instead of routing bulk payloads through Wi-Fi or
the Mac.

## Engines

- `native`: regular files only. Splits the source into fixed-size chunks, starts
  `nc` receivers on the destination, sends with `dd` from the source, then
  reassembles atomically on the destination.
- `auto`: `native` for files, `python` for directories.
- `python`: regular files or directories. Starts Python socket helpers over SSH,
  then sends payload streams over the raw 200G destination IPs.

## Verification

Before blaming the transfer tool, verify the ring:

```bash
scripts/spark_ring_probe.sh spark0 spark1
scripts/spark_ring_probe_latency.sh spark0 spark1
```

For an adjacent edge, a healthy transfer should use the raw `10.10.x.y`
addresses listed in `SPARKNETWORK.md`, not Wi-Fi hostnames. `ssh sparkN` is only
there to start and supervise the remote workers.

## Failure Rules

- If an adjacent `--link both` copy is slow, retry `--link first` and
  `--link second` to isolate a bad rail.
- If a non-adjacent copy is needed, follow the helper's hop-by-hop path and copy
  neighbor-to-neighbor.
- Check the destination path before running the command. The native file engine
  prepares the destination file before filling chunks.
- Use `rsync` only for final metadata/delta validation or small control files,
  not initial model payload movement.
