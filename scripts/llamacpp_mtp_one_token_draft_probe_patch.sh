#!/usr/bin/env sh
set -eu

target_note="llama.cpp Spark fork: one-token MTP draft probe (skeleton patch)"

LLAMA_DIR="${LLAMA_DIR:-$HOME/src/llama.cpp-deepseek-v4-flash-cuda-spark}"
LLAMA_REPO="${LLAMA_REPO:-https://github.com/kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark.git}"
LLAMA_COMMIT="${LLAMA_COMMIT:-94073e2}"
if [ "${PATCH_FILE:-}" = "" ]; then
	case "$LLAMA_COMMIT" in
		9222e55)
			PATCH_FILE="$PWD/docs/llamacpp-patches/kamnxt-llamacpp-deepseek-v4-flash-cuda-spark-9222e55-mtp-one-token-draft-probe-skeleton.patch"
			;;
		94073e2)
			PATCH_FILE="$PWD/docs/llamacpp-patches/kamnxt-llamacpp-deepseek-v4-flash-cuda-spark-94073e2-mtp-one-token-draft-probe-skeleton.patch"
			;;
		*)
			PATCH_FILE="$PWD/docs/llamacpp-patches/kamnxt-llamacpp-deepseek-v4-flash-cuda-spark-94073e2-mtp-one-token-draft-probe-skeleton.patch"
			;;
	esac
fi

TRUNK_GGUF="${TRUNK_GGUF:-}"
MTP_SIDECAR_GGUF="${MTP_SIDECAR_GGUF:-}"
PROMPT="${PROMPT:-Hello.}"
SEED="${SEED:-1234}"
LOAD_SIDECAR_WEIGHTS="${LOAD_SIDECAR_WEIGHTS:-0}"

JSON_ONLY="${JSON_ONLY:-0}"

CUDACXX="${CUDACXX:-}"

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

if [ "$JSON_ONLY" != "1" ]; then
	echo "== $target_note =="
	date -u +"utc=%Y-%m-%dT%H:%M:%SZ"
	echo "cwd=$PWD"
	echo "llama_dir=$LLAMA_DIR"
	echo "llama_repo=$LLAMA_REPO"
	echo "llama_commit=$LLAMA_COMMIT"
	echo "patch_file=$PATCH_FILE"
	echo
fi

if [ ! -d "$LLAMA_DIR" ]; then
	if [ "$JSON_ONLY" != "1" ]; then
		echo "missing LLAMA_DIR=$LLAMA_DIR"
	fi
	if [ "$ALLOW_FETCH" = "1" ]; then
		mkdir -p "$(dirname "$LLAMA_DIR")"
		git clone "$LLAMA_REPO" "$LLAMA_DIR"
	else
		json_err "missing LLAMA_DIR; set ALLOW_FETCH=1 to clone the llama.cpp fork"
		exit 2
	fi
fi

if [ ! -r "$PATCH_FILE" ]; then
	json_err "PATCH_FILE not readable: $PATCH_FILE"
	exit 3
fi

if [ "$JSON_ONLY" != "1" ]; then
	echo "== llama.cpp revision (pre) =="
	(cd "$LLAMA_DIR" && git rev-parse HEAD) || true
fi

need_git_prepare=0
if [ "$ALLOW_FETCH" = "1" ] || [ "$ALLOW_PATCH" = "1" ]; then
	need_git_prepare=1
fi

if [ "$need_git_prepare" = "1" ]; then
	if [ "$ALLOW_FETCH" = "1" ]; then
		(cd "$LLAMA_DIR" && git fetch --all --tags)
	fi
	if ! (cd "$LLAMA_DIR" && git checkout "$LLAMA_COMMIT"); then
		json_err "unable to checkout LLAMA_COMMIT=$LLAMA_COMMIT (set ALLOW_FETCH=1 to fetch, or ensure the commit exists locally)"
		exit 7
	fi
fi

if [ "$JSON_ONLY" != "1" ]; then
	echo
	echo "== patch =="
fi
if [ "$ALLOW_PATCH" != "1" ]; then
	if [ "$JSON_ONLY" != "1" ]; then
		echo "patch skipped (set ALLOW_PATCH=1 to apply): $PATCH_FILE"
	fi
else
	if (cd "$LLAMA_DIR" && git apply --reverse --check "$PATCH_FILE" >/dev/null 2>&1); then
		if [ "$JSON_ONLY" != "1" ]; then
			echo "patch already applied"
		fi
	else
		if ! (cd "$LLAMA_DIR" && git apply --check "$PATCH_FILE" >/dev/null 2>&1); then
			json_err "patch does not apply cleanly (clean tree or reset LLAMA_DIR; then set ALLOW_FETCH=1 ALLOW_PATCH=1)"
			exit 8
		fi
		(cd "$LLAMA_DIR" && git apply "$PATCH_FILE")
		if [ "$JSON_ONLY" != "1" ]; then
			echo "patch applied"
		fi
	fi
fi

if [ "$JSON_ONLY" != "1" ]; then
	echo
	echo "== build =="
fi
if [ "$ALLOW_BUILD" != "1" ]; then
	if [ "$JSON_ONLY" != "1" ]; then
		echo "build skipped (set ALLOW_BUILD=1 to compile llama-ds4-mtp-one-token-draft-probe)"
	fi
else
	if [ "$CUDACXX" = "" ]; then
		if command -v nvcc >/dev/null 2>&1; then
			CUDACXX="$(command -v nvcc)"
		else
			for p in /usr/local/cuda/bin/nvcc /opt/cuda/bin/nvcc /usr/local/cuda-*/bin/nvcc /usr/local/cuda*/bin/nvcc; do
				if [ -x "$p" ]; then
					CUDACXX="$p"
					break
				fi
			done
		fi
	fi
	if [ "$JSON_ONLY" != "1" ]; then
		if [ "$CUDACXX" != "" ]; then
			echo "cudacxx=$CUDACXX"
		else
			echo "cudacxx=not-found (set CUDACXX=/abs/path/to/nvcc if CMake cannot discover CUDA)"
		fi
	fi
	cmake_cuda_compiler_arg=""
	if [ "$CUDACXX" != "" ]; then
		cmake_cuda_compiler_arg="-DCMAKE_CUDA_COMPILER=$CUDACXX"
	fi
	(cd "$LLAMA_DIR" && cmake -B build -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release $cmake_cuda_compiler_arg)
	(cd "$LLAMA_DIR" && cmake --build build --config Release --target llama-ds4-mtp-one-token-draft-probe -j)
fi

if [ "$JSON_ONLY" != "1" ]; then
	echo
	echo "== run =="
fi
if [ "$ALLOW_RUN" != "1" ]; then
	if [ "$JSON_ONLY" != "1" ]; then
		echo "run skipped (set ALLOW_RUN=1 TRUNK_GGUF=/abs/path/to/trunk.gguf MTP_SIDECAR_GGUF=/abs/path/to/sidecar.gguf)"
	fi
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
			echo "defaulted TRUNK_GGUF=$p" 1>&2
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
			echo "defaulted MTP_SIDECAR_GGUF=$p" 1>&2
			break
		fi
	done
	if [ "$MTP_SIDECAR_GGUF" = "" ]; then
		json_err "MTP_SIDECAR_GGUF is required for ALLOW_RUN=1"
		exit 5
	fi
fi

PROBE_BIN="$LLAMA_DIR/build/bin/llama-ds4-mtp-one-token-draft-probe"
if [ ! -x "$PROBE_BIN" ]; then
	if [ "$JSON_ONLY" != "1" ]; then
		echo "probe binary not found: $PROBE_BIN"
		echo "set ALLOW_BUILD=1 to build it"
	fi
	if [ "$JSON_ONLY" = "1" ]; then
		json_err "probe binary not found (set ALLOW_BUILD=1 to build it)"
	fi
	exit 6
fi

PROBE_ARGS="--json --model \"$TRUNK_GGUF\" --sidecar \"$MTP_SIDECAR_GGUF\" --prompt \"$PROMPT\" --seed $SEED"
if [ "$LOAD_SIDECAR_WEIGHTS" = "1" ]; then
	PROBE_ARGS="$PROBE_ARGS --load-sidecar-weights"
fi
sh -lc "\"$PROBE_BIN\" $PROBE_ARGS"
