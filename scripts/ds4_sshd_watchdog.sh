#!/bin/sh
set -u

LOGTAG=ds4-sshd-watchdog
STATE_DIR=/run/ds4-rescue
FAIL_FILE=$STATE_DIR/sshd-watchdog.failures
LOCK_DIR=$STATE_DIR/sshd-watchdog.lock
REBOOT_AFTER="${DS4_WATCHDOG_REBOOT_AFTER:-0}"

log()
{
	if command -v logger >/dev/null 2>&1
	then
		logger -t "$LOGTAG" "$*"
	else
		echo "$LOGTAG: $*" >&2
	fi
}

probe_ssh()
{
	python3 - <<'PY'
import socket
import sys

try:
    sock = socket.create_connection(("127.0.0.1", 22), timeout=2.0)
    sock.settimeout(2.0)
    data = sock.recv(128)
    sock.close()
    sys.exit(0 if data.startswith(b"SSH-") else 1)
except Exception:
    sys.exit(1)
PY
}

restart_ssh()
{
	if systemctl restart ssh
	then
		return 0
	fi
	systemctl restart sshd
}

kill_container()
{
	name="$1"
	if [ "$name" = "" ]
	then
		return 0
	fi
	log "killing container $name"
	docker kill "$name" >/dev/null 2>&1 || true
}

kill_allowlisted_containers()
{
	name=""
	if ! command -v docker >/dev/null 2>&1
	then
		return 0
	fi
	for name in vllm_deepseek_v4_flash
	do
		kill_container "$name"
	done
	docker ps --format '{{.Names}}' 2>/dev/null | while IFS= read -r name
	do
		case "$name" in
		vllm_*|ds4_vllm_*|centaur_vllm_*)
			kill_container "$name"
			;;
		esac
	done
}

kill_pattern()
{
	pat="$1"
	log "killing processes matching $pat"
	pkill -9 -f "$pat" >/dev/null 2>&1 || true
}

kill_allowlisted_processes()
{
	kill_pattern '/usr/local/bin/vllm serve'
	kill_pattern '/usr/bin/python3 /usr/local/bin/vllm serve'
	kill_pattern 'vllm serve /models/'
	kill_pattern 'VLLM::'
	if [ "${DS4_WATCHDOG_KILL_RAY:-0}" = "1" ]
	then
		kill_pattern '/ray/'
		kill_pattern 'raylet'
	fi
}

clear_failures()
{
	mkdir -p "$STATE_DIR"
	printf '0\n' > "$FAIL_FILE"
}

record_failure()
{
	old=0
	mkdir -p "$STATE_DIR"
	if [ -r "$FAIL_FILE" ]
	then
		old="$(cat "$FAIL_FILE" 2>/dev/null || echo 0)"
	fi
	case "$old" in
	''|*[!0-9]*)
		old=0
		;;
	esac
	new=$((old + 1))
	printf '%s\n' "$new" > "$FAIL_FILE"
	echo "$new"
}

maybe_reboot()
{
	failures="$1"
	if [ "$REBOOT_AFTER" = "0" ] || [ "$REBOOT_AFTER" = "" ]
	then
		return 0
	fi
	case "$REBOOT_AFTER" in
	*[!0-9]*)
		log "invalid DS4_WATCHDOG_REBOOT_AFTER=$REBOOT_AFTER; reboot escalation disabled"
		return 0
		;;
	esac
	if [ "$failures" -lt "$REBOOT_AFTER" ]
	then
		return 0
	fi
	log "SSH still wedged after $failures failures; rebooting by watchdog policy"
	systemctl reboot --force
}

run_rescue()
{
	reason="$1"
	log "$reason; restarting ssh"
	restart_ssh || true
	sleep 2
	if probe_ssh
	then
		log "SSH banner recovered after restart"
		clear_failures
		return 0
	fi
	log "SSH banner still failing after restart; killing allowlisted heavy runtimes"
	kill_allowlisted_containers
	kill_allowlisted_processes
	sleep 5
	restart_ssh || true
	sleep 2
	if probe_ssh
	then
		log "SSH banner recovered after killing allowlisted runtimes"
		clear_failures
		return 0
	fi
	failures="$(record_failure)"
	log "SSH banner still failing after heavy-runtime kill; consecutive_failures=$failures"
	maybe_reboot "$failures"
	return 1
}

mkdir -p "$STATE_DIR"
if ! mkdir "$LOCK_DIR" 2>/dev/null
then
	log "previous watchdog run still active; skipping"
	exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT INT TERM

case "${1:-}" in
--force|rescue|rescue-now)
	run_rescue "forced local self-rescue requested"
	exit $?
	;;
esac

if probe_ssh
then
	clear_failures
	exit 0
fi

run_rescue "local SSH banner probe failed"
exit $?
