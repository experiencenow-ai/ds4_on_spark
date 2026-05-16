#!/usr/bin/env sh
set -eu

target_note="antirez/ds4: MTP multi-token acceptance probe"

DS4_DIR="${DS4_DIR:-$HOME/src/ds4}"
DS4_REPO="${DS4_REPO:-https://github.com/antirez/ds4.git}"
DS4_COMMIT="${DS4_COMMIT:-3630e64}"

PATCH_Q4K_FILE="${PATCH_Q4K_FILE:-/tmp/ds4_cuda_mtp_q4k_and_sidecar_map.patch}"
PATCH_CACHE_FILE="${PATCH_CACHE_FILE:-/tmp/ds4_cuda_multi_model_cache.patch}"
PATCH_VERIFY_FILE="${PATCH_VERIFY_FILE:-/tmp/ds4_mtp_decode2_default_verifier.patch}"
APPLY_CACHE_PATCH="${APPLY_CACHE_PATCH:-1}"
APPLY_VERIFY_PATCH="${APPLY_VERIFY_PATCH:-1}"

TRUNK_GGUF="${TRUNK_GGUF:-}"
MTP_SIDECAR_GGUF="${MTP_SIDECAR_GGUF:-}"
PROMPT="${PROMPT:-Explain Redis streams in one paragraph. Keep it concise, covering key features: append-only log, consumer groups, blocking reads, message persistence, and}"
SEED="${SEED:-1234}"
CTX="${CTX:-2048}"
N_PREDICT="${N_PREDICT:-32}"
MTP_DRAFT="${MTP_DRAFT:-2}"
MTP_MARGIN="${MTP_MARGIN:-0}"
RUN_LABEL="${RUN_LABEL:-mtp_draft${MTP_DRAFT}}"

ALLOW_FETCH="${ALLOW_FETCH:-0}"
ALLOW_CLEAN="${ALLOW_CLEAN:-0}"
ALLOW_PATCH="${ALLOW_PATCH:-0}"
ALLOW_BUILD="${ALLOW_BUILD:-0}"
ALLOW_RUN="${ALLOW_RUN:-0}"

note()
{
	echo "$@" 1>&2
}

note "== $target_note =="
note "$(date -u +"utc=%Y-%m-%dT%H:%M:%SZ")"
note "cwd=$PWD"
note "ds4_dir=$DS4_DIR"
note "ds4_repo=$DS4_REPO"
note "ds4_commit=$DS4_COMMIT"
note

if [ ! -d "$DS4_DIR" ]; then
	note "missing DS4_DIR=$DS4_DIR"
	if [ "$ALLOW_FETCH" = "1" ]; then
		mkdir -p "$(dirname "$DS4_DIR")"
		git clone "$DS4_REPO" "$DS4_DIR"
	else
		echo "missing DS4_DIR; set ALLOW_FETCH=1 to clone antirez/ds4" 1>&2
		exit 2
	fi
fi

need_git_prepare=0
if [ "$ALLOW_FETCH" = "1" ] || [ "$ALLOW_CLEAN" = "1" ] || [ "$ALLOW_PATCH" = "1" ]; then
	need_git_prepare=1
fi

if [ "$need_git_prepare" = "1" ]; then
	if [ "$ALLOW_FETCH" = "1" ]; then
		(cd "$DS4_DIR" && git fetch --all --tags)
	fi
	if [ "$ALLOW_CLEAN" = "1" ]; then
		(cd "$DS4_DIR" && git reset --hard && git clean -fd)
	fi
	if ! (cd "$DS4_DIR" && git checkout "$DS4_COMMIT"); then
		echo "unable to checkout DS4_COMMIT=$DS4_COMMIT (set ALLOW_FETCH=1 to fetch, or ensure the commit exists locally)" 1>&2
		exit 7
	fi
fi

apply_patch_file()
{
	patch_path="$1"
	patch_label="$2"
	if [ "$ALLOW_PATCH" != "1" ]; then
		note "patch skipped (set ALLOW_PATCH=1 to apply): $patch_label"
		return 0
	fi
	if [ ! -r "$patch_path" ]; then
		echo "patch not readable: $patch_label ($patch_path)" 1>&2
		exit 3
	fi
	if (cd "$DS4_DIR" && git apply --reverse --check "$patch_path" >/dev/null 2>&1); then
		note "patch already applied: $patch_label"
		return 0
	fi
	if ! (cd "$DS4_DIR" && git apply --check "$patch_path" >/dev/null 2>&1); then
		echo "patch does not apply cleanly: $patch_label (set ALLOW_CLEAN=1 to reset/clean DS4_DIR, then re-run)" 1>&2
		exit 8
	fi
	(cd "$DS4_DIR" && git apply "$patch_path")
	note "patch applied: $patch_label"
}

apply_patch_file "$PATCH_Q4K_FILE" "cuda-mtp-q4k-and-sidecar-map"
if [ "$APPLY_CACHE_PATCH" = "1" ]; then
	apply_patch_file "$PATCH_CACHE_FILE" "cuda-multi-model-cache"
else
	note "patch skipped (APPLY_CACHE_PATCH=0): cuda-multi-model-cache"
fi
if [ "$APPLY_VERIFY_PATCH" = "1" ]; then
	apply_patch_file "$PATCH_VERIFY_FILE" "mtp-decode2-default-verifier"
else
	note "patch skipped (APPLY_VERIFY_PATCH=0): mtp-decode2-default-verifier"
fi

if [ "$ALLOW_BUILD" != "1" ]; then
	note "build skipped (set ALLOW_BUILD=1 to compile ds4)"
else
	(cd "$DS4_DIR" && make -j)
fi

if [ "$ALLOW_RUN" != "1" ]; then
	note "run skipped (set ALLOW_RUN=1 TRUNK_GGUF=/abs/path/to/trunk.gguf MTP_SIDECAR_GGUF=/abs/path/to/sidecar.gguf)"
	exit 0
fi

if [ "$TRUNK_GGUF" = "" ]; then
	for p in \
		/home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf \
		/home/spark1/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf \
		/home/spark/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf \
		/mnt/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf \
		/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf
	do
		if [ -r "$p" ]; then
			TRUNK_GGUF="$p"
			export TRUNK_GGUF
			note "defaulted TRUNK_GGUF=$p"
			break
		fi
	done
	if [ "$TRUNK_GGUF" = "" ]; then
		echo "TRUNK_GGUF is required for ALLOW_RUN=1" 1>&2
		exit 4
	fi
fi

if [ "$MTP_SIDECAR_GGUF" = "" ]; then
	for p in \
		/home/spark0/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf \
		/home/spark1/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf \
		/home/spark/models/ds4/DeepSeek-V4-Flash-MTP-Q4K_Q8_0-F32.gguf \
		/home/spark/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf \
		/mnt/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf \
		/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf
	do
		if [ -r "$p" ]; then
			MTP_SIDECAR_GGUF="$p"
			export MTP_SIDECAR_GGUF
			note "defaulted MTP_SIDECAR_GGUF=$p"
			break
		fi
	done
	if [ "$MTP_SIDECAR_GGUF" = "" ]; then
		echo "MTP_SIDECAR_GGUF is required for ALLOW_RUN=1" 1>&2
		exit 5
	fi
fi

DS4_BIN="$DS4_DIR/ds4"
if [ ! -x "$DS4_BIN" ]; then
	echo "ds4 binary not found (set ALLOW_BUILD=1 to build it): $DS4_BIN" 1>&2
	exit 6
fi
export DS4_BIN TRUNK_GGUF MTP_SIDECAR_GGUF PROMPT SEED CTX N_PREDICT MTP_DRAFT MTP_MARGIN RUN_LABEL

cd "$DS4_DIR"

DS4_MTP_CONF_LOG="${DS4_MTP_CONF_LOG:-1}"
DS4_MTP_TIMING="${DS4_MTP_TIMING:-1}"
DS4_MTP_MIN_MARGIN="${DS4_MTP_MIN_MARGIN:-0}"
export DS4_MTP_CONF_LOG DS4_MTP_TIMING DS4_MTP_MIN_MARGIN

# Spark CUDA stability knobs (best-effort defaults).
# These can be overridden by setting the env vars explicitly on Spark.
if [ "${DS4_CUDA_WEIGHT_CACHE_SYNC:-}" = "" ]; then
	DS4_CUDA_WEIGHT_CACHE_SYNC="1"
	note "defaulted DS4_CUDA_WEIGHT_CACHE_SYNC=$DS4_CUDA_WEIGHT_CACHE_SYNC"
fi
if [ "${DS4_CUDA_WEIGHT_ARENA_CHUNK_MB:-}" = "" ]; then
	DS4_CUDA_WEIGHT_ARENA_CHUNK_MB="256"
	note "defaulted DS4_CUDA_WEIGHT_ARENA_CHUNK_MB=$DS4_CUDA_WEIGHT_ARENA_CHUNK_MB"
fi
if [ "${DS4_CUDA_MODEL_COPY_CHUNK_MB:-}" = "" ]; then
	DS4_CUDA_MODEL_COPY_CHUNK_MB="16"
	note "defaulted DS4_CUDA_MODEL_COPY_CHUNK_MB=$DS4_CUDA_MODEL_COPY_CHUNK_MB"
fi
export DS4_CUDA_WEIGHT_CACHE_SYNC DS4_CUDA_WEIGHT_ARENA_CHUNK_MB DS4_CUDA_MODEL_COPY_CHUNK_MB

python3 - <<'PY'
import hashlib
import os
import subprocess
import sys
import time

cmd = [
	os.environ["DS4_BIN"],
	"--cuda",
	"-m",
	os.environ["TRUNK_GGUF"],
	"--mtp",
	os.environ["MTP_SIDECAR_GGUF"],
	"--mtp-draft",
	os.environ["MTP_DRAFT"],
	"--mtp-margin",
	os.environ["MTP_MARGIN"],
	"--temp",
	"0",
	"-p",
	os.environ["PROMPT"],
	"-c",
	os.environ["CTX"],
	"-n",
	os.environ["N_PREDICT"],
	"--seed",
	os.environ["SEED"],
]
prompt_hash = hashlib.sha256(os.environ["PROMPT"].encode("utf-8")).hexdigest()
cmd_hash = hashlib.sha256("\0".join(cmd).encode("utf-8")).hexdigest()
spec_disabled = 1 if os.environ.get("DS4_MTP_SPEC_DISABLE", "") != "" else 0
phase = os.environ.get("RUN_LABEL", "mtp")
print(
	"ds4: mtp bench phase=%s command_sha256=%s prompt_sha256=%s n_predict=%s mtp_draft=%s ctx=%s seed=%s spec_disabled=%d"
	% (
		phase,
		cmd_hash,
		prompt_hash,
		os.environ["N_PREDICT"],
		os.environ["MTP_DRAFT"],
		os.environ["CTX"],
		os.environ["SEED"],
		spec_disabled,
	),
	file=sys.stderr,
	flush=True,
)
t0 = time.monotonic()
rc = subprocess.call(cmd)
wall = time.monotonic() - t0
print(
	"ds4: mtp bench phase=%s external_wall_s=%.6f exit_code=%d n_predict=%s mtp_draft=%s ctx=%s seed=%s spec_disabled=%d"
	% (
		phase,
		wall,
		rc,
		os.environ["N_PREDICT"],
		os.environ["MTP_DRAFT"],
		os.environ["CTX"],
		os.environ["SEED"],
		spec_disabled,
	),
	file=sys.stderr,
	flush=True,
)
raise SystemExit(rc)
PY
