# Build Style

This repo follows a firmware-style C/CUDA coding discipline aimed at predictable performance and easy review.

Source of truth:

- `AGENTS.md` (repo-level rules)
- `SKILL.md` (detailed C style guide used by the automation)

## C/CUDA checklist

- Verify real struct/function definitions before coding against them (no semantic guesses).
- Prefer caller-owned, static allocation (`ds4_arena_t`, `ds4_pool_t`, fixed rings); avoid `malloc`/`free` in hot paths.
- Use `<stdint.h>` types internally (`uint8_t`, `int32_t`, `uint64_t`, ...); avoid implicit `bool` checks (`ptr != 0`).
- Compact Allman braces; single-statement `if`/`for`/`while` uses no braces.
- Unique negative return codes per failure path.
- Keep functions small (≈<50 lines) by splitting helpers before orchestrators.
- Keep functions in dependency order (callee before caller) when practical.
- Headers use `#pragma once`.

## Build hygiene

- Keep `make check` (CPU-only, `-Werror`) green on macOS.
- Keep `make check-cuda` green on Linux/Spark when CUDA is enabled.
