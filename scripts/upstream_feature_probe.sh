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
	"${ROOT_DIR}/scripts/fetch_upstreams.sh" ds4
	"${ROOT_DIR}/scripts/fetch_upstreams.sh" deepgemm
	"${ROOT_DIR}/scripts/fetch_upstreams.sh" deepseek_v4_flash_hf
	"${ROOT_DIR}/scripts/fetch_upstreams.sh" deepseek_v4_flash_base_hf
	"${ROOT_DIR}/scripts/fetch_upstreams.sh" transformers
	"${ROOT_DIR}/scripts/fetch_upstreams.sh" vllm
fi

fail=0
skipped=0

ok()
{
	echo "OK   $*"
}

miss()
{
	echo "MISS $*" >&2
	fail=1
}

need_pat()
{
	local path="$1"
	local pat="$2"
	local label="$3"
	if [ ! -f "${path}" ]; then
		miss "${label} (${path})"
		return 1
	fi
	if rg -n "${pat}" "${path}" >/dev/null 2>&1; then
		ok "${label}"
		return 0
	fi
	miss "${label} (${path})"
	return 1
}

need_lfs_pointer()
{
	local path="$1"
	local label="$2"
	if [ ! -f "${path}" ]; then
		miss "${label} (${path})"
		return 1
	fi
	if head -n 1 "${path}" | rg -n "^version https://git-lfs.github.com/spec/v1$" >/dev/null 2>&1; then
		ok "${label}"
		return 0
	fi
	miss "${label} (expected git-lfs pointer stub; possible weight download?)"
	return 1
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

skip()
{
	echo "SKIP $*" >&2
	skipped=1
}

echo "== ds4 (DeepSeek-V4-Flash reference engine) =="
if [ -d "${UPSTREAM_DIR}/ds4" ]; then
	need_file "${UPSTREAM_DIR}/ds4/ds4.c" "ds4 ds4.c present" || true
	need_file "${UPSTREAM_DIR}/ds4/ds4.h" "ds4 ds4.h present" || true
	need_file "${UPSTREAM_DIR}/ds4/ds4_server.c" "ds4 ds4_server.c present" || true
	need_file "${UPSTREAM_DIR}/ds4/download_model.sh" "ds4 download_model.sh present (do not run from intake)" || true
else
	skip "ds4 checkout missing; run: ./scripts/upstream_feature_probe.sh --fetch"
fi

echo "== DeepSeek-V4-Flash (HF official configs) =="
if [ -d "${UPSTREAM_DIR}/deepseek_v4_flash_hf" ]; then
	need_file "${UPSTREAM_DIR}/deepseek_v4_flash_hf/config.json" "DeepSeek-V4-Flash config.json present" || true
	need_file "${UPSTREAM_DIR}/deepseek_v4_flash_hf/tokenizer.json" "DeepSeek-V4-Flash tokenizer.json present" || true
	need_file "${UPSTREAM_DIR}/deepseek_v4_flash_hf/LICENSE" "DeepSeek-V4-Flash LICENSE present" || true
	need_pat "${UPSTREAM_DIR}/deepseek_v4_flash_hf/config.json" "\"expert_dtype\"[[:space:]]*:[[:space:]]*\"fp4\"" "DeepSeek-V4-Flash config expert_dtype=fp4" || true
	need_lfs_pointer "${UPSTREAM_DIR}/deepseek_v4_flash_hf/model-00002-of-00046.safetensors" "DeepSeek-V4-Flash weights are LFS pointers (no download)" || true
else
	skip "DeepSeek-V4-Flash HF checkout missing; run: ./scripts/upstream_feature_probe.sh --fetch"
fi

echo "== DeepSeek-V4-Flash-Base (HF official configs) =="
if [ -d "${UPSTREAM_DIR}/deepseek_v4_flash_base_hf" ]; then
	need_file "${UPSTREAM_DIR}/deepseek_v4_flash_base_hf/config.json" "DeepSeek-V4-Flash-Base config.json present" || true
	need_file "${UPSTREAM_DIR}/deepseek_v4_flash_base_hf/tokenizer.json" "DeepSeek-V4-Flash-Base tokenizer.json present" || true
	need_file "${UPSTREAM_DIR}/deepseek_v4_flash_base_hf/LICENSE" "DeepSeek-V4-Flash-Base LICENSE present" || true
	need_pat "${UPSTREAM_DIR}/deepseek_v4_flash_base_hf/config.json" "\"expert_dtype\"[[:space:]]*:[[:space:]]*\"fp8\"" "DeepSeek-V4-Flash-Base config expert_dtype=fp8" || true
	need_lfs_pointer "${UPSTREAM_DIR}/deepseek_v4_flash_base_hf/model-00002-of-00046.safetensors" "DeepSeek-V4-Flash-Base weights are LFS pointers (no download)" || true
else
	skip "DeepSeek-V4-Flash-Base HF checkout missing; run: ./scripts/upstream_feature_probe.sh --fetch"
fi

echo "== transformers (DeepSeek-V4 support) =="
if [ -d "${UPSTREAM_DIR}/transformers" ]; then
	need_dir "${UPSTREAM_DIR}/transformers/src/transformers/models/deepseek_v4" "transformers deepseek_v4 model code" || true
	need_file "${UPSTREAM_DIR}/transformers/docs/source/en/model_doc/deepseek_v4.md" "transformers deepseek_v4 docs" || true
else
	skip "transformers checkout missing; run: ./scripts/upstream_feature_probe.sh --fetch"
fi

echo "== vLLM (DeepSeek-V4 support) =="
if [ -d "${UPSTREAM_DIR}/vllm" ]; then
	need_file "${UPSTREAM_DIR}/vllm/vllm/model_executor/models/deepseek_v4.py" "vllm deepseek_v4 model entrypoint" || true
	need_file "${UPSTREAM_DIR}/vllm/csrc/fused_deepseek_v4_qnorm_rope_kv_insert_kernel.cu" "vllm deepseek_v4 fused KV insert kernel" || true
else
	skip "vllm checkout missing; run: ./scripts/upstream_feature_probe.sh --fetch"
fi

if [ -f "${UPSTREAM_DIR}/vllm/vllm/model_executor/models/deepseek_v4.py" ]; then
	if rg -n "_DEEPSEEK_V4_EXPERT_DTYPES" "${UPSTREAM_DIR}/vllm/vllm/model_executor/models/deepseek_v4.py" >/dev/null 2>&1; then
		ok "vllm deepseek_v4 expert_dtype switch present"
	else
		miss "vllm deepseek_v4 expert_dtype switch missing (_DEEPSEEK_V4_EXPERT_DTYPES)"
	fi
fi

if [ "${fail}" -eq 0 ] && [ "${skipped}" -ne 0 ]; then
	echo "OK   feature probe skipped (missing upstream checkouts; run with --fetch to enforce)"
	exit 0
fi

if [ "${fail}" -ne 0 ]; then
	echo "FAIL (one or more expected features missing)" >&2
	exit 1
fi

echo "OK   all feature probes passed"
exit 0
