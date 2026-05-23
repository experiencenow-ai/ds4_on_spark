# Centaur Archive Manager Design

> Supersedes: `docs/centaur_archive_manager_design.md`

This is a canonical document. Update this file instead of adding overlapping docs.

## Scope

The Centaur archive manager is the long-term memory layer for KV cache blobs,
candidate replay bundles, and fixture/run artifacts that should not stay in
VRAM or in git. Its primary job is memory: preserve serialized KV cache pages
for later staging back into the serving stack. Fixture archival is a secondary
use and can reuse the smaller #1311 archive scripts as lower-layer helpers.

The first checked-in implementation is intentionally local-file backed. It gives
Centaur a real API and a reproducible custom-XOR parity simulation before the
operator's DAS is mounted.

## Physical Layout

Current hardware plan:

- 6 SATA bays attached to the Mac Studio DAS.
- 5 x 16 TiB drives are the append-mostly data tier.
- 1 x 22 TiB high-write drive is the staging/scratch tier.
- Sparks reach staged data through the Mac over the 10 Gbps LAN; they do not
  write directly to the archive tier in the first iteration.

Default constants in `centaur/centaur_archive_manager.py`:

```text
ARCHIVE_DATA_DRIVE_COUNT = 5
ARCHIVE_PARITY_DRIVE_COUNT = 0
ARCHIVE_STAGING_DRIVE_COUNT = 1
ARCHIVE_DATA_DRIVE_TIB = 16
ARCHIVE_STAGING_DRIVE_TIB = 22
ARCHIVE_STAGING_USABLE_TIB = 6
```

These are layout parameters, not assumptions baked into the code. Tests cover a
non-default 4-data-drive layout to keep the implementation parametric.

## XOR Scheme

The manager uses custom rotated XOR striping across the data drives. It does not
use `mdadm` RAID-5 for KV memory because Centaur needs explicit placement and
future related-group fetch control rather than opaque block-device striping.

For each blob:

1. Split the blob into stripes.
2. Each stripe has `data_drive_count - 1` data chunks and one XOR parity chunk.
3. The parity lane rotates by stripe index across the data drives.
4. Each drive gets one chunk per stripe in a per-blob part file.
5. The manifest records blob size, SHA-256, chunk size, stripe count, home drive,
   related group, and relative part paths.

This tolerates one missing drive part file per blob. Rebuild XORs the surviving
lanes for each stripe and rewrites the missing drive file, then validates the
full blob SHA-256. Reads keep one part file per data drive and fetch the
surviving parts concurrently, preserving the parallel-5-read shape for the real
DAS path.

## Related-Group Placement

The first heuristic records a stable `home_drive_index`:

```text
home_drive_index = sha256(related_group) % ARCHIVE_DATA_DRIVE_COUNT
```

The current blob bytes are striped across all data drives so the parity and
parallel-read semantics are testable immediately. The home drive is recorded for
the next placement refinement: related groups with the same domain/generation/
candidate lineage can place manifests and small sidecars together, and larger
groups can later choose between same-drive co-location and all-drive parallel
stripe fetches. The important invariant is already in the API: every KV blob has
a required `related_group`, and group fetches are first-class.

## Append-Mostly Invariant

Normal operation is append-mostly:

- `put_kv_blob` creates a new blob id and writes new per-drive part files.
- `put_bundle` copies a completed bundle into the archive tree.
- `stage_for_vram` writes scratch files only under the staging tier.
- Existing KV blobs are never modified in place except for parity rebuild of a
  missing drive part.

Manifest rewrites are small metadata updates. Garbage collection is planned
through `gc()` as a dry-run candidate list first; destructive deletion should be
a separate reviewed operation.

## API Surface

`CentaurArchiveManager` exposes the issue-required surface:

```text
put_kv_blob(key, blob_bytes, related_group, ttl=None) -> blob_id
get_kv_blob(blob_id) -> bytes
get_kv_blob_group(group_id) -> list[bytes]
stage_for_vram(blob_ids) -> path
put_bundle(bundle_dir) -> bundle_id
get_bundle(bundle_id) -> path
gc(older_than) -> dry-run delete plan
parity_check() -> integrity report
parity_rebuild(failed_drive_index) -> rebuild report
tier_metrics() -> usage and layout report
```

Error semantics are loud:

- invalid layout or empty keys raise `ValueError`;
- unknown ids raise `KeyError`;
- missing files raise `FileNotFoundError`;
- hash/parity failures raise `ArchiveIntegrityError`.

There is no silent fallback to recompute or to skip missing memory.

## Stage For VRAM

`stage_for_vram(blob_ids)` materializes requested blobs under the staging tier:

```text
staging/drive0/vram/<stage_id>/
  stage_manifest.json
  kv_blobs/<blob_id>.kv
```

The manifest records blob id, key, related group, path, size, and SHA-256. The
serving-stack patches are deliberately downstream work: vLLM and llama.cpp still
need a "load this prefix KV from this staged path" hook.

## GC Semantics

The first manager returns a dry-run GC plan:

- a blob is a delete candidate if its TTL expired;
- or if its `created_at_unix` is older than the provided threshold;
- no files are deleted by `gc()` in this PR.

Actual deletion should be another issue because it must handle group references,
promotion records, pinned memories, and operator retention policy.

## Parity Check Schedule

Recommended schedule once the DAS is live:

- Daily quick check: `parity_check()` over manifest metadata and blob hashes for
  newly written blobs.
- Weekly full check: read every blob through the manager and verify SHA-256.
- Monthly failure drill: run local simulation plus one real non-critical blob
  rebuild on a scratch copy of a drive part.
- On any missing drive file: stop writes, run `parity_rebuild(failed_drive)`,
  then run `parity_check()` before resuming writes.

The included smoke command performs the local 6-file simulation:

```text
python3 scripts/centaur_archive_manager_smoke.py
```

It writes a KV blob, deletes one simulated drive part file, rebuilds it through
XOR, stages the blob for VRAM, and verifies byte identity.

## Relationship To The Existing Fixture Archive

`docs/archive_tier_design.md`, `scripts/archive_fixture.sh`, and
`scripts/archive_restore.sh` remain useful for moving large review-hostile
fixtures out of git. This manager does not replace those scripts for fixture
cleanup; it wraps a higher-value memory-oriented API around the DAS concept.

The important change is ownership: Centaur owns KV memory lifecycle and staging.
The serving stacks consume staged paths after their downstream hooks exist.
