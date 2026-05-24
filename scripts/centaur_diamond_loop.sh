#!/usr/bin/env bash
# Daily Centaur diamond loop with lazy-vLLM backpressure and human review queue.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QUEUE_ROOT="${QUEUE_ROOT:-$HOME/centaur_review_queue}"
SPARKS="${SPARKS:-spark6 spark7 spark0 spark3}"
MODEL="${MODEL:-deepseek-ai/DeepSeek-V4-Flash}"
TARGET_COUNT="${TARGET_COUNT:-20}"
PROMPT_VARIANTS="${PROMPT_VARIANTS:-16}"
CENTAUR_REPO="${CENTAUR_REPO:-$HOME/centaur}"
SPARK_PORT="${SPARK_PORT:-8000}"
STATUS_TIMEOUT="${STATUS_TIMEOUT:-10}"
MAX_HELD_SECONDS="${MAX_HELD_SECONDS:-14400}"
SKIP_WINDOW_DAYS="${SKIP_WINDOW_DAYS:-7}"
MIN_FREE_GIB="${MIN_FREE_GIB:-20}"
MIN_COMPLEXITY="${MIN_COMPLEXITY:-8}"
DISCOVER_MAX_TARGETS="${DISCOVER_MAX_TARGETS:-200}"
MAX_TOKENS="${MAX_TOKENS:-4096}"
WORKERS="${WORKERS:-128}"
RUN_ID="${RUN_ID:-centaur_diamond_$(date -u +%Y%m%dT%H%M%SZ)}"
DRY_RUN=0

usage()
{
	cat <<'EOF'
usage: centaur_diamond_loop.sh [options]

Options:
  --queue-root DIR        Review queue root (default: ~/centaur_review_queue)
  --sparks "LIST"        Space-separated Spark hosts (default: spark6 spark7 spark0 spark3)
  --model MODEL          Lazy proxy model id (default: deepseek-ai/DeepSeek-V4-Flash)
  --target-count N       Targets per run (default: 20)
  --prompt-variants N    Variants per target (default: 16)
  --centaur-repo DIR     Remote Centaur checkout (default: ~/centaur)
  --run-id ID            Stable run id
  --dry-run              Build local plan and skip ssh/rsync
EOF
}

while [ "$#" -gt 0 ]; do
	case "$1" in
		--queue-root) QUEUE_ROOT="$2"; shift 2 ;;
		--sparks) SPARKS="$2"; shift 2 ;;
		--model) MODEL="$2"; shift 2 ;;
		--target-count) TARGET_COUNT="$2"; shift 2 ;;
		--prompt-variants) PROMPT_VARIANTS="$2"; shift 2 ;;
		--centaur-repo) CENTAUR_REPO="$2"; shift 2 ;;
		--run-id) RUN_ID="$2"; shift 2 ;;
		--dry-run) DRY_RUN=1; shift ;;
		-h|--help) usage; exit 0 ;;
		*) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
	esac
done

QUEUE_ROOT="$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).expanduser())' "$QUEUE_ROOT")"
mkdir -p "$QUEUE_ROOT"/pending "$QUEUE_ROOT"/approved "$QUEUE_ROOT"/rejected "$QUEUE_ROOT"/failures "$QUEUE_ROOT"/incoming "$QUEUE_ROOT"/runs

safe_name()
{
	printf '%s' "$1" | tr -c 'A-Za-z0-9_.@+-' '_' | cut -c1-120
}

log_failure()
{
	stage="$1"
	spark="$2"
	message="$3"
	stamp="$(date -u +%Y%m%dT%H%M%SZ)"
	path="$QUEUE_ROOT/failures/${stamp}-$(safe_name "$stage")-$(safe_name "$spark").log"
	{
		printf 'run_id=%s\n' "$RUN_ID"
		printf 'stage=%s\n' "$stage"
		printf 'spark=%s\n' "$spark"
		printf 'model=%s\n' "$MODEL"
		printf 'timestamp=%s\n' "$stamp"
		printf '%s\n' "$message"
	} > "$path"
	printf 'logged failure: %s\n' "$path" >&2
}

build_skip_list()
{
	out="$1"
	python3 - "$QUEUE_ROOT" "$out" "$SKIP_WINDOW_DAYS" <<'PY'
from __future__ import annotations
import datetime as dt
import json
import sys
from pathlib import Path
root = Path(sys.argv[1]).expanduser()
out = Path(sys.argv[2])
days = int(sys.argv[3])
now = dt.datetime.now(dt.timezone.utc)
cutoff = now - dt.timedelta(days=days)
targets: set[str] = set()
for base in (root / "pending", root / "approved"):
    if not base.exists():
        continue
    for meta_path in base.glob("*/*/*/metadata.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        queued = str(meta.get("queued_at") or "")
        try:
            if queued.endswith("Z"):
                queued = queued[:-1] + "+00:00"
            when = dt.datetime.fromisoformat(queued) if queued else dt.datetime.fromtimestamp(meta_path.stat().st_mtime, dt.timezone.utc)
        except Exception:
            when = dt.datetime.fromtimestamp(meta_path.stat().st_mtime, dt.timezone.utc)
        if when >= cutoff and meta.get("target_id"):
            targets.add(str(meta["target_id"]))
payload = {
    "format": "centaur-diamond-skip-list-v1",
    "cutoff": cutoff.isoformat().replace("+00:00", "Z"),
    "target_ids": sorted(targets),
}
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(len(targets))
PY
}

status_decision()
{
	status_file="$1"
	python3 - "$status_file" "$MAX_HELD_SECONDS" <<'PY'
from __future__ import annotations
import json
import sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
max_held = int(sys.argv[2])
active = bool(data.get("active"))
model = data.get("current_model")
idle = int(data.get("idle_seconds") or 0)
if not active and not model:
    print("free")
elif active and idle > max_held:
    print("held_too_long")
else:
    print("busy")
PY
}

status_pid()
{
	status_file="$1"
	python3 - "$status_file" <<'PY'
from __future__ import annotations
import json
import sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(data.get("pid") or "")
PY
}

spark_is_free()
{
	spark="$1"
	status_file="$(mktemp)"
	if ! ssh -o BatchMode=yes -o ConnectTimeout="$STATUS_TIMEOUT" "$spark" "curl -fsS --max-time $STATUS_TIMEOUT http://127.0.0.1:$SPARK_PORT/ds4/status" > "$status_file" 2>&1; then
		log_failure "lazy_proxy_timeout" "$spark" "$(cat "$status_file")"
		rm -f "$status_file"
		return 1
	fi
	decision="$(status_decision "$status_file")"
	case "$decision" in
		free)
			rm -f "$status_file"
			return 0
			;;
		held_too_long)
			log_failure "model_held_over_4h" "$spark" "$(cat "$status_file")"
			rm -f "$status_file"
			return 1
			;;
		*)
			pid="$(status_pid "$status_file")"
			if [ -n "$pid" ]; then
				held_seconds="$(ssh -o BatchMode=yes -o ConnectTimeout="$STATUS_TIMEOUT" "$spark" "ps -o etimes= -p '$pid' 2>/dev/null | awk 'NR==2 {print \$1}'" || true)"
				if [ -n "$held_seconds" ] && [ "$held_seconds" -gt "$MAX_HELD_SECONDS" ]; then
					log_failure "model_held_over_4h" "$spark" "$(cat "$status_file")
pid_elapsed_seconds=$held_seconds"
					rm -f "$status_file"
					return 1
				fi
			fi
			printf '%s busy: %s\n' "$spark" "$(cat "$status_file")" >&2
			rm -f "$status_file"
			return 1
			;;
	esac
}

release_spark()
{
	spark="$1"
	if ! ssh -o BatchMode=yes -o ConnectTimeout="$STATUS_TIMEOUT" "$spark" "PORT=$SPARK_PORT ~/bin/ds4_vllm_lazy_release.sh" >/dev/null 2>&1; then
		log_failure "release_failed" "$spark" "lazy release command failed"
	fi
}

_ssh_step()
{
	step_name="$1"
	spark="$2"
	remote_log="$3"
	shift 3
	if "$@" > "$remote_log" 2>&1; then
		return 0
	fi
	log_failure "$step_name" "$spark" "$(cat "$remote_log")"
	rm -f "$remote_log"
	return 1
}

_remote_run_diamond()
{
	spark="$1"
	remote_dir="$2"
	remote_log="$3"
	ssh -o BatchMode=yes -o ConnectTimeout="$STATUS_TIMEOUT" "$spark" \
		"RUN_ID='$RUN_ID' MODEL='$MODEL' TARGET_COUNT='$TARGET_COUNT' PROMPT_VARIANTS='$PROMPT_VARIANTS' CENTAUR_REPO='$CENTAUR_REPO' SPARK_PORT='$SPARK_PORT' REMOTE_DIR='$remote_dir' MIN_FREE_GIB='$MIN_FREE_GIB' MIN_COMPLEXITY='$MIN_COMPLEXITY' DISCOVER_MAX_TARGETS='$DISCOVER_MAX_TARGETS' MAX_TOKENS='$MAX_TOKENS' WORKERS='$WORKERS' bash -s" > "$remote_log" 2>&1 <<'REMOTE'
set -euo pipefail
cd "$CENTAUR_REPO"
avail_gib="$(df -Pk "$REMOTE_DIR" | awk 'NR==2 {print int($4 / 1024 / 1024)}')"
if [ "$avail_gib" -lt "$MIN_FREE_GIB" ]; then
	echo "full disk risk: ${avail_gib}GiB free under $REMOTE_DIR, need ${MIN_FREE_GIB}GiB" >&2
	exit 31
fi
PATH="$HOME/.venvs/shinka-diamond/bin:$PATH"
python3 -m v2.centaur_over_shinka_cli discover-targets \
	--repo-root . \
	--output "$REMOTE_DIR/all_targets.json" \
	--max-targets "$DISCOVER_MAX_TARGETS" \
	--min-complexity "$MIN_COMPLEXITY"
python3 - "$REMOTE_DIR/all_targets.json" "$REMOTE_DIR/selected_targets.json" "$REMOTE_DIR/skip_targets.json" "$TARGET_COUNT" <<'PY'
from __future__ import annotations
import json
import sys
from pathlib import Path
manifest_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
skip_path = Path(sys.argv[3])
limit = int(sys.argv[4])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
targets = manifest.get("targets", manifest if isinstance(manifest, list) else [])
skip = set(json.loads(skip_path.read_text(encoding="utf-8")).get("target_ids", []))
chosen = [target for target in targets if str(target.get("target_id", "")) not in skip][:limit]
if not chosen:
    print("no eligible Centaur diamond targets after seven-day skip window", file=sys.stderr)
    raise SystemExit(20)
payload = manifest if isinstance(manifest, dict) else {"format": "centaur-diamond-target-manifest-v1"}
payload["targets"] = chosen
payload["target_count"] = len(chosen)
out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"selected {len(chosen)} targets")
PY
python3 -m v2.centaur_over_shinka_cli prepare-dgx-run \
	--repo-root . \
	--targets "$REMOTE_DIR/selected_targets.json" \
	--output-dir "$REMOTE_DIR/dgx_batch" \
	--model "$MODEL" \
	--runner-command "$HOME/bin/sparkrunner_lazy_adapter.sh" \
	--prompt-variants "$PROMPT_VARIANTS" \
	--accept-large-run
cd "$REMOTE_DIR/dgx_batch"
SPARKRUNNER_LAZY_BASE_URL="http://127.0.0.1:$SPARK_PORT/v1" \
SPARKRUNNER_LAZY_WORKERS="$WORKERS" \
SPARKRUNNER_LAZY_MAX_TOKENS_CAP="$MAX_TOKENS" \
CENTAUR_VERIFY_AFTER_DGX=1 \
	./run_dgx_sparkrunner.sh
REMOTE
}

_collect_and_release()
{
	spark="$1"
	remote_dir="$2"
	started="$3"
	incoming="$QUEUE_ROOT/incoming/$RUN_ID"
	mkdir -p "$incoming"
	if ! rsync -a "$spark:$remote_dir/dgx_batch/verified/" "$incoming/verified/"; then
		log_failure "rsync_verified_failed" "$spark" "failed to rsync $remote_dir/dgx_batch/verified"
		return 1
	fi
	ended="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
	"$ROOT/scripts/centaur_release_review_queue.sh" \
		--verified-dir "$incoming/verified" \
		--queue-root "$QUEUE_ROOT" \
		--run-id "$RUN_ID" \
		--spark "$spark" \
		--model "$MODEL" \
		--started-at "$started" \
		--ended-at "$ended"
}

run_remote_loop()
{
	spark="$1"
	skip_file="$2"
	remote_dir="/tmp/${RUN_ID}"
	started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
	remote_log="$(mktemp)"
	_ssh_step "spark_unreachable" "$spark" "$remote_log" \
		ssh -o BatchMode=yes -o ConnectTimeout="$STATUS_TIMEOUT" "$spark" "mkdir -p '$remote_dir'" || return 1
	_ssh_step "stage_skip_list_failed" "$spark" "$remote_log" \
		scp -q "$skip_file" "$spark:$remote_dir/skip_targets.json" || return 1
	if ! _remote_run_diamond "$spark" "$remote_dir" "$remote_log"; then
		log_failure "remote_run_failed" "$spark" "$(cat "$remote_log")"
		rm -f "$remote_log"
		return 1
	fi
	cat "$remote_log"
	rm -f "$remote_log"
	_collect_and_release "$spark" "$remote_dir" "$started"
}

skip_file="$QUEUE_ROOT/incoming/$RUN_ID/skip_targets.json"
skip_count="$(build_skip_list "$skip_file")"

if [ "$DRY_RUN" -eq 1 ]; then
	cat <<EOF
{
  "format": "centaur-diamond-loop-plan-v1",
  "run_id": "$RUN_ID",
  "queue_root": "$QUEUE_ROOT",
  "sparks": "$SPARKS",
  "model": "$MODEL",
  "target_count": $TARGET_COUNT,
  "prompt_variants": $PROMPT_VARIANTS,
  "planned_prompts": $((TARGET_COUNT * PROMPT_VARIANTS)),
  "skip_targets": $skip_count,
  "skip_file": "$skip_file",
  "dry_run": true
}
EOF
	exit 0
fi

for spark in $SPARKS; do
	if ! spark_is_free "$spark"; then
		continue
	fi
	if run_remote_loop "$spark" "$skip_file"; then
		release_spark "$spark"
		exit 0
	fi
	release_spark "$spark"
done

log_failure "no_spark_completed" "operator" "all configured Sparks failed or were busy"
exit 1
