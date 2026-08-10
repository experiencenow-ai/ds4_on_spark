#!/usr/bin/env bash
set -euo pipefail

usage()
{
  cat >&2 <<'EOF'
usage: scripts/ds4_layout_apply.sh --apply [--node-root /home/sparkN]

Creates missing canonical data roots and validates the official SparkPipe
checkout. It never creates aliases, moves, overwrites, archives, or deletes
model data.
EOF
}

node_root="${HOME}"
apply=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --apply) apply=1; shift ;;
    --node-root) node_root="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage; exit 64 ;;
  esac
done

[ "$apply" = 1 ] || { echo "refusing to change layout without --apply" >&2; exit 64; }
[ -d "$node_root" ] || { echo "missing node root: $node_root" >&2; exit 1; }
[ ! -L "$node_root" ] || { echo "refusing symlink node root: $node_root" >&2; exit 1; }

real_directory()
{
  path="$1"
  [ ! -L "$path" ] || { echo "refusing symlink canonical root: $path" >&2; exit 1; }
  if [ ! -e "$path" ]; then
    mkdir "$path"
  fi
  [ -d "$path" ] || { echo "canonical root is not a directory: $path" >&2; exit 1; }
}

for name in sparkdata srcdata extnvme kvcache; do
  real_directory "$node_root/$name"
done

repo="$node_root/sparkpipe"
[ ! -L "$repo" ] || { echo "refusing symlink SparkPipe checkout: $repo" >&2; exit 1; }
[ -d "$repo/.git" ] || { echo "missing real SparkPipe checkout: $repo" >&2; exit 1; }
origin="$(git -C "$repo" config --get remote.origin.url)"
case "$origin" in
  https://github.com/sparkpipe/sparkpipe.git|git@github.com:sparkpipe/sparkpipe.git) ;;
  *) echo "wrong SparkPipe origin: $origin" >&2; exit 1 ;;
esac

printf 'layout roots ready: node_root=%s sparkpipe=%s sparkdata=%s srcdata=%s extnvme=%s kvcache=%s\n' \
  "$node_root" "$node_root/sparkpipe" "$node_root/sparkdata" \
  "$node_root/srcdata" "$node_root/extnvme" "$node_root/kvcache"
