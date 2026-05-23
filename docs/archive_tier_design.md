# Centaur Archive Tier Design

> Supersedes: `docs/archive_tier_design.md`

This is a canonical document. Update this file instead of adding overlapping docs.

> Supersession note: this document describes the #1311 fixture archive helper.
> For Centaur's KV-cache long-term memory subsystem and custom XOR layout, see
> `docs/centaur_archive_manager_design.md`.

## Decision

Centaur archive storage is a Mac-owned DAS volume mounted at `/Volumes/CentaurArchive`. The operator-ordered enclosure is configured as Linux `mdadm` RAID-5 over six drives, 5x16TB plus 1x22TB. RAID-5 is the chosen XOR-parity layout because the operator explicitly requested XOR parity and the workload is mostly large append/read artifact bundles, not low-latency random writes.

The Mac is the gatekeeper. Sparks do not write directly to the archive tier. Spark jobs finish into local run directories, then the Mac archives completed bundles with `scripts/archive_fixture.sh`. Replay restores with `scripts/archive_restore.sh` or pulls from the archive to a Spark scratch path as a separate operator action.

## Mount And Layout

Recommended mount:

```text
/Volumes/CentaurArchive
```

Top-level layout:

```text
/Volumes/CentaurArchive/fixtures/...
/Volumes/CentaurArchive/run_bundles/...
/Volumes/CentaurArchive/trace_snapshots/...
/Volumes/CentaurArchive/replay_archives/...
```

Repo fixtures keep small summary JSON, stubs, schemas, and manifests. Large raw outputs move to the archive tier. The repo-side manifest is `fixtures/fixtures_manifest.json`, with schema in `fixtures/fixtures_manifest.schema.json`.

## Access Semantics

The default access mode is pull-on-replay:

1. A Spark or local run writes artifacts to the repo or scratch.
2. The Mac archives completed artifacts into `/Volumes/CentaurArchive`.
3. The repo keeps `fixtures/fixtures_manifest.json` plus a small stub where the fixture used to live.
4. Replay restores only the requested fixture.

NFS is optional later for read-only browsing, but it is not the default. SSHFS is rejected for the primary path because mount behavior and disconnect handling are too brittle for archival integrity. Direct Spark writes are rejected because fixture ownership and checksum manifests should be serialized through one host.

## Retention Policy

Keep these online in the repo:

- Summary records under roughly 1 MB.
- Schemas, validators, and routing fixtures.
- The newest three generations per active domain if each generation is small enough for normal git review.
- All stubs and manifests for archived artifacts.

Archive these after 30 days or immediately when they exceed normal review size:

- Raw LongMemEval traces and model prompt/completion caches.
- vLLM and DS4 throughput sweep raw event logs.
- Replay bundles larger than 10 MB.
- Full candidate-machine run bundles after a promoted summary exists.

Keep archived raw artifacts for at least one year unless the operator explicitly prunes them after copying to cold storage.

## Integrity

Every archived path records:

- Original repo path.
- Archive path.
- Total size.
- Per-file SHA-256 entries.
- Directory tree SHA-256 for directories.
- Archive timestamp.

Weekly storage integrity:

```text
sudo mdadm --detail /dev/md/centaur_archive
echo check | sudo tee /sys/block/md*/md/sync_action
cat /proc/mdstat
```

Weekly manifest integrity:

```text
find /Volumes/CentaurArchive -type f -print0 | xargs -0 shasum -a 256 >/Volumes/CentaurArchive/.weekly_sha256.txt
```

If `mdadm --detail` reports a degraded array or the weekly checksum walk fails, stop archive writes, notify the operator, and replace/rebuild before resuming.

## Operator Bring-Up

1. Attach the six-drive DAS to the Mac or designated Linux host.
2. Create one GPT data partition per drive, using the common 16TB size. The extra capacity on the 22TB drive remains unused unless the operator creates a separate non-critical scratch partition.
3. Create a single RAID-5 array across the six equal-sized data partitions:

```text
sudo mdadm --create /dev/md/centaur_archive --level=5 --raid-devices=6 /dev/disk/by-id/<drive0-part> /dev/disk/by-id/<drive1-part> /dev/disk/by-id/<drive2-part> /dev/disk/by-id/<drive3-part> /dev/disk/by-id/<drive4-part> /dev/disk/by-id/<drive5-part>
```

4. Format the array as APFS on macOS-managed hardware or ext4/xfs on Linux-managed hardware. The path visible to this repo must be `/Volumes/CentaurArchive`.
5. Persist the mdadm array in the host's mdadm config if Linux owns the enclosure:

```text
sudo mdadm --detail --scan | sudo tee -a /etc/mdadm/mdadm.conf
```

6. Create archive directories:
```text
mkdir -p /Volumes/CentaurArchive/fixtures /Volumes/CentaurArchive/run_bundles /Volumes/CentaurArchive/trace_snapshots /Volumes/CentaurArchive/replay_archives
```

7. Set `CENTAUR_ARCHIVE_ROOT=/Volumes/CentaurArchive` in the Mac shell profile used by operators.
8. Run the smoke test:

```text
python3 -m unittest tests.archive_fixture_test -q
```

## Commands

Archive one fixture:

```text
scripts/archive_fixture.sh fixtures/pipeline_quality/big_run_20260601
```

Restore it:

```text
scripts/archive_restore.sh fixtures/pipeline_quality/big_run_20260601
```

Use a temporary archive root for testing:

```text
scripts/archive_fixture.sh fixtures/sample.json --archive-root /tmp/centaur-archive-test
scripts/archive_restore.sh fixtures/sample.json --manifest fixtures/fixtures_manifest.json
```
