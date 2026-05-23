# Automation

> Supersedes: `docs/automation-github-protocol.md`, `docs/automation-loops.md`, `docs/codex-task-runner.md`

This is the canonical document for this topic. Update this file instead of adding a new overlapping note.

## Scope

- Consolidates 3 previous document(s) into one non-overlapping reference.
- Preserves stable commands, constraints, and source inventory; removes per-iteration narrative duplication.
- Historical probe/status fragments should live in git history, not as active docs.

## Current Guidance

- `automation-github-protocol.md`: Automation GitHub Protocol (91 lines).
- `automation-loops.md`: Automation Loops (136 lines).
- `codex-task-runner.md`: Codex Task Runner (68 lines).

## Command Inventory

- `codex-task-runner.md`: `./scripts/codex_task.py <task> [options]`
- `codex-task-runner.md`: `./scripts/codex_task.py mtp-local-verify`
- `codex-task-runner.md`: `./scripts/codex_task.py spark-antirez-oracle --run`
- `codex-task-runner.md`: `./scripts/codex_task.py spark-antirez-oracle --fresh`
- `codex-task-runner.md`: `./scripts/codex_task.py spark-llamacpp-mtp-probe --fresh --load-sidecar-weights`
- `codex-task-runner.md`: `./scripts/codex_task.py pr-status`
- `codex-task-runner.md`: `./scripts/codex_task.py automation-status`
- `codex-task-runner.md`: `./scripts/codex_task.py repo-status`
- `codex-task-runner.md`: `./scripts/codex_task.py`

## Source Map

| Source | Lines | Main heading | Subsections |
|---|---:|---|---|
| `docs/automation-github-protocol.md` | 91 | Automation GitHub Protocol | Branch Ownership, Start Of Each Loop, Before Editing, Commit And PR Rules, Merge Rules |
| `docs/automation-loops.md` | 136 | Automation Loops | Loop 1: Spark Access, Loop 2: Hardware Baseline, Loop 3: Upstream Intake, Loop 4: Model Contract, Loop 5: Existing Baseline |
| `docs/codex-task-runner.md` | 68 | Codex Task Runner | Common Tasks, Approval Model |
