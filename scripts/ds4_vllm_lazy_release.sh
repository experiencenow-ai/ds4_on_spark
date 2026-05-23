#!/usr/bin/env sh
set -eu

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
MODEL="${1:-${MODEL:-}}"

url="http://$HOST:$PORT/ds4/release"
if [ -n "$MODEL" ]; then
	url="$url?model=$MODEL"
fi
curl -fsS -X POST "$url"
echo
