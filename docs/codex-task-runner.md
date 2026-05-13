# Codex Task Runner

`scripts/codex_task.py` is a small allowlisted runner for common repo-owned
maintenance tasks. Its purpose is to reduce repeated approval prompts by giving
Codex one stable command prefix:

```bash
./scripts/codex_task.py <task> [options]
```

The runner does not execute arbitrary shell strings. Each task maps to fixed
subprocess argument arrays and accepts only narrow parameters.

## Common Tasks

Local MTP patch/math checks:

```bash
./scripts/codex_task.py mtp-local-verify
```

Run the antirez/ds4 one-token MTP oracle on Spark0 using the already prepared
Spark-side checkout:

```bash
./scripts/codex_task.py spark-antirez-oracle --run
```

Fresh Spark-side clone/patch/build/run:

```bash
./scripts/codex_task.py spark-antirez-oracle --fresh
```

Run the llama.cpp one-token MTP candidate probe on Spark0:

```bash
./scripts/codex_task.py spark-llamacpp-mtp-probe --fresh --load-sidecar-weights
```

Open PR status:

```bash
./scripts/codex_task.py pr-status
```

Local automation status:

```bash
./scripts/codex_task.py automation-status
```

Repo status:

```bash
./scripts/codex_task.py repo-status
```

## Approval Model

When the app asks for a reusable approval, prefer approving this prefix:

```text
./scripts/codex_task.py
```

That keeps approvals scoped to audited repo maintenance tasks instead of a broad
interpreter prefix such as `python3` or a collection of one-off probe scripts.
