#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/build/ds4_archive_xor}"
CC_BIN="${CC:-cc}"

mkdir -p "$(dirname "$OUT")"
"$CC_BIN" -O3 -std=c11 -Wall -Wextra -pthread -o "$OUT" "$ROOT/src/ds4_archive/native/ds4_archive_xor.c"
echo "$OUT"
