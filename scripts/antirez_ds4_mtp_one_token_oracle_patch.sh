#!/usr/bin/env sh
set -eu

target_note="antirez/ds4: one-token MTP draft probe (oracle JSON)"

DS4_DIR="${DS4_DIR:-$HOME/src/ds4}"
DS4_REPO="${DS4_REPO:-https://github.com/antirez/ds4.git}"
DS4_COMMIT="${DS4_COMMIT:-3630e64}"

PATCH_Q4K_FILE="${PATCH_Q4K_FILE:-/tmp/ds4_cuda_mtp_q4k_and_sidecar_map.patch}"
PATCH_CACHE_FILE="${PATCH_CACHE_FILE:-/tmp/ds4_cuda_multi_model_cache.patch}"
PATCH_PROBE_FILE="${PATCH_PROBE_FILE:-/tmp/ds4_mtp_one_token_json_probe.patch}"

TRUNK_GGUF="${TRUNK_GGUF:-}"
MTP_SIDECAR_GGUF="${MTP_SIDECAR_GGUF:-}"
PROMPT="${PROMPT:-Hello.}"
SEED="${SEED:-1234}"
CTX="${CTX:-32768}"
DS4_EXTRA_ARGS="${DS4_EXTRA_ARGS:-}"

JSON_ONLY="${JSON_ONLY:-0}"

ALLOW_FETCH="${ALLOW_FETCH:-0}"
ALLOW_PATCH="${ALLOW_PATCH:-0}"
ALLOW_BUILD="${ALLOW_BUILD:-0}"
ALLOW_RUN="${ALLOW_RUN:-0}"

json_err()
{
	msg="$1"
	if [ "$JSON_ONLY" = "1" ]; then
		printf '{\n  "ok": false,\n  "errors": [%s]\n}\n' "\"$msg\""
	else
		echo "$msg" 1>&2
	fi
}

note()
{
	if [ "$JSON_ONLY" != "1" ]; then
		echo "$@" 1>&2
	fi
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
		json_err "missing DS4_DIR; set ALLOW_FETCH=1 to clone antirez/ds4"
		exit 2
	fi
fi

need_git_prepare=0
if [ "$ALLOW_FETCH" = "1" ] || [ "$ALLOW_PATCH" = "1" ]; then
	need_git_prepare=1
fi

if [ "$need_git_prepare" = "1" ]; then
	if [ "$ALLOW_FETCH" = "1" ]; then
		(cd "$DS4_DIR" && git fetch --all --tags)
	fi
	if ! (cd "$DS4_DIR" && git checkout "$DS4_COMMIT"); then
		json_err "unable to checkout DS4_COMMIT=$DS4_COMMIT (set ALLOW_FETCH=1 to fetch, or ensure the commit exists locally)"
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
		json_err "patch not readable: $patch_label ($patch_path)"
		exit 3
	fi
	if (cd "$DS4_DIR" && git apply --reverse --check "$patch_path" >/dev/null 2>&1); then
		note "patch already applied: $patch_label"
		return 0
	fi
	if ! (cd "$DS4_DIR" && git apply --check "$patch_path" >/dev/null 2>&1); then
		json_err "patch does not apply cleanly: $patch_label (reset DS4_DIR and re-run with ALLOW_FETCH=1 ALLOW_PATCH=1)"
		exit 8
	fi
	(cd "$DS4_DIR" && git apply "$patch_path")
	note "patch applied: $patch_label"
}

apply_patch_file "$PATCH_Q4K_FILE" "cuda-mtp-q4k-and-sidecar-map"
apply_patch_file "$PATCH_CACHE_FILE" "cuda-multi-model-cache"
apply_patch_file "$PATCH_PROBE_FILE" "mtp-one-token-json-probe"

if [ "$ALLOW_BUILD" != "1" ]; then
	note "build skipped (set ALLOW_BUILD=1 to compile ds4)"
else
	if [ "$JSON_ONLY" = "1" ]; then
		(cd "$DS4_DIR" && make -j) 1>&2
	else
		(cd "$DS4_DIR" && make -j)
	fi
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
		json_err "TRUNK_GGUF is required for ALLOW_RUN=1"
		exit 4
	fi
fi

if [ "$MTP_SIDECAR_GGUF" = "" ]; then
	for p in \
		/home/spark0/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf \
		/home/spark1/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf \
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
		json_err "MTP_SIDECAR_GGUF is required for ALLOW_RUN=1"
		exit 5
	fi
fi

DS4_BIN="$DS4_DIR/ds4"
if [ ! -x "$DS4_BIN" ]; then
	json_err "ds4 binary not found (set ALLOW_BUILD=1 to build it): $DS4_BIN"
	exit 6
fi

cd "$DS4_DIR"
DS4_MTP_PROBE="${DS4_MTP_PROBE:-1}"
DS4_MTP_FULL_LOGITS="${DS4_MTP_FULL_LOGITS:-1}"
export DS4_MTP_PROBE DS4_MTP_FULL_LOGITS
exec sh -lc "\"$DS4_BIN\" --cuda -m \"$TRUNK_GGUF\" --mtp \"$MTP_SIDECAR_GGUF\" -p \"$PROMPT\" -c \"$CTX\" --seed \"$SEED\" $DS4_EXTRA_ARGS --dump-mtp-one-token-json"
