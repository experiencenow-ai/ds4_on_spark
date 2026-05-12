#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
ops_spark_ring_staged_env_audit.sh -- Mac-side audit of staged DS4 ring envs (safe)

Usage:
  ops_spark_ring_staged_env_audit.sh [--instance<N> <name>]... <spark0_user@host> <spark1_user@host> [spark2_user@host ...]

Environment:
  SSH_OPTS   Optional ssh options override.

Notes:
  - Non-destructive; intended to run from the Mac.
  - Audits the staged env file on each Spark:
      /tmp/ds4-config/ds4-<instance>.env.example
  - Validates ring-consistency: world size, unique ranks, consistent ring host list.
  - Intended to be run after `scripts/ops_stage_spark_ring.sh`.
EOF
}

if [ "$#" -lt 2 ]; then
	usage >&2
	exit 2
fi

while [ $# -gt 0 ]; do
	case "$1" in
		--instance[0-9]*)
			idx="${1#--instance}"
			case "$idx" in
				*[!0-9]*|"")
					echo "invalid instance option: $1" >&2
					exit 2
					;;
			esac
			eval "instance_$idx=\${2:-}"
			shift 2
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			break
			;;
	esac
done

if [ "$#" -lt 2 ]; then
	usage >&2
	exit 2
fi

if [ "${SSH_OPTS:-}" = "" ]; then
	SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
fi

node_count="$#"
i=0
while [ "$#" -gt 0 ]; do
	eval "target_$i=\$1"
	i=$((i + 1))
	shift
done

value_at()
{
	prefix="$1"
	idx="$2"
	eval "printf '%s' \"\${${prefix}_${idx}:-}\""
}

instance_for_index()
{
	idx="$1"
	value="$(value_at instance "$idx")"
	if [ "$value" != "" ]; then
		echo "$value"
		return 0
	fi
	echo "spark$idx"
}

ssh_run()
{
	target="$1"
	shift
	ssh $SSH_OPTS "$target" "$@"
}

need_nonempty()
{
	key="$1"
	val="$2"
	if [ "$val" = "" ]; then
		echo "missing: $key" >&2
		return 1
	fi
	return 0
}

need_uint()
{
	key="$1"
	val="$2"
	case "$val" in
		''|*[!0-9]*)
			echo "invalid uint: $key=$val" >&2
			return 1
			;;
	esac
	return 0
}

trim_ws()
{
	printf '%s' "$1" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

split_csv_words()
{
	printf '%s' "$1" | tr ',' ' ' | tr -s ' ' ' ' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

dedupe_list()
{
	printf '%s\n' $* | awk '!seen[$0]++'
}

ring_hosts_normalized=""
master_addr=""
master_port=""
ranks=""
err=0

echo "== staged DS4 ring env audit (Mac-side) =="
date -Is 2>/dev/null || date || true
echo "node_count=$node_count"
i=0
while [ "$i" -lt "$node_count" ]; do
	echo "spark$i: $(value_at target "$i") (instance=$(instance_for_index "$i"))"
	i=$((i + 1))
done
echo

i=0
while [ "$i" -lt "$node_count" ]; do
	target="$(value_at target "$i")"
	instance="$(instance_for_index "$i")"
	env_path="/tmp/ds4-config/ds4-${instance}.env.example"

	echo "== spark$i ($target) staged env =="
	kv="$(ssh_run "$target" sh -c '
set -eu
path="${1:-}"
if [ ! -f "$path" ]; then
	echo "missing:$path"
	exit 2
fi
for k in DS4_INSTANCE DS4_WORLD_SIZE DS4_RANK DS4_MASTER_ADDR DS4_MASTER_PORT DS4_RING_HOSTS; do
	v="$(grep -E "^[[:space:]]*${k}=" "$path" 2>/dev/null | head -n 1 | sed -e "s/^[[:space:]]*${k}=//")"
	printf "%s=%s\n" "$k" "$v"
done
' sh "$env_path" 2>/dev/null)" || kv=""
	if [ "$kv" = "" ]; then
		echo "failed to read $env_path" >&2
		err=1
		i=$((i + 1))
		echo
		continue
	fi
	case "$kv" in
		missing:*)
			echo "$kv" >&2
			err=1
			i=$((i + 1))
			echo
			continue
			;;
	esac

	ds4_instance="$(printf '%s\n' "$kv" | awk -F= '$1=="DS4_INSTANCE"{print $2}')"
	ds4_world="$(printf '%s\n' "$kv" | awk -F= '$1=="DS4_WORLD_SIZE"{print $2}')"
	ds4_rank="$(printf '%s\n' "$kv" | awk -F= '$1=="DS4_RANK"{print $2}')"
	ds4_master_addr="$(printf '%s\n' "$kv" | awk -F= '$1=="DS4_MASTER_ADDR"{print $2}')"
	ds4_master_port="$(printf '%s\n' "$kv" | awk -F= '$1=="DS4_MASTER_PORT"{print $2}')"
	ds4_ring_hosts="$(printf '%s\n' "$kv" | awk -F= '$1=="DS4_RING_HOSTS"{print $2}')"

	echo "env_path=$env_path"
	echo "DS4_INSTANCE=$ds4_instance"
	echo "DS4_WORLD_SIZE=$ds4_world"
	echo "DS4_RANK=$ds4_rank"
	echo "DS4_MASTER_ADDR=$ds4_master_addr"
	echo "DS4_MASTER_PORT=$ds4_master_port"
	echo "DS4_RING_HOSTS=$ds4_ring_hosts"
	echo

	if ! need_nonempty DS4_INSTANCE "$ds4_instance"; then err=1; fi
	if ! need_uint DS4_WORLD_SIZE "$ds4_world"; then err=1; fi
	if ! need_uint DS4_RANK "$ds4_rank"; then err=1; fi
	if ! need_nonempty DS4_MASTER_ADDR "$ds4_master_addr"; then err=1; fi
	if ! need_uint DS4_MASTER_PORT "$ds4_master_port"; then err=1; fi
	if ! need_nonempty DS4_RING_HOSTS "$ds4_ring_hosts"; then err=1; fi

	if [ "$ds4_instance" != "$instance" ] && [ "$ds4_instance" != "" ]; then
		echo "warning: DS4_INSTANCE mismatch for spark$i: staged=$ds4_instance expected=$instance" >&2
	fi
	if [ "$ds4_world" != "" ] && [ "$ds4_world" -ne "$node_count" ] 2>/dev/null; then
		echo "invalid: DS4_WORLD_SIZE=$ds4_world expected=$node_count" >&2
		err=1
	fi

	ranks="$ranks $ds4_rank"

	if [ "$master_addr" = "" ]; then
		master_addr="$ds4_master_addr"
	fi
	if [ "$master_port" = "" ]; then
		master_port="$ds4_master_port"
	fi
	if [ "$ds4_master_addr" != "" ] && [ "$master_addr" != "$ds4_master_addr" ]; then
		echo "invalid: DS4_MASTER_ADDR mismatch: expected=$master_addr got=$ds4_master_addr" >&2
		err=1
	fi
	if [ "$ds4_master_port" != "" ] && [ "$master_port" != "$ds4_master_port" ]; then
		echo "invalid: DS4_MASTER_PORT mismatch: expected=$master_port got=$ds4_master_port" >&2
		err=1
	fi

	norm_ring="$(trim_ws "$ds4_ring_hosts")"
	if [ "$ring_hosts_normalized" = "" ]; then
		ring_hosts_normalized="$norm_ring"
	fi
	if [ "$norm_ring" != "" ] && [ "$ring_hosts_normalized" != "$norm_ring" ]; then
		echo "invalid: DS4_RING_HOSTS mismatch: expected=$ring_hosts_normalized got=$norm_ring" >&2
		err=1
	fi

	i=$((i + 1))
done

uniq_ranks="$(dedupe_list $ranks)"
uniq_count="$(printf '%s\n' "$uniq_ranks" | awk 'END{print NR}')"
if [ "$uniq_count" -ne "$node_count" ]; then
	echo "invalid: expected $node_count unique ranks; got $uniq_count (ranks:$ranks)" >&2
	err=1
fi

if [ "$ring_hosts_normalized" != "" ]; then
	ring_words="$(split_csv_words "$ring_hosts_normalized")"
	ring_count="$(printf '%s\n' $ring_words | awk 'END{print NR}')"
	ring_uniq="$(dedupe_list $ring_words)"
	ring_uniq_count="$(printf '%s\n' "$ring_uniq" | awk 'END{print NR}')"
	if [ "$ring_count" -ne "$node_count" ]; then
		echo "invalid: DS4_RING_HOSTS count=$ring_count expected=$node_count (ring_hosts=$ring_hosts_normalized)" >&2
		err=1
	fi
	if [ "$ring_uniq_count" -ne "$ring_count" ]; then
		echo "invalid: DS4_RING_HOSTS contains duplicates (ring_hosts=$ring_hosts_normalized)" >&2
		err=1
	fi
	if [ "$master_addr" != "" ]; then
		if ! printf '%s\n' $ring_words | grep -Fx "$master_addr" >/dev/null 2>&1; then
			echo "invalid: DS4_MASTER_ADDR=$master_addr not present in DS4_RING_HOSTS=$ring_hosts_normalized" >&2
			err=1
		fi
	fi
fi

if [ "$err" -ne 0 ]; then
	echo "== FAIL ==" >&2
	exit 2
fi

echo "== OK =="
