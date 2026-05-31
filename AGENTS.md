# Project Instructions

This repository targets Tockchain/Valis-style C/CUDA firmware-quality work.

## C/CUDA Style

- Verify existing structs, fields, function signatures, and semantics before
  writing code that touches them.
- Use `<stdint.h>` types internally: `uint8_t`, `int32_t`, `uint64_t`, etc.
- Avoid `malloc`/`free` in hot paths. Prefer startup allocation, arenas, or
  fixed pools.
- Keep functions under roughly 50 lines by splitting helpers before callers.
- Use compact Allman braces.
- Use explicit comparisons: `ptr != 0`, `err < 0`, `count == 0`.
- Return unique negative error codes per failure path.
- Keep functions in dependency order where practical.
- Use `#pragma once` for headers.
- No hidden semantic guesses. If the model or cache structure is unclear, read
  the source or generated contract first.

## Repo Practice

- Keep benchmark claims tied to scripts, hardware metadata, and command lines.
- Commit generated probe outputs only after redacting secrets, usernames that
  should not be public, tokens, and private LAN details if needed.
- Prefer narrow, measurable milestones over broad framework work.
- Deployment and benchmark tests must be zero-drift: commit the fix, open a PR,
  merge it to main, pull main on the target Spark checkouts, rebuild/install from
  those pulled checkouts, restart services, and only then test. Do not validate
  deployment behavior from local hotpatches, copied files, dirty trees, or
  unmerged branches.

## Codex Autonomy and Permissions

- Keep active repo work inside the checked-out repo and approved scratch space
  such as `/private/tmp`. Do not edit files under `$HOME`, downloads, or
  private tool state unless the user explicitly asks for that path.
- Minimize approval prompts by batching related edits into one patch or one
  repo-owned script change. Avoid many tiny edit operations.
- Prefer `scripts/codex_task.py` and other repo-owned runners for repeatable
  Spark, validation, PR, and status tasks. Add a small parameter to an existing
  runner before creating several one-off shell commands.
- Prefer simple command argv forms that match approved prefixes. Avoid heredocs,
  redirection-heavy commands, pipes, shell substitutions, and wildcard tricks
  when the same task can be done by an existing script or a simple command.
- Files created by Codex are still normal repo files; update them in the active
  branch and PR without asking the user again unless the sandbox actually blocks
  the write.
- Put large run artifacts under `/private/tmp/ds4_*` and summarize their paths
  in docs or PR text instead of committing the artifacts.
- Use PRs for repo changes. Do not push directly to `main`.
