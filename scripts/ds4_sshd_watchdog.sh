#!/bin/sh
set -eu

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

if probe_ssh
then
	exit 0
fi

logger -t ds4-sshd-watchdog "local SSH banner probe failed; restarting ssh"
if systemctl restart ssh
then
	:
else
	systemctl restart sshd
fi
sleep 2
if probe_ssh
then
	logger -t ds4-sshd-watchdog "SSH banner recovered after restart"
	exit 0
fi
logger -t ds4-sshd-watchdog "SSH banner still failing after restart"
exit 1
