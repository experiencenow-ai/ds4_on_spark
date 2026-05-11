#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
ops_ds4_config_check.sh -- validate DS4 key=value config files (safe)

Usage:
  ops_ds4_config_check.sh [--strict-unknown] [-/path/optional.conf] <path.conf> [more.conf ...]

Notes:
  - Non-destructive; does not require sudo.
  - Supports blank lines and '#' comments (including inline comments after whitespace).
  - Validates keys/values against the current ds4 config contract:
      include/ds4/config.h
      src/ds4_config.c
  - By default, unknown keys are WARNed but not fatal.
  - With --strict-unknown, unknown keys fail non-zero.
EOF
}

strict_unknown=0

while [ $# -gt 0 ]; do
	case "$1" in
		--strict-unknown)
			strict_unknown=1
			shift
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

if [ "$#" -lt 1 ]; then
	usage >&2
	exit 2
fi

warn()
{
	echo "warning: $*" >&2
}

is_uint()
{
	case "${1:-}" in
		''|*[!0-9]*)
			return 1
			;;
	esac
	return 0
}

is_i32()
{
	s="${1:-}"
	if [ "$s" = "" ]; then
		return 1
	fi
	case "$s" in
		-*)
			s="${s#-}"
			;;
	esac
	is_uint "$s"
}

parse_bool()
{
	v="$(printf '%s' "${1:-}" | tr 'A-Z' 'a-z')"
	case "$v" in
		0|false|no|off)
			echo 0
			return 0
			;;
		1|true|yes|on)
			echo 1
			return 0
			;;
	esac
	return 1
}

parse_log_level()
{
	v="$(printf '%s' "${1:-}" | tr 'A-Z' 'a-z')"
	case "$v" in
		error)
			echo 0
			return 0
			;;
		warn|warning)
			echo 1
			return 0
			;;
		info)
			echo 2
			return 0
			;;
		debug)
			echo 3
			return 0
			;;
	esac
	if is_uint "$v"; then
		if [ "$v" -ge 0 ] && [ "$v" -le 3 ]; then
			echo "$v"
			return 0
		fi
	fi
	return 1
}

parse_i32_kmg_nonneg()
{
	raw="${1:-}"
	if [ "$raw" = "" ]; then
		return 1
	fi
	base="$raw"
	suf=""
	case "$raw" in
		*[KkMmGg])
			suf="${raw#${raw%?}}"
			base="${raw%?}"
			;;
	esac
	if ! is_i32 "$base"; then
		return 1
	fi
	if [ "$base" -lt 0 ]; then
		return 1
	fi
	case "$suf" in
		'')
			echo "$base"
			return 0
			;;
		K|k)
			echo $((base * 1024))
			return 0
			;;
		M|m)
			echo $((base * 1024 * 1024))
			return 0
			;;
		G|g)
			echo $((base * 1024 * 1024 * 1024))
			return 0
			;;
	esac
	return 1
}

check_one()
{
	path="$1"
	label="$2"

	if [ ! -f "$path" ]; then
		echo "missing config file: $path" >&2
		return 2
	fi
	if [ ! -r "$path" ]; then
		echo "unreadable config file (check owner/group/mode): $path" >&2
		return 2
	fi

	enable_cuda=""
	cuda_arena_size=""

	lineno=0
	while IFS= read -r line || [ "$line" != "" ]; do
		lineno=$((lineno + 1))
		line="$(printf '%s' "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
		case "$line" in
			''|\#*)
				continue
				;;
		esac
		line="$(printf '%s' "$line" | sed -e 's/[[:space:]]#.*$//')"
		line="$(printf '%s' "$line" | sed -e 's/[[:space:]]*$//')"
		case "$line" in
			'')
				continue
				;;
		esac
		case "$line" in
			*=*)
				key="${line%%=*}"
				val="${line#*=}"
				key="$(printf '%s' "$key" | sed -e 's/[[:space:]]*$//')"
				val="$(printf '%s' "$val" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
				;;
			*)
				echo "$label:$lineno: expected key=value (or comment): $line" >&2
				return 2
				;;
		esac

		case "$key" in
			log_level)
				if ! parse_log_level "$val" >/dev/null 2>&1; then
					echo "$label:$lineno: invalid log_level: $val" >&2
					return 2
				fi
				;;
			enable_cuda)
				if ! parsed="$(parse_bool "$val" 2>/dev/null)"; then
					echo "$label:$lineno: invalid enable_cuda (expected 0/1 or true/false): $val" >&2
					return 2
				fi
				enable_cuda="$parsed"
				;;
			cuda_device)
				if ! is_i32 "$val"; then
					echo "$label:$lineno: invalid cuda_device (expected -1 or >=0 int): $val" >&2
					return 2
				fi
				if [ "$val" -lt -1 ]; then
					echo "$label:$lineno: invalid cuda_device (min -1): $val" >&2
					return 2
				fi
				;;
			arena_size)
				if ! parse_i32_kmg_nonneg "$val" >/dev/null 2>&1; then
					echo "$label:$lineno: invalid arena_size (expected non-neg int or K/M/G suffix): $val" >&2
					return 2
				fi
				;;
			cuda_arena_size)
				if ! parsed="$(parse_i32_kmg_nonneg "$val" 2>/dev/null)"; then
					echo "$label:$lineno: invalid cuda_arena_size (expected non-neg int or K/M/G suffix): $val" >&2
					return 2
				fi
				cuda_arena_size="$parsed"
				;;
			log_ring_entries)
				if ! parse_i32_kmg_nonneg "$val" >/dev/null 2>&1; then
					echo "$label:$lineno: invalid log_ring_entries (expected non-neg int or K/M/G suffix): $val" >&2
					return 2
				fi
				;;
			*)
				if [ "$strict_unknown" -ne 0 ]; then
					echo "$label:$lineno: unknown key: $key" >&2
					return 2
				fi
				warn "$label:$lineno: unknown key ignored by ds4: $key"
				;;
		esac
	done < "$path"

	if [ "$cuda_arena_size" != "" ] && [ "$cuda_arena_size" -gt 0 ]; then
		if [ "${enable_cuda:-0}" != "1" ]; then
			echo "$label: cuda_arena_size>0 requires enable_cuda=1 (enable_cuda=${enable_cuda:-0})" >&2
			return 2
		fi
	fi

	return 0
}

for raw in "$@"; do
	optional=0
	path="$raw"
	case "$raw" in
		-/*)
			optional=1
			path="${raw#-}"
			;;
	esac
	if [ ! -f "$path" ]; then
		if [ "$optional" -ne 0 ]; then
			continue
		fi
		echo "missing config file: $path" >&2
		exit 2
	fi
	check_one "$path" "$path" || exit $?
done

exit 0
