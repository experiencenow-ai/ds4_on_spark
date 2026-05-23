# Spark Ring

> Supersedes: `docs/spark-ring-fast-transfer.md`, `docs/spark0-spark1-ready.md`, `docs/spark-ring-network-map.md`, `docs/spark-ring-access-checklist.md`, `docs/spark-ring-ops-readiness-tp3.md`, `docs/spark-ring-ops-readiness-tp2.md`, `docs/spark-access.md`, `docs/spark-ring-ops-checklist.md`, `docs/spark0-cuda-toolchain-facts.md`, `docs/spark-ring-ops-checklist-tp3.md`, `docs/spark-ring-ops-transition-tp2-to-tp3.md`, `docs/spark-ring-ops-quickstart-tp3.md`, `docs/spark-model-cache.md`, `docs/spark-ring-ops-checklist-tp2.md`, `docs/spark-ring-readiness-status.md`, `docs/spark-ring-node-bringup.md`, `docs/spark-ring-ops-quickstart-tp2.md`

This is the canonical document for this topic. Update this file instead of adding a new overlapping note.

## Scope

- Consolidates 17 previous document(s) into one non-overlapping reference.
- Preserves stable commands, constraints, and source inventory; removes per-iteration narrative duplication.
- Historical probe/status fragments should live in git history, not as active docs.

## Current Guidance

- `spark-ring-fast-transfer.md`: Spark Ring Fast Transfer (143 lines).
- `spark0-spark1-ready.md`: Spark0/Spark1 Probe Runbook (133 lines).
- `spark-ring-network-map.md`: Spark Ring Network Map (10 lines).
- `spark-ring-access-checklist.md`: Spark Ring Access Checklist (Ordered Spark Inventory) (139 lines).
- `spark-ring-ops-readiness-tp3.md`: Spark Ring Ops Readiness (Spark0/Spark1/Spark2 / TP=3) (119 lines).
- `spark-ring-ops-readiness-tp2.md`: Spark Ring Ops Readiness (Spark0/Spark1 / TP=2 Baseline) (111 lines).
- `spark-access.md`: Spark Access Notes (371 lines).
- `spark-ring-ops-checklist.md`: Example Spark Ring Ops Checklist (Spark0..Spark3) (46 lines).
- `spark0-cuda-toolchain-facts.md`: Spark0 CUDA + Toolchain Facts (Stable Reference) (31 lines).
- `spark-ring-ops-checklist-tp3.md`: Spark Ring Ops Checklist (Spark0/Spark1/Spark2) (124 lines).
- `spark-ring-ops-transition-tp2-to-tp3.md`: Spark Ring Transition Runbook (TP=2 → TP=3) (153 lines).
- `spark-ring-ops-quickstart-tp3.md`: Spark Ring Ops Quickstart (Spark0/Spark1/Spark2 / TP=3) (158 lines).
- `spark-model-cache.md`: Spark Model Cache (145 lines).
- `spark-ring-ops-checklist-tp2.md`: Spark Ring Ops Checklist (Spark0/Spark1 / TP=2 Baseline) (106 lines).
- `spark-ring-readiness-status.md`: Spark Ring Readiness Status (Spark0..Spark2) (57 lines).
- `spark-ring-node-bringup.md`: Spark Ring Node Bring-up (Spark1/Spark2 Ready) (111 lines).
- `spark-ring-ops-quickstart-tp2.md`: Spark Ring Ops Quickstart (Spark0/Spark1 / TP=2 Baseline) (109 lines).

## Command Inventory

- `spark-ring-fast-transfer.md`: `ssh spark3 'for ip in 10.10.5.2 10.10.6.2 10.10.7.2 10.10.8.2; do ping -M do -s 8972 -c 1 "$ip"; done'`
- `spark-ring-fast-transfer.md`: `ssh spark5 'for ip in 10.10.9.1 10.10.10.1 10.10.11.2 10.10.12.2; do ping -M do -s 8972 -c 1 "$ip"; done'`
- `spark-ring-fast-transfer.md`: `ssh spark3 'iperf3 -s -B 10.10.5.1 -1'`
- `spark-ring-fast-transfer.md`: `ssh spark2 'iperf3 -c 10.10.5.1 -P 16 -w 16M -t 20'`
- `spark-ring-fast-transfer.md`: `ssh spark3 'for i in $(seq 0 63); do port=$((25700+i)); (nc -l $port | dd of=/dev/null bs=64M status=none) & done; wait'`
- `spark-ring-fast-transfer.md`: `ssh spark2 '/usr/bin/time -f elapsed=%e sh -c '\''for i in $(seq 0 63); do port=$((25700+i)); ip=10.10.5.1; if [ $((i%2)) -eq 1 ]; then ip=10.10.6.1; fi; (dd if=/dev/zero bs=64M count=1 status=none | nc -N $ip $port) & done; wait'\'''`
- `spark-ring-fast-transfer.md`: `ssh spark2 'sha256sum /models/foo.gguf'`
- `spark-ring-fast-transfer.md`: `ssh spark3 'sha256sum /models/foo.gguf'`
- `spark-ring-fast-transfer.md`: `rsync -a --dry-run --checksum -e ssh spark2:/models/foo/ spark3:/models/foo/`
- `spark0-spark1-ready.md`: `SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh aitopatom-9ab9.local | tee /private/tmp/spark0-probe.txt`
- `spark0-spark1-ready.md`: `SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark1.local | tee /private/tmp/spark1-probe.txt`
- `spark0-spark1-ready.md`: `SPARK_SSH_USER=spark0 REDACT=1 SPARK_PROBE_FACTS=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh spark1.local || true`
- `spark0-spark1-ready.md`: `SPARK_SSH_USER=spark0 REDACT=1 SPARK_PROBE_SUMMARY=1 ./scripts/spark_probe.sh spark1.local || true`
- `spark0-spark1-ready.md`: `SPARK_SSH_USER=spark0 REDACT=1 NVIDIA_SMI_FULL=1 ./scripts/spark_probe.sh aitopatom-9ab9.local | tee /private/tmp/spark0-probe-verbose.txt`
- `spark0-spark1-ready.md`: `SPARK_SSH_USER=spark0 REDACT=1 CUDA_RUNTIME_PROBE=0 ./scripts/spark_probe.sh aitopatom-9ab9.local`
- `spark0-spark1-ready.md`: `SPARK_SSH_USER=spark0 REDACT=1 NVCC_ARCH=sm_121 ./scripts/spark_probe.sh aitopatom-9ab9.local`
- `spark-ring-access-checklist.md`: `SPARK_SSH_USER=spark0 REDACT=1 SPARK_NODE_FACTS=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe_snapshots.sh --stamp "$stamp" --topology full aitopatom-9ab9.local spark1.local spark2.local`
- `spark-ring-ops-readiness-tp3.md`: `./scripts/ops_spark_ring_ops_check.sh --out "/private/tmp/ds4_ops_check_tp3_$(date -u +%Y%m%d-%H%M%SZ).txt" \`
- `spark-ring-ops-readiness-tp3.md`: `./scripts/ops_spark_ring_ops_check.sh --preflight tp3 --strict --journal --lines 120 \`
- `spark-ring-ops-readiness-tp3.md`: `./scripts/ops_spark_ring_staged_env_audit.sh spark0@... spark1@... spark2@...`
- `spark-ring-ops-readiness-tp3.md`: `./scripts/ops_spark_ring_staged_readiness.sh --topology ring --preflight tp3 --strict \`
- `spark-ring-ops-readiness-tp2.md`: `./scripts/ops_spark_ring_ops_check.sh --out "/private/tmp/ds4_ops_check_tp2_$(date -u +%Y%m%d-%H%M%SZ).txt" \`
- `spark-ring-ops-readiness-tp2.md`: `./scripts/ops_spark_ring_ops_check.sh --preflight tp2 --strict --journal --lines 120 \`
- `spark-access.md`: `git init --bare .codex_git`
- `spark-access.md`: `git --git-dir=.codex_git remote add origin git@github.com:experiencenow-ai/ds4_on_spark.git`
- `spark-access.md`: `git --git-dir=.codex_git fetch origin main --prune`
- `spark-access.md`: `git --git-dir=.codex_git --work-tree=. reset --hard origin/main`
- `spark-access.md`: `git --git-dir=.codex_git --work-tree=. checkout -b codex/loop-spark-access-YYYYMMDD-short-suffix origin/main`
- `spark-access.md`: `git --git-dir=.codex_git init`
- `spark-access.md`: `git --git-dir=.codex_git --work-tree=. remote add origin git@github.com:experiencenow-ai/ds4_on_spark.git`
- `spark-access.md`: `git --git-dir=.codex_git --work-tree=. fetch origin main --depth=50`
- `spark-access.md`: `git --git-dir=.codex_git --work-tree=. fetch origin --prune`
- `spark-access.md`: `git --git-dir=.codex_git config core.bare false`
- `spark0-cuda-toolchain-facts.md`: `SPARK_SSH_USER=spark0 REDACT=1 SPARK_PROBE_FACTS=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_probe.sh aitopatom-9ab9.local > "docs/spark0-probe-facts-${stamp}.md"`
- `spark-ring-ops-transition-tp2-to-tp3.md`: `./scripts/ops_validate_deploy_assets.sh`
- `spark-ring-ops-transition-tp2-to-tp3.md`: `./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring \`
- `spark-ring-ops-transition-tp2-to-tp3.md`: `./scripts/ops_spark_ring_ops_check.sh --out "${RUN_DIR:-/private/tmp}/ds4_ops_check_tp23_$(date -u +%Y%m%d-%H%M%SZ).txt" \`
- `spark-ring-ops-transition-tp2-to-tp3.md`: `./scripts/ops_spark_ring_ops_check.sh --out "${RUN_DIR:-/private/tmp}/ds4_ops_check_tp23_post_$(date -u +%Y%m%d-%H%M%SZ).txt" \`
- `spark-ring-ops-quickstart-tp3.md`: `./scripts/ops_validate_deploy_assets.sh`
- `spark-ring-ops-quickstart-tp3.md`: `./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring \`
- `spark-ring-ops-quickstart-tp3.md`: `./scripts/ops_spark_ring_ops_check.sh --out "/private/tmp/ds4_ops_check_tp3_$(date -u +%Y%m%d-%H%M%SZ).txt" \`
- `spark-ring-ops-quickstart-tp3.md`: `curl -fsS http://spark0.local:9090/metrics | head`
- `spark-ring-readiness-status.md`: `SPARK_SSH_USER=spark0 REDACT=1 SPARK_NODE_FACTS=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe_snapshots.sh --stamp "$stamp" --topology full aitopatom-9ab9.local spark1.local spark2.local`
- `spark-ring-node-bringup.md`: `SPARK_KNOWN_HOSTS_PER_HOST=1 ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts.spark1.local spark0@spark1.local 'hostname'`
- `spark-ring-node-bringup.md`: `SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe_facts.sh --stamp "$stamp" spark1.local`
- `spark-ring-node-bringup.md`: `SPARK_SSH_USER=spark0 REDACT=1 SPARK_NODE_FACTS=1 SPARK_KNOWN_HOSTS_PER_HOST=1 DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. ./scripts/spark_ring_probe_snapshots.sh --stamp "$stamp" --topology full aitopatom-9ab9.local spark1.local spark2.local`
- `spark-ring-ops-quickstart-tp2.md`: `./scripts/ops_validate_deploy_assets.sh`
- `spark-ring-ops-quickstart-tp2.md`: `./scripts/ops_stage_spark0_spark1.sh --mesh-check spark0@<spark0-host> spark1@<spark1-host>`
- `spark-ring-ops-quickstart-tp2.md`: `./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring \`
- `spark-ring-ops-quickstart-tp2.md`: `./scripts/ops_spark_ring_ops_check.sh --out "/private/tmp/ds4_ops_check_tp2_$(date -u +%Y%m%d-%H%M%SZ).txt" \`

## Source Map

| Source | Lines | Main heading | Subsections |
|---|---:|---|---|
| `docs/spark-ring-fast-transfer.md` | 143 | Spark Ring Fast Transfer | Rule, Utility, Tuning, Verification, Current Spark2-Spark3 Smoke Tests |
| `docs/spark0-spark1-ready.md` | 133 | Spark0/Spark1 Probe Runbook | Current Status (2026-05-12), Goals, Spark2 / Ring Next Steps, Mac-Side Discovery, Spark Probe (Redacted) |
| `docs/spark-ring-network-map.md` | 10 | Spark Ring Network Map | - |
| `docs/spark-ring-access-checklist.md` | 139 | Spark Ring Access Checklist (Ordered Spark Inventory) | Quickstart (Commit-Safe Ring Snapshot Set), Three-node Ring Access Checklist (Spark0..Spark2), 1) Hostnames + Resolution, 2) SSH Keys + Known Hosts Hygiene, 3) Clock Sync (Skew + NTP State) |
| `docs/spark-ring-ops-readiness-tp3.md` | 119 | Spark Ring Ops Readiness (Spark0/Spark1/Spark2 / TP=3) | One Command Snapshot (Mac Side, Safe), Readiness Rubric (TP=3), TP=2 / TP=3 Readiness Notes (Future-Proofing) |
| `docs/spark-ring-ops-readiness-tp2.md` | 111 | Spark Ring Ops Readiness (Spark0/Spark1 / TP=2 Baseline) | One Command Snapshot (Mac Side, Safe), Readiness Rubric (TP=2), TP=2 / TP=3 Readiness Notes (Future-Proofing) |
| `docs/spark-access.md` | 371 | Spark Access Notes | Reproducible Probes, Spark1 Ready Checklist, Spark Ring (Spark0..Spark2) Access + Probes, Diagnosis, If Account Auth Needs Reset Again |
| `docs/spark-ring-ops-checklist.md` | 46 | Example Spark Ring Ops Checklist (Spark0..Spark3) | Bring-up (Once), Before A TP=4 Attempt (Repeatable), If Something Fails |
| `docs/spark0-cuda-toolchain-facts.md` | 31 | Spark0 CUDA + Toolchain Facts (Stable Reference) | Current Facts (observed 2026-05-13), How To Re-Verify (Commit-Safe) |
| `docs/spark-ring-ops-checklist-tp3.md` | 124 | Spark Ring Ops Checklist (Spark0/Spark1/Spark2) | Bring-up (Once), Developer Path (`systemd --user`) (Optional), Before A TP=3 Attempt (Repeatable), During A TP=3 Attempt (Repeatable), Planned Restart / Config Change (Repeatable) |
| `docs/spark-ring-ops-transition-tp2-to-tp3.md` | 153 | Spark Ring Transition Runbook (TP=2 → TP=3) | Overview, 0) Prereqs (Mac Side), 1) Validate + Stage (Mac Side, Safe), 2) Install + Validate (Spark Side, Human Approval), 3) Gate With Strict Preflights (Spark Side, Safe) |
| `docs/spark-ring-ops-quickstart-tp3.md` | 158 | Spark Ring Ops Quickstart (Spark0/Spark1/Spark2 / TP=3) | 0) Choose Names + Inventory (Mac Side), 1) Stage Deploy Assets + Scripts (Mac Side, Safe), 2) Install System Units + Config (Spark Side, Human Approval), 3) Run Strict Readiness Gates (Spark Side, Safe), 4) Start DS4 (Spark Side, Human Approval) |
| `docs/spark-model-cache.md` | 145 | Spark Model Cache | Canonical Root, Required Layout, Candidate Shelf, Copy Rule, Verification |
| `docs/spark-ring-ops-checklist-tp2.md` | 106 | Spark Ring Ops Checklist (Spark0/Spark1 / TP=2 Baseline) | Bring-up (Once), Developer Path (`systemd --user`) (Optional), Before A TP=2 Attempt (Repeatable), During A TP=2 Attempt (Repeatable), Planned Restart / Config Change (Repeatable) |
| `docs/spark-ring-readiness-status.md` | 57 | Spark Ring Readiness Status (Spark0..Spark2) | Latest commit-safe snapshots, Snapshot command (commit-safe), Ring readiness matrix, When Spark1/Spark2 appear (minimum next actions) |
| `docs/spark-ring-node-bringup.md` | 111 | Spark Ring Node Bring-up (Spark1/Spark2 Ready) | 0) Decide identity + SSH user, 1) Mac-side preflight (resolution + port 22 + ping), 2) SSH key auth (non-interactive) + probe-scoped known_hosts, 3) Clock sanity (UTC + skew + NTP state), 4) Capture a per-node facts snapshot (GPU/CUDA/toolchain/storage) |
| `docs/spark-ring-ops-quickstart-tp2.md` | 109 | Spark Ring Ops Quickstart (Spark0/Spark1 / TP=2 Baseline) | 0) Choose Names + Inventory (Mac Side), 1) Stage Deploy Assets + Scripts (Mac Side, Safe), 2) Install System Units + Config (Spark Side, Human Approval), 3) Run Strict Preflight (Safe Gate), 4) Start DS4 (Optional; Human Approval) |
