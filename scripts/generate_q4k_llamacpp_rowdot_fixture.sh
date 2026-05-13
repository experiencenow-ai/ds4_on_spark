#!/usr/bin/env sh
set -eu

note="generate llama.cpp Q4_K rowdot fixture"

ALLOW_FETCH="${ALLOW_FETCH:-0}"
ALLOW_BUILD="${ALLOW_BUILD:-0}"

REF="b9110"
VECTORS="16"
OUT=""

usage()
{
	echo "usage: $0 --out <path> [--ref <tag-or-ref>] [--vectors <n>]" 1>&2
	echo "env: ALLOW_FETCH=1 ALLOW_BUILD=1" 1>&2
}

while [ "$#" -gt 0 ]; do
	case "$1" in
		--out) OUT="${2:-}"; shift 2 ;;
		--ref) REF="${2:-}"; shift 2 ;;
		--vectors) VECTORS="${2:-}"; shift 2 ;;
		-h|--help) usage; exit 0 ;;
		*) echo "unknown arg: $1" 1>&2; usage; exit 2 ;;
	esac
done

if [ "$OUT" = "" ]; then
	echo "missing --out" 1>&2
	usage
	exit 2
fi

echo "== $note =="
date -u +"utc=%Y-%m-%dT%H:%M:%SZ"
echo "cwd=$PWD"
echo "ref=$REF"
echo "vectors=$VECTORS"
echo "out=$OUT"
echo "allow_fetch=$ALLOW_FETCH"
echo "allow_build=$ALLOW_BUILD"
echo

tmp="$(mktemp -d /private/tmp/q4k-llamacpp-fixture-XXXX)"
trap 'rm -rf "$tmp"' EXIT INT TERM

repo_dir="$tmp/llama.cpp"
build_dir="$repo_dir/build"
tool_src="$PWD/scripts/q4k_llamacpp_rowdot_fixture_gen.c"
tool_bin="$tmp/q4k_llamacpp_rowdot_fixture_gen"
tmp_out="$tmp/fixture.json"

if [ ! -r "$tool_src" ]; then
	echo "missing tool source: $tool_src" 1>&2
	exit 3
fi

if [ "$ALLOW_FETCH" != "1" ]; then
	echo "fetch disabled (set ALLOW_FETCH=1 to clone ggml-org/llama.cpp)" 1>&2
	exit 4
fi

git clone --depth 1 --branch "$REF" https://github.com/ggml-org/llama.cpp.git "$repo_dir" 1>/dev/null
up_commit="$(cd "$repo_dir" && git rev-parse HEAD)"
up_ref="refs/tags/$REF"
if (cd "$repo_dir" && git show-ref -q --tags "refs/tags/$REF"); then
	up_ref="refs/tags/$REF"
else
	up_ref="$REF"
fi

if [ "$ALLOW_BUILD" != "1" ]; then
	echo "build disabled (set ALLOW_BUILD=1 to run CMake + compile the fixture tool)" 1>&2
	exit 5
fi

cmake -S "$repo_dir" -B "$build_dir" \
	-DGGML_BUILD_TESTS=OFF \
	-DGGML_BUILD_EXAMPLES=OFF \
	-DLLAMA_BUILD_TESTS=OFF \
	-DLLAMA_BUILD_EXAMPLES=OFF \
	-DCMAKE_BUILD_TYPE=Release \
	1>/dev/null

if ! cmake --build "$build_dir" --config Release --target ggml -j 1>/dev/null 2>&1; then
	cmake --build "$build_dir" --config Release -j 1>/dev/null
fi

libs="$(find "$build_dir" -type f -name 'libggml*.a' | sort | tr '\n' ' ')"
if [ "$libs" = "" ]; then
	echo "unable to find libggml*.a under $build_dir" 1>&2
	exit 6
fi

cc -O2 -std=c11 \
	-I "$repo_dir/ggml/include" \
	-I "$repo_dir/ggml/src" \
	-o "$tool_bin" \
	"$tool_src" \
	$libs \
	-lm -pthread

"$tool_bin" --out "$tmp_out" --vectors "$VECTORS" --up-ref "$up_ref" --up-commit "$up_commit"

mkdir -p "$(dirname "$OUT")"
cp "$tmp_out" "$OUT"

echo "ok=true"
echo "up_commit=$up_commit"

