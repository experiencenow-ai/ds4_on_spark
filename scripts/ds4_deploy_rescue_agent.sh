#!/bin/sh
set -eu

usage()
{
	echo "usage: $0 spark2 spark3 ..." >&2
	exit 1
}

if [ "$#" -eq 0 ]
then
	usage
fi

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
sudo_password="${DS4_SUDO_PASSWORD:-}"
ssh_opts="${DS4_SSH_OPTS:-}"
scp_opts="${DS4_SCP_OPTS:-$ssh_opts}"
keys_file="$(mktemp)"
cleanup()
{
	rm -f "$keys_file"
}
trap cleanup EXIT INT TERM

ensure_peer_key()
{
	host="$1"
	ssh $ssh_opts "$host" 'mkdir -p "$HOME/.ssh"; chmod 700 "$HOME/.ssh"; if [ ! -s "$HOME/.ssh/id_ed25519.pub" ]; then ssh-keygen -q -t ed25519 -N "" -f "$HOME/.ssh/id_ed25519" -C "ds4-peer-ssh:$(whoami)@$(hostname)"; fi; chmod 600 "$HOME/.ssh/id_ed25519"; chmod 644 "$HOME/.ssh/id_ed25519.pub"; cat "$HOME/.ssh/id_ed25519.pub"'
}

install_peer_keys()
{
	host="$1"
	ssh $ssh_opts "$host" 'mkdir -p "$HOME/.ssh"; chmod 700 "$HOME/.ssh"; touch "$HOME/.ssh/authorized_keys"; chmod 600 "$HOME/.ssh/authorized_keys"; tmp="$(mktemp)"; cat > "$tmp"; while IFS= read -r key; do [ "$key" != "" ] || continue; grep -qxF "$key" "$HOME/.ssh/authorized_keys" || printf "%s\n" "$key" >> "$HOME/.ssh/authorized_keys"; done < "$tmp"; rm -f "$tmp"' < "$keys_file"
}

copy_payload()
{
	host="$1"
	ssh $ssh_opts "$host" 'mkdir -p "$HOME/.ds4-rescue" "$HOME/.config/systemd/user"'
	scp $scp_opts "$repo_dir/scripts/ds4_peer_ssh_heartbeat.py" "$host:.ds4-rescue/ds4_peer_ssh_heartbeat.py"
	scp $scp_opts "$repo_dir/scripts/spark_memory_launch_guard.py" "$host:.ds4-rescue/spark_memory_launch_guard.py"
	scp $scp_opts "$repo_dir/scripts/spark_extend_swap.sh" "$host:.ds4-rescue/spark_extend_swap.sh"
	scp $scp_opts "$repo_dir/scripts/ds4-peer-ssh-heartbeat.service" "$host:.config/systemd/user/ds4-peer-ssh-heartbeat.service"
	scp $scp_opts "$repo_dir/scripts/ds4-peer-ssh-heartbeat.timer" "$host:.config/systemd/user/ds4-peer-ssh-heartbeat.timer"
}

start_user_service()
{
	host="$1"
	ssh $ssh_opts "$host" 'chmod 700 "$HOME/.ds4-rescue"; mkdir -p "$HOME/.ds4-rescue/peer-trim-votes" "$HOME/.ds4-rescue/trim-state"; chmod 700 "$HOME/.ds4-rescue/peer-trim-votes" "$HOME/.ds4-rescue/trim-state"; chmod 755 "$HOME/.ds4-rescue/"*.sh "$HOME/.ds4-rescue/"*.py; systemctl --user daemon-reload; systemctl --user disable --now ds4-rescue-agent 2>/dev/null || true; systemctl --user enable ds4-peer-ssh-heartbeat.timer; systemctl --user restart ds4-peer-ssh-heartbeat.timer; systemctl --user --no-pager --plain list-timers ds4-peer-ssh-heartbeat.timer'
}

extend_swap()
{
	host="$1"
	if [ "${DS4_EXTEND_SWAP:-0}" != "1" ]
	then
		return 0
	fi
	if [ "${DS4_REMOTE_SUDO_TTY:-0}" = "1" ]
	then
		ssh $ssh_opts -tt "$host" 'sudo "$HOME/.ds4-rescue/spark_extend_swap.sh" /swap-extra-16g.img 16'
	elif [ "$sudo_password" = "" ]
	then
		ssh $ssh_opts "$host" 'sudo -n "$HOME/.ds4-rescue/spark_extend_swap.sh" /swap-extra-16g.img 16'
	else
		printf '%s\n' "$sudo_password" | ssh $ssh_opts "$host" 'sudo -S -p "" "$HOME/.ds4-rescue/spark_extend_swap.sh" /swap-extra-16g.img 16'
	fi
}

echo "==> preparing peer SSH key mesh"
for host in "$@"
do
	echo "==> $host: ensure peer SSH key"
	ensure_peer_key "$host" >> "$keys_file"
done
for host in "$@"
do
	echo "==> $host: install peer authorized keys"
	install_peer_keys "$host"
done

for host in "$@"
do
	echo "==> $host: copy quorum monitor payload"
	copy_payload "$host"
	echo "==> $host: start user quorum monitor"
	start_user_service "$host"
	echo "==> $host: extend persistent swap if requested"
	extend_swap "$host"
done
