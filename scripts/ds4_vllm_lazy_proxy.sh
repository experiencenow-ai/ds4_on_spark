#!/usr/bin/env sh
set -eu

FRONT_HOST="${FRONT_HOST:-127.0.0.1}"
FRONT_PORT="${FRONT_PORT:-8000}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-18000}"
LOG_DIR="${LOG_DIR:-$HOME/vllm-lazy-logs}"
SCRIPT="${SCRIPT:-$HOME/bin/ds4_vllm_lazy_proxy.py}"
WAIT="${WAIT:-1}"
DEEPSEEK_V4_REMOTE_BASE="${DEEPSEEK_V4_REMOTE_BASE:-http://10.10.100.14:8000}"
DEEPSEEK_V4_REMOTE_MODEL="${DEEPSEEK_V4_REMOTE_MODEL:-deepseek-v4-flash}"
DS4_REMOTE_MODELS_JSON="${DS4_REMOTE_MODELS_JSON:-}"

mkdir -p "$LOG_DIR"
if [ ! -x "$SCRIPT" ]; then
	echo "missing lazy proxy script: $SCRIPT" >&2
	exit 2
fi

pid_file="$LOG_DIR/lazy-proxy-$FRONT_PORT.pid"
log_file="$LOG_DIR/lazy-proxy-$FRONT_PORT.log"

if [ -s "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
	echo "lazy proxy already running: pid=$(cat "$pid_file") endpoint=http://$FRONT_HOST:$FRONT_PORT/v1 log=$log_file"
else
	FRONT_HOST="$FRONT_HOST" FRONT_PORT="$FRONT_PORT" BACKEND_HOST="$BACKEND_HOST" BACKEND_PORT="$BACKEND_PORT" LOG_DIR="$LOG_DIR" \
		DEEPSEEK_V4_REMOTE_BASE="$DEEPSEEK_V4_REMOTE_BASE" DEEPSEEK_V4_REMOTE_MODEL="$DEEPSEEK_V4_REMOTE_MODEL" \
		DS4_REMOTE_MODELS_JSON="$DS4_REMOTE_MODELS_JSON" \
		nohup python3 "$SCRIPT" >"$log_file" 2>&1 &
	echo "$!" >"$pid_file"
	echo "started lazy proxy: pid=$(cat "$pid_file") endpoint=http://$FRONT_HOST:$FRONT_PORT/v1 backend=http://$BACKEND_HOST:$BACKEND_PORT/v1 log=$log_file"
fi

if [ "$WAIT" = "1" ]; then
	i=0
	while [ "$i" -lt 60 ]; do
		if curl -fsS "http://$FRONT_HOST:$FRONT_PORT/health" >/dev/null; then
			curl -fsS "http://$FRONT_HOST:$FRONT_PORT/v1/models" | python3 -c 'import sys,json; print(len(json.load(sys.stdin)["data"]))'
			exit 0
		fi
		if ! kill -0 "$(cat "$pid_file")" 2>/dev/null; then
			echo "lazy proxy exited before readiness" >&2
			tail -120 "$log_file" >&2 || true
			exit 3
		fi
		i=$((i + 1))
		sleep 1
	done
	echo "timeout waiting for lazy proxy readiness" >&2
	tail -120 "$log_file" >&2 || true
	exit 4
fi
