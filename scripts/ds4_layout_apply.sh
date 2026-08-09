#!/usr/bin/env bash
set -euo pipefail

usage()
{
  cat >&2 <<'EOF'
usage: scripts/ds4_layout_apply.sh --apply [--node-root /home/sparkN]

Creates the canonical small-file roots and stable aliases. It never moves,
overwrites, archives, or deletes model data.
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

mkdir -p "$node_root/sparkdata" "$node_root/srcdata"

if [ ! -e "$node_root/sparkpipe" ] && git -C "$node_root/src/ds4_on_spark" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  ln -s "$node_root/src/ds4_on_spark" "$node_root/sparkpipe"
fi

mounted=0
if command -v mountpoint >/dev/null 2>&1 && mountpoint -q "$node_root/ds4_nvme"; then
  mounted=1
elif command -v findmnt >/dev/null 2>&1; then
  mount_target="$(findmnt -T "$node_root/ds4_nvme" -n -o TARGET 2>/dev/null || true)"
  if [ "$mount_target" = "$node_root/ds4_nvme" ]; then
    mounted=1
  fi
fi

extnvme="$node_root/extnvme"
legacy_extnvme="$node_root/ds4_nvme"
if [ -L "$extnvme" ]; then
  target="$(readlink "$extnvme")"
  if [ "$target" != "$legacy_extnvme" ]; then
    echo "refusing unexpected extnvme symlink: $extnvme -> $target" >&2
    exit 1
  fi
  if [ "$mounted" = 0 ]; then
    rm "$extnvme"
    mkdir -p "$extnvme"
  fi
elif [ -e "$extnvme" ]; then
  if [ "$mounted" = 1 ]; then
    if rmdir "$extnvme" 2>/dev/null; then
      ln -s "$legacy_extnvme" "$extnvme"
    else
      echo "WARN: preserving non-empty extnvme directory while disk is mounted: $extnvme" >&2
    fi
  fi
else
  if [ "$mounted" = 1 ]; then
    ln -s "$legacy_extnvme" "$extnvme"
  else
    mkdir -p "$extnvme"
  fi
fi

printf 'layout roots ready: node_root=%s sparkpipe=%s sparkdata=%s srcdata=%s extnvme=%s\n' \
  "$node_root" "$node_root/sparkpipe" "$node_root/sparkdata" \
  "$node_root/srcdata" "$node_root/extnvme"
