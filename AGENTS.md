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

