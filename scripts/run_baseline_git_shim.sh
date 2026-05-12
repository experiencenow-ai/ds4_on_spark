#!/usr/bin/env sh
set -eu

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
shim_dir="${GIT_SHIM_DIR:-$repo_root/.codex_git}"

if [ -d "$shim_dir" ] && [ -r "$shim_dir/HEAD" ] && [ -r "$shim_dir/index" ]; then
	echo "ok: git shim already present: $shim_dir"
	echo "use: git --git-dir=$shim_dir --work-tree=$repo_root <cmd>"
	echo "env: DS4_GIT_DIR=$shim_dir DS4_GIT_WORK_TREE=$repo_root"
	exit 0
fi

git_file="$repo_root/.git"
orig_gitdir="${SOURCE_GIT_DIR:-}"
if [ "$orig_gitdir" = "" ] && [ -d "$repo_root/.codex_git_worktree" ] && [ -r "$repo_root/.codex_git_worktree/HEAD" ] && [ -r "$repo_root/.codex_git_worktree/index" ]; then
	orig_gitdir="$repo_root/.codex_git_worktree"
fi
if [ "$orig_gitdir" = "" ]; then
	if [ ! -r "$git_file" ]; then
		echo "error: missing readable $git_file (expected git worktree .git file)" >&2
		echo "hint: set SOURCE_GIT_DIR=/abs/path/to/gitdir to override" >&2
		exit 2
	fi
	orig_gitdir="$(sed -n 's/^gitdir: //p' "$git_file" | head -n 1 || true)"
fi
if [ "$orig_gitdir" = "" ] || [ ! -d "$orig_gitdir" ]; then
	echo "error: could not locate gitdir from $git_file" >&2
	echo "note: expected: gitdir: /abs/path/to/.git/worktrees/<id>" >&2
	echo "hint: set SOURCE_GIT_DIR=/abs/path/to/gitdir to override" >&2
	exit 3
fi

if [ ! -r "$orig_gitdir/commondir" ]; then
	echo "error: missing commondir under $orig_gitdir (not a linked worktree gitdir?)" >&2
	exit 4
fi

common_dir="$(cd "$orig_gitdir" && cd "$(cat commondir)" && pwd)"
if [ "$common_dir" = "" ] || [ ! -d "$common_dir" ]; then
	echo "error: failed to resolve common git dir from $orig_gitdir/commondir" >&2
	exit 5
fi

tmp="${shim_dir}.tmp.$$"
rm -rf "$tmp"
mkdir -p "$tmp"
cp -a "$orig_gitdir/." "$tmp"
printf "%s\n" "$common_dir" >"$tmp/commondir"
printf "%s\n" "$git_file" >"$tmp/gitdir"

rm -rf "$shim_dir"
mv "$tmp" "$shim_dir"

echo "ok: created writable git shim: $shim_dir"
echo "use: git --git-dir=$shim_dir --work-tree=$repo_root <cmd>"
echo "env: DS4_GIT_DIR=$shim_dir DS4_GIT_WORK_TREE=$repo_root"
