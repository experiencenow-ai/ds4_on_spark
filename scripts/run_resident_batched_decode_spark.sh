#!/usr/bin/env sh
set -eu

# Resident batched decode runner for Spark-hosted llama-server.
#
# This runner does not fetch, build, or download model weights. It uploads the
# repo throughput driver, starts one resident llama-server for one
# (parallel,batch,ubatch) combo, sends concurrent completion waves, fetches the
# artifacts, and summarizes the best aggregate decode row.

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"

OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_resident_batched_decode}"
ALLOW_RUN="${ALLOW_RUN:-0}"

LLAMA_SERVER="${LLAMA_SERVER:-/home/spark0/src/llama.cpp-kamnxt/build-cuda/bin/llama-server}"
MODEL_GGUF="${MODEL_GGUF:-}"
MODEL_GGUF_GLOB="${MODEL_GGUF_GLOB:-/home/spark0/models/ds4/*.gguf}"
MODEL_GGUF_EXCLUDE_EGREP="${MODEL_GGUF_EXCLUDE_EGREP:-MTP|DFlash|draft|sidecar}"
MODEL_GGUF_INCLUDE_EGREP="${MODEL_GGUF_INCLUDE_EGREP:-IQ2|Q2_K|IQ3|Q3_K}"

PORT="${PORT:-18084}"
CTX="${CTX:-8192}"
N_GPU_LAYERS="${N_GPU_LAYERS:-99}"
N_PREDICT="${N_PREDICT:-64}"
REPEATS="${REPEATS:-1}"
PROMPT_WORDS="${PROMPT_WORDS:-16}"
CONCURRENCY="${CONCURRENCY:-1 2 4 8}"
PARALLEL_VALUES="${PARALLEL_VALUES:-8}"
BATCH_VALUES="${BATCH_VALUES:-2048}"
UBATCH_VALUES="${UBATCH_VALUES:-512}"
SERVER_ARGS="${SERVER_ARGS:---cache-ram -1 --fit off --no-warmup --no-webui --cache-prompt --log-verbosity 2 --metrics}"
CACHE_PROMPT="${CACHE_PROMPT:-0}"
SCRAPE_METRICS="${SCRAPE_METRICS:-1}"
RESTART_PER_COMBO="${RESTART_PER_COMBO:-0}"
KEEP_SERVER="${KEEP_SERVER:-0}"
WAIT_TIMEOUT_S="${WAIT_TIMEOUT_S:-1200}"
REQUEST_TIMEOUT_S="${REQUEST_TIMEOUT_S:-900}"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="$OUT_ROOT/$ts"
REMOTE_SWEEP_DIR="/tmp/ds4_resident_batched_decode_$ts"
LOCAL_SWEEP_BASE="${REMOTE_SWEEP_DIR##*/}"
LOCAL_SWEEP_DIR="$OUT_DIR/resident_batched_decode/$LOCAL_SWEEP_BASE"
REPORT_MD="$OUT_DIR/resident_batched_decode.md"
SUMMARY_JSON="$OUT_DIR/summary.json"

mkdir -p "$OUT_DIR"
echo "writing report to: $OUT_DIR"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
repo_rev="unknown"
if [ -e "$repo_root/.git" ]; then
	repo_rev="$(cd "$repo_root" && git rev-parse HEAD 2>/dev/null || echo unknown)"
fi

quote_sh()
{
	v="${1:-}"
	printf "'%s'" "$(printf %s "$v" | sed "s/'/'\\\\\\\\''/g")"
}

fetch_remote_dir_tar()
{
	remote_dir="${1:-}"
	local_tgz="${2:-}"
	remote_tar_script='set -eu; dir="$1"; if [ ! -d "$dir" ]; then exit 0; fi; base="${dir##*/}"; parent="${dir%/*}"; if [ "$parent" = "$dir" ]; then parent="."; fi; tar -C "$parent" -czf - "$base"'
	if [ "$remote_dir" = "" ] || [ "$local_tgz" = "" ]; then
		return 0
	fi
	ssh $SSH_OPTS "$target" "sh -lc $(quote_sh "$remote_tar_script") sh $(quote_sh "$remote_dir")" >"$local_tgz" 2>"$local_tgz.stderr" || true
}

remote_select_model_gguf()
{
	glob="${1:-}"
	exclude_re="${2:-}"
	include_re="${3:-}"
	if [ "$glob" = "" ]; then
		return 0
	fi
	ssh $SSH_OPTS "$target" "sh -lc 'set -eu; glob=\"\$1\"; exclude_re=\"\$2\"; include_re=\"\$3\"; best_path=\"\"; best_size=\"\"; for f in \$glob; do [ -r \"\$f\" ] || continue; base=\"\${f##*/}\"; if [ \"\$exclude_re\" != \"\" ] && printf %s \"\$base\" | grep -Eiq \"\$exclude_re\"; then continue; fi; if [ \"\$include_re\" != \"\" ] && ! printf %s \"\$base\" | grep -Eiq \"\$include_re\"; then continue; fi; sz=\$(stat -c %s \"\$f\" 2>/dev/null || (wc -c <\"\$f\" 2>/dev/null | tr -d \"[:space:]\") || true); [ \"\$sz\" != \"\" ] || continue; if [ \"\$best_size\" = \"\" ] || [ \"\$sz\" -lt \"\$best_size\" ]; then best_size=\"\$sz\"; best_path=\"\$f\"; fi; done; [ \"\$best_path\" != \"\" ]; printf \"%s\\n\" \"\$best_path\"' sh $(quote_sh "$glob") $(quote_sh "$exclude_re") $(quote_sh "$include_re")" 2>/dev/null || true
}

{
	echo "# Resident Batched Decode (Spark)"
	echo
	echo "Date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
	echo
	echo "- ds4_on_spark commit: $repo_rev"
	echo "- target: $target"
	echo "- allow_run: $ALLOW_RUN"
	echo "- llama_server: $LLAMA_SERVER"
	echo "- model_gguf: $MODEL_GGUF"
	echo "- port: $PORT"
	echo "- ctx: $CTX"
	echo "- n_predict: $N_PREDICT"
	echo "- prompt_words: $PROMPT_WORDS"
	echo "- concurrency: $CONCURRENCY"
	echo "- parallel_values: $PARALLEL_VALUES"
	echo "- batch_values: $BATCH_VALUES"
	echo "- ubatch_values: $UBATCH_VALUES"
	echo "- restart_per_combo: $RESTART_PER_COMBO"
	echo
} >"$REPORT_MD"

if [ "$ALLOW_RUN" != "1" ]; then
	cat >"$SUMMARY_JSON" <<'JSON'
{
  "ok": false,
  "skipped": true,
  "reason": "set ALLOW_RUN=1 to run resident batched decode"
}
JSON
	echo "run skipped: set ALLOW_RUN=1"
	exit 0
fi

if [ "$MODEL_GGUF" = "" ]; then
	MODEL_GGUF="$(remote_select_model_gguf "$MODEL_GGUF_GLOB" "$MODEL_GGUF_EXCLUDE_EGREP" "$MODEL_GGUF_INCLUDE_EGREP")"
fi

if [ "$MODEL_GGUF" = "" ]; then
	echo "error: no readable MODEL_GGUF selected on $target" >&2
	exit 4
fi
{
	echo "Selected model_gguf: $MODEL_GGUF"
	echo
} >>"$REPORT_MD"

echo "== preflight (Spark) =="
ssh $SSH_OPTS "$target" "sh -lc 'set -eu; srv=\"\$1\"; model=\"\$2\"; if [ ! -x \"\$srv\" ]; then echo \"error: LLAMA_SERVER not executable: \$srv\" >&2; exit 2; fi; if [ ! -r \"\$model\" ]; then echo \"error: MODEL_GGUF not readable: \$model\" >&2; exit 3; fi; echo \"ok: llama-server=\$srv\"; echo \"ok: model=\$model\"' sh $(quote_sh "$LLAMA_SERVER") $(quote_sh "$MODEL_GGUF")"

remote_env="LLAMA_SERVER=$(quote_sh "$LLAMA_SERVER") MODEL_GGUF=$(quote_sh "$MODEL_GGUF") PORT=$(quote_sh "$PORT") CTX=$(quote_sh "$CTX") N_GPU_LAYERS=$(quote_sh "$N_GPU_LAYERS") N_PREDICT=$(quote_sh "$N_PREDICT") REPEATS=$(quote_sh "$REPEATS") PROMPT_WORDS=$(quote_sh "$PROMPT_WORDS") CONCURRENCY=$(quote_sh "$CONCURRENCY") PARALLEL_VALUES=$(quote_sh "$PARALLEL_VALUES") BATCH_VALUES=$(quote_sh "$BATCH_VALUES") UBATCH_VALUES=$(quote_sh "$UBATCH_VALUES") SERVER_ARGS=$(quote_sh "$SERVER_ARGS") CACHE_PROMPT=$(quote_sh "$CACHE_PROMPT") SCRAPE_METRICS=$(quote_sh "$SCRAPE_METRICS") RESTART_PER_COMBO=$(quote_sh "$RESTART_PER_COMBO") KEEP_SERVER=$(quote_sh "$KEEP_SERVER") WAIT_TIMEOUT_S=$(quote_sh "$WAIT_TIMEOUT_S") REQUEST_TIMEOUT_S=$(quote_sh "$REQUEST_TIMEOUT_S") START_SERVER=1"

echo "== running resident throughput sweep on spark =="
ssh $SSH_OPTS "$target" "cat > /tmp/benchmark_llamacpp_server_throughput_sweep.py && chmod +x /tmp/benchmark_llamacpp_server_throughput_sweep.py && $remote_env OUT_DIR=$(quote_sh "$REMOTE_SWEEP_DIR") python3 /tmp/benchmark_llamacpp_server_throughput_sweep.py" \
	<"$repo_root/scripts/benchmark_llamacpp_server_throughput_sweep.py" \
	>"$OUT_DIR/remote_stdout.txt" 2>"$OUT_DIR/remote_stderr.txt" || true

fetch_remote_dir_tar "$REMOTE_SWEEP_DIR" "$OUT_DIR/remote_resident_batched_decode.tgz"
if [ -s "$OUT_DIR/remote_resident_batched_decode.tgz" ]; then
	mkdir -p "$OUT_DIR/resident_batched_decode"
	tar -xzf "$OUT_DIR/remote_resident_batched_decode.tgz" -C "$OUT_DIR/resident_batched_decode" >/dev/null 2>&1 || true
fi

BEST_DECODE_JSON="$LOCAL_SWEEP_DIR/throughput_best_decode.json"
python3 - "$BEST_DECODE_JSON" "$SUMMARY_JSON" "$REPORT_MD" "$OUT_DIR" "$LOCAL_SWEEP_DIR" "$REMOTE_SWEEP_DIR" <<'PY'
import json
import sys
from pathlib import Path

best_path = Path(sys.argv[1])
summary_path = Path(sys.argv[2])
report_path = Path(sys.argv[3])
out_dir = Path(sys.argv[4])
local_sweep_dir = Path(sys.argv[5])
remote_sweep_dir = sys.argv[6]

best = None
errors = []
if best_path.is_file():
	try:
		best = json.loads(best_path.read_text(encoding="utf-8"))
	except Exception as e:
		errors.append(f"failed to parse best decode JSON: {e}")
else:
	errors.append(f"missing best decode JSON: {best_path}")

ok = False
if isinstance(best, dict):
	try:
		ok = (
			int(best.get("error_count") or 0) == 0
			and int(best.get("ok_count") or 0) > 0
			and float(best.get("agg_generated_tok_s") or 0.0) > 0.0
		)
	except Exception:
		ok = False

summary = {
	"ok": ok,
	"errors": errors,
	"best_decode": best,
	"artifacts": {
		"out_dir": str(out_dir),
		"remote_stdout": str(out_dir / "remote_stdout.txt"),
		"remote_stderr": str(out_dir / "remote_stderr.txt"),
		"remote_tarball": str(out_dir / "remote_resident_batched_decode.tgz"),
		"local_sweep_dir": str(local_sweep_dir),
		"remote_sweep_dir": remote_sweep_dir,
		"best_decode_json": str(best_path),
	},
}
summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

with report_path.open("a", encoding="utf-8") as f:
	f.write("## Summary\n\n")
	f.write("```json\n")
	f.write(json.dumps(summary, indent=2, sort_keys=True))
	f.write("\n```\n\n")
	f.write("## Artifacts\n\n")
	for k, v in summary["artifacts"].items():
		f.write(f"- {k}: `{v}`\n")
	f.write("\n")
	f.write("## Remote Stdout Prefix\n\n```text\n")
	try:
		f.write((out_dir / "remote_stdout.txt").read_text(encoding="utf-8", errors="replace")[:8000])
	except OSError:
		pass
	f.write("\n```\n")
PY

echo "done: $REPORT_MD"
cat "$SUMMARY_JSON"
