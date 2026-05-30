#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
nodes=("$@")
ssh_opts="${DS4_SSH_OPTS:-}"
scp_opts="${DS4_SCP_OPTS:-$ssh_opts}"
sudo_password="${DS4_SUDO_PASSWORD:-}"
payload="ds4-route-admin.sudoers.in"

if [ "${#nodes[@]}" -eq 0 ]
then
	nodes=(spark0 spark1 spark2 spark3 spark4 spark5 spark6 spark7)
fi

remote_install()
{
	node="$1"
	remote='set -eu
run_sudo()
{
	if [ "${DS4_REMOTE_SUDO_STDIN:-0}" = "1" ]
	then
		sudo -S -p "" "$@"
	else
		sudo "$@"
	fi
}
user="$(id -un)"
ipbin="$(command -v ip)"
tmp="/tmp/ds4-route-admin.sudoers"
sed "s/@DS4_USER@/$user/g" "/tmp/ds4-route-admin.sudoers.in" > "$tmp"
run_sudo install -o root -g root -m 0440 "$tmp" "/etc/sudoers.d/ds4-route-admin"
run_sudo visudo -cf "/etc/sudoers.d/ds4-route-admin"
sudo -n "$ipbin" route get 10.10.100.10 >/dev/null
rm -f "$tmp" "/tmp/ds4-route-admin.sudoers.in"
echo "installed route-admin sudoers for $user on $(hostname)"'
	if [ "$sudo_password" = "" ]
	then
		ssh $ssh_opts -tt "$node" "$remote"
	else
		printf '%s\n' "$sudo_password" | ssh $ssh_opts "$node" "DS4_REMOTE_SUDO_STDIN=1; export DS4_REMOTE_SUDO_STDIN; $remote"
	fi
}

for node in "${nodes[@]}"
do
	echo "==> $node: copy route-admin sudoers payload"
	scp $scp_opts "$repo_dir/scripts/$payload" "$node:/tmp/$payload"
	echo "==> $node: install route-admin sudoers"
	remote_install "$node"
done
