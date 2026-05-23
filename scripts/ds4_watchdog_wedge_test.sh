#!/usr/bin/env bash
set -euo pipefail

target="${1:-}"
timeout_s="${DS4_WATCHDOG_TEST_TIMEOUT:-180}"
poll_s="${DS4_WATCHDOG_TEST_POLL:-5}"
sudo_password="${DS4_SUDO_PASSWORD:-}"
test_tag="${DS4_WATCHDOG_TEST_TAG:-VLLM::watchdog-port-wedge}"
mem_mib="${DS4_WATCHDOG_TEST_MEM_MIB:-512}"

if [ "$target" = "" ]
then
	echo "usage: DS4_SUDO_PASSWORD=<remote-sudo-password> $0 <spark-ssh-target>" >&2
	exit 2
fi

ssh_opts=(-o BatchMode=yes -o ConnectTimeout=5)

ssh_check()
{
	ssh "${ssh_opts[@]}" "$target" 'python3 - <<'"'"'PY'"'"'
import socket
import sys
try:
    sock = socket.create_connection(("127.0.0.1",22),timeout=2.0)
    sock.settimeout(2.0)
    data = sock.recv(64)
    sock.close()
    print(data.decode("ascii","replace").strip())
    sys.exit(0 if data.startswith(b"SSH-") else 1)
except Exception as exc:
    print(type(exc).__name__ + ":" + str(exc))
    sys.exit(1)
PY'
}

run_sudo_script()
{
	remote_tag="$1"
	remote_mem_mib="$2"
	if [ "$sudo_password" = "" ]
	then
		ssh "$target" "sudo /bin/sh -s -- '$remote_tag' '$remote_mem_mib'"
	else
		{ printf '%s\n' "$sudo_password"; cat; } | ssh "$target" "sudo -S /bin/sh -s -- '$remote_tag' '$remote_mem_mib'"
	fi
}

echo "== precheck: $target SSH banner =="
ssh_check

echo "== starting synthetic SSH-port wedge on $target: tag=$test_tag mem_mib=$mem_mib =="
run_sudo_script "$test_tag" "$mem_mib" <<'REMOTE'
set -eu
TAG="${1:-VLLM::watchdog-port-wedge}"
MEM_MIB="${2:-512}"
mkdir -p /run/ds4-rescue
cat >/tmp/ds4_watchdog_vllm_port_wedge.py <<'PY'
#!/usr/bin/env python3
import multiprocessing
import os
import socket
import sys
import time

def burn():
    x = 0
    while True:
        x = ((x * 1103515245) + 12345) & 0x7fffffff

def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else "VLLM::watchdog-port-wedge"
    mem_mib = int(sys.argv[2]) if len(sys.argv) > 2 else 512
    workers = max(1,min(8,(os.cpu_count() or 2) // 2))
    payload = bytearray(mem_mib * 1024 * 1024)
    for i in range(0,len(payload),4096):
        payload[i] = 1
    procs = []
    for _ in range(workers):
        p = multiprocessing.Process(target=burn)
        p.daemon = True
        p.start()
        procs.append(p)
    sock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    sock.bind(("0.0.0.0",22))
    sock.listen(128)
    print("%s pid=%d workers=%d mem_mib=%d" % (tag,os.getpid(),workers,mem_mib),flush=True)
    while True:
        conn, _addr = sock.accept()
        time.sleep(30)
        conn.close()

if __name__ == "__main__":
    main()
PY
chmod 0755 /tmp/ds4_watchdog_vllm_port_wedge.py
systemctl stop ssh.socket 2>/dev/null || true
systemctl stop ssh || systemctl stop sshd || true
nohup python3 /tmp/ds4_watchdog_vllm_port_wedge.py "$TAG" "$MEM_MIB" >/tmp/ds4_watchdog_vllm_port_wedge.log 2>&1 &
echo $! >/run/ds4-rescue/watchdog-wedge-test.pid
REMOTE

echo "== waiting for watchdog recovery, timeout ${timeout_s}s =="
start="$(date +%s)"
while true
do
	now="$(date +%s)"
	elapsed="$((now - start))"
	if [ "$elapsed" -gt "$timeout_s" ]
	then
		echo "watchdog recovery timed out after ${timeout_s}s" >&2
		exit 1
	fi
	if ssh_check >/tmp/ds4_watchdog_wedge_ssh_check.txt 2>&1
	then
		cat /tmp/ds4_watchdog_wedge_ssh_check.txt
		break
	fi
	echo "still wedged at ${elapsed}s: $(tr '\n' ' ' </tmp/ds4_watchdog_wedge_ssh_check.txt)"
	sleep "$poll_s"
done

echo "== postcheck: wedge process and watchdog logs =="
ssh "${ssh_opts[@]}" "$target" 'pgrep -af "VLLM::watchdog-port-wedge|ds4_watchdog_vllm_port_wedge" | grep -v "pgrep -af" | grep -v "grep -v" || true'
ssh "${ssh_opts[@]}" "$target" 'journalctl -t ds4-sshd-watchdog --since "5 minutes ago" --no-pager || true'
ssh "${ssh_opts[@]}" "$target" 'systemctl is-active ssh; systemctl is-active ds4-sshd-watchdog.timer; systemctl --user is-active ds4-rescue-agent.service'
