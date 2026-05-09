#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM_DIR="${ROOT_DIR}/upstreams"

usage()
{
	cat <<'EOF'
Usage: ./scripts/upstream_feature_probe.sh [--fetch]

Sanity-checks that locally fetched upstreams contain expected DeepSeek-V4
support codepaths (does not validate pins; use ./scripts/upstream_verify_pins.sh).

By default this script only inspects existing ./upstreams/* checkouts.
If --fetch is provided, it fetches the required upstreams first.
EOF
}

want_fetch=0
if [ "${#}" -gt 1 ]; then
	usage
	exit 2
fi

if [ "${#}" -eq 1 ]; then
	case "$1" in
		--fetch)
			want_fetch=1
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			usage
			exit 2
			;;
	esac
fi

if [ "${want_fetch}" -eq 1 ]; then
	"${ROOT_DIR}/scripts/fetch_upstreams.sh" transformers
	"${ROOT_DIR}/scripts/fetch_upstreams.sh" vllm
fi

fail=0

ok()
{
	echo "OK   $*"
}

miss()
{
	echo "MISS $*" >&2
	fail=1
}

need_file()
{
	local path="$1"
	local label="$2"
	if [ -f "${path}" ]; then
		ok "${label}"
		return 0
	fi
	miss "${label} (${path})"
	return 1
}

need_dir()
{
	local path="$1"
	local label="$2"
	if [ -d "${path}" ]; then
		ok "${label}"
		return 0
	fi
	miss "${label} (${path})"
	return 1
}

echo "== transformers (DeepSeek-V4 support) =="
need_dir "${UPSTREAM_DIR}/transformers" "transformers checkout present" || true
need_dir "${UPSTREAM_DIR}/transformers/src/transformers/models/deepseek_v4" "transformers deepseek_v4 model code" || true
need_file "${UPSTREAM_DIR}/transformers/docs/source/en/model_doc/deepseek_v4.md" "transformers deepseek_v4 docs" || true

echo "== vLLM (DeepSeek-V4 support) =="
need_dir "${UPSTREAM_DIR}/vllm" "vllm checkout present" || true
need_file "${UPSTREAM_DIR}/vllm/vllm/model_executor/models/deepseek_v4.py" "vllm deepseek_v4 model entrypoint" || true
need_file "${UPSTREAM_DIR}/vllm/csrc/fused_deepseek_v4_qnorm_rope_kv_insert_kernel.cu" "vllm deepseek_v4 fused KV insert kernel" || true

if [ -f "${UPSTREAM_DIR}/vllm/vllm/model_executor/models/deepseek_v4.py" ]; then
	if rg -n "_DEEPSEEK_V4_EXPERT_DTYPES" "${UPSTREAM_DIR}/vllm/vllm/model_executor/models/deepseek_v4.py" >/dev/null 2>&1; then
		ok "vllm deepseek_v4 expert_dtype switch present"
	else
		miss "vllm deepseek_v4 expert_dtype switch missing (_DEEPSEEK_V4_EXPERT_DTYPES)"
	fi
fi

if [ "${fail}" -ne 0 ]; then
	echo "FAIL (one or more expected features missing)" >&2
	exit 1
fi

echo "OK   all feature probes passed"
exit 0

