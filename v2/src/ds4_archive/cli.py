from __future__ import annotations

import argparse
import json
import sys

from .service import ArchiveVolume, XorArchiveStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ds4-archive")
    parser.add_argument("--metadata-root", required=True)
    parser.add_argument("--volume", action="append", required=True, help="volume_id=/absolute/path; repeat exactly four or six times")
    parser.add_argument("--extent-payload-bytes", type=int, default=0, help="logical bytes per extent; default is 64 MiB per data shard")
    parser.add_argument("--io-workers", type=int, default=6)
    parser.add_argument("--no-fsync", action="store_true")
    parser.add_argument("--native-helper", default="auto", help="path to ds4_archive_xor, 'auto', or 'none'")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init")
    sub.add_parser("status")
    sub.add_parser("list")
    sub.add_parser("rebuild-catalog")

    put = sub.add_parser("put")
    put.add_argument("--namespace", required=True)
    put.add_argument("--key", required=True)
    put.add_argument("--input", required=True)

    get = sub.add_parser("get")
    get.add_argument("--namespace", required=True)
    get.add_argument("--key", required=True)
    get.add_argument("--output", required=True)

    verify = sub.add_parser("verify")
    verify.add_argument("--namespace", required=True)
    verify.add_argument("--key", required=True)

    repair = sub.add_parser("repair")
    repair.add_argument("--namespace", required=True)
    repair.add_argument("--key", required=True)

    args = parser.parse_args(argv)
    store = XorArchiveStore(
        args.metadata_root,
        [ArchiveVolume.parse(value) for value in args.volume],
        extent_payload_bytes=args.extent_payload_bytes,
        io_workers=args.io_workers,
        fsync=not args.no_fsync,
        native_helper=None if args.native_helper == "none" else args.native_helper,
    )
    if args.cmd == "init":
        result = store.init()
    elif args.cmd == "status":
        result = store.status()
    elif args.cmd == "list":
        result = {"format": "ds4-xor-archive-list-v1", "objects": store.list_objects()}
    elif args.cmd == "rebuild-catalog":
        result = store.rebuild_catalog()
    elif args.cmd == "put":
        result = store.put_path(args.namespace, args.key, args.input)
    elif args.cmd == "get":
        result = {"format": "ds4-xor-archive-stage-v1", "path": str(store.stage(args.namespace, args.key, args.output))}
    elif args.cmd == "verify":
        result = store.verify(args.namespace, args.key)
    elif args.cmd == "repair":
        result = store.repair(args.namespace, args.key)
    else:
        raise AssertionError(args.cmd)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
