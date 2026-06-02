# DS4 XOR Archive API

The DS4 archive stores immutable objects across HDD-backed volumes as a
single-parity XOR stripe set.  It is optimized for large append-only archive entries:
each extent uses the same byte offset and shard length on every drive, so a
healthy read streams all data shards in parallel while one shard is parity.

## Layout

The archive layout follows the physical drives that are actually online:

```text
4 volumes x 16TB raw: 3 data shards + 1 XOR parity shard, about 48TB usable
6 volumes x 16TB raw: 5 data shards + 1 XOR parity shard, about 80TB usable
```

Do not make four physical drives pretend to be six volumes.  That doubles shard
streams on two disks and turns a sequential archive write into avoidable seek
and SMB contention.  With the current four-drive Mac Studio shelf, use the 3+1
layout.

The extra space on the 22TB enterprise drives should host the metadata root,
catalog, write journal, repair workspace, and scratch data.  Each archive
volume also receives replicated manifests under `.ds4_archive/manifests` so the
catalog can be rebuilt if the scratch metadata is lost.

## Native Data Plane

The archive control plane is Python, but the byte-moving path is C.  Build the
native helper on the host that will stream the disks:

```bash
v2/scripts/build_ds4_archive_xor.sh /usr/local/bin/ds4_archive_xor
```

`ds4-archive` auto-detects `ds4_archive_xor` on `PATH`, or you can pin it:

```bash
export DS4_ARCHIVE_XOR=/usr/local/bin/ds4_archive_xor
```

The C helper performs the hot loop: large extent reads, 5-way split, XOR parity,
fast 64-bit shard hashes, parallel writes to all shard files, native
restore, verify, and one-shard repair.  Python remains responsible for stable
volume identity, namespace/key mapping, replicated manifests, and catalog
rebuilds.

## API Surface

Python:

```python
from pathlib import Path
from ds4_archive import ArchiveVolume, XorArchiveStore

store = XorArchiveStore(
    "/mnt/archive-meta",
    [
        ArchiveVolume("16tb0", Path("/mnt/mac/16tb0")),
        ArchiveVolume("16tb1", Path("/mnt/mac/16tb1")),
        ArchiveVolume("16tb2", Path("/mnt/mac/16tb2")),
        ArchiveVolume("22tb0", Path("/mnt/mac/22tb0")),
    ],
    native_helper="auto",
)
store.init()
store.put_path("models", "nemotron/foo", "/tmp/foo.bin")
store.stage("models", "nemotron/foo", "/tmp/restored.bin")
store.verify("models", "nemotron/foo")
store.repair("models", "nemotron/foo")
```

CLI:

```bash
ds4-archive \
  --metadata-root /mnt/archive-meta \
  --volume 16tb0=/mnt/mac/16tb0 \
  --volume 16tb1=/mnt/mac/16tb1 \
  --volume 16tb2=/mnt/mac/16tb2 \
  --volume 22tb0=/mnt/mac/22tb0 \
  init
```

Use `put`, `get`, `verify`, `repair`, `status`, `list`, and `rebuild-catalog`
with the same `--metadata-root` and four or six `--volume` arguments.

When the native helper is available, `put` and staged `get` use the C data
plane.  If it is absent, the Python implementation remains available for local
tests and metadata-level debugging; pass `--native-helper none` to force that
fallback.

## Recovery Model

Every extent records:

- one shared offset
- one shared shard length
- five data shard roles
- one parity shard role
- one xxHash64-style checksum per shard for native data-plane objects

Parity rotates by extent, so no physical drive is permanently the parity drive.
If one shard is missing or corrupt, the reader reconstructs it with XOR.  The
repair command rewrites the missing/corrupt shard at the same offset, restoring
the object to healthy state.  Two bad shards in the same extent are
unrecoverable for the `archive_3p1_xor` and `archive_5p1_xor` storage classes.
