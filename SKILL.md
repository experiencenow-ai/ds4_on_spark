---
name: ct-c-style
description: C coding style for Tockchain/Valis firmware development. Use when writing, reviewing, or modifying C code for this project. Enforces compact Allman bracing, stdint types, zero-copy wire structs, dependency-ordered functions, unique negative error codes, and high-performance patterns. Triggers on any C code generation, editing, or review request.
---

# ct C Style

High-performance C for Tockchain/Valis firmware on little-endian AVX2 Linux. Correctness over speed, but both matter.

## Core Philosophy

- **Precision first**: Verify before emitting — never guess struct fields or semantics
- **Zero-copy**: Wire structs with pointers directly into memory, named fields
- **No malloc/free**: Stack allocation, arena allocators, or pre-allocated pools only
- **DRY via `static inline` or macros**: Never duplicate logic
- **Functions < 50 lines**: Decompose into orchestrator + helpers
- **O(1) or O(N log N)**: Never O(N²) unless N is tiny and bounded

## Precision Before Speed

**Never guess struct fields, function signatures, or semantics.** If uncertain:

1. **Stop and read** - Use `view` tool to examine the actual header/source
2. **Trace the data flow** - Understand what each field means, not just what it's named
3. **Verify before emitting** - Re-check field names and types against source before responding

### The Semantic Trap

Wrong field name that compiles is worse than syntax error:
- `tx->amount` vs `tx->value` vs `tx->amt` — which exists? what units?
- `hdr->vanid` vs `hdr->rawvanid` vs `hdr->van_id` — which is valid? what's the encoding?
- `node->count` vs `node->numtx` vs `node->n` — what's being counted?

**If you're guessing the field name, you're guessing the semantics.**

### Pre-Emit Checklist

Before writing any code that touches existing structs/functions:
1. Have I actually seen the struct definition? (not assumed it)
2. Do I know the units/encoding of each field I'm using?
3. Have I verified the function signature I'm calling?
4. Could this compile but silently do the wrong thing?

### When Uncertain

Say: "I need to check the actual struct definition before writing this."
Then use tools to read the source. Don't apologize — just verify.

## Types

Use `<stdint.h>` exclusively. Never `char`, `int`, `long`, `size_t` (except API boundaries).

```c
uint8_t *buffer,*ptr;
int32_t count = 0,i,j;
uint64_t timestamp;
```

Pointer style: `type *name` (space after type, `*` with name).

## Naming

| Scope | Convention | Example |
|-------|------------|---------|
| Functions | `snake_case` or `snakecase` | `verify_van`, `get_rawvanid` |
| Types/structs | `snakecase_t` | `van_header_t`, `nodevans_info_t` |
| Globals/macros | `ALL_CAPS` | `MAX_TX_PER_VAN`, `ILLEGAL_VANID` |
| Locals | Short but unambiguous | `vH`, `np`, `numtx` |
| Whitelisted shorts | `U` (utime_data), `H` (header), `A` (active) | — |

## Function Layout

```c
int32_t funcname(type1 arg1,type2 arg2)
{
    type1 local1,local2;
    type2 local3 = init;
    if ( condition != 0 )
        return(-1);
    // body with no blank lines
    return(0);
}
```

Rules:
- All locals declared at top, same-type on same line
- No blank lines inside functions
- Comments inside functions: `//` only, never `/* */`
- `/* */` before function is acceptable for documentation
- `return(value);` — parentheses required
- Single blank line between functions

## Bracing (Compact Allman)

Opening brace on own line, vertically aligned with closing brace.

**Single-statement if/for/while**: No braces, body on next line indented.

```c
if ( x != 0 )
    do_thing();
for (i=0; i<n; i++)
    process(i);
```

**Multi-statement**: Braces required.

```c
if ( x != 0 )
{
    do_thing();
    do_other();
}
```

## Spacing

**Control structures**: `if ( expr )`, `while ( expr )` — spaces inside parens.

**Function calls**: `func(arg1,arg2,arg3)` — no spaces.

**For loops**: `for (i=0; i<n; i++)` — compact inside parens.

**Comparisons**: Always explicit: `if ( ptr != 0 )`, never `if ( ptr )`.

**Math**: Parenthesize all operations: `result = ((x * y) + z);`

**Logical ops**: Single `&&`/`||` no extra parens; multiple requires parens:
```c
if ( x == 0 && y == 0 )           // OK
if ( (x == 0) && (y == 0) && (z == 0) )  // required
```

## Error Handling

Unique negative values per error path — the code itself identifies the line:

```c
int32_t process(data_t *d)
{
    if ( d == 0 )
        return(-1);
    if ( d->len > MAX )
        return(-2);
    if ( validate(d) < 0 )
        return(-3);
    return(0);
}
```

**No goto** except true emergencies. Encapsulate matched open/close:

```c
// BAD: 1 fopen, 3 fclose
fp = fopen(...);
if ( x ) { fclose(fp); return(-1); }
if ( y ) { fclose(fp); return(-2); }
fclose(fp);

// GOOD: encapsulate inner logic
fp = fopen(...);
err = process_file_contents(fp);
fclose(fp);
return(err);
```

## Structs

Wire structs with `#pragma pack(1)` (set globally in `_valis.h`). Use bitfields for flags, not manual bit ops:

```c
typedef struct
{
    uint32_t utime;
    uint16_t numtx;
    uint16_t rawvanid;
    uint8_t is_vip : 1;
    uint8_t lastvan : 1;
    uint8_t coldvan : 1;
    uint8_t reserved : 5;
    uint8_t nodeid;
} van_header_t;
```

Zero-init: `uint8_t zero[32] = {0};`

## File Organization

1. Includes via project-wide header (`_valis.h`, `gen3.h`, etc.)
2. Globals/constants at top
3. Functions in dependency order (callee before caller)
4. No forward declarations unless circular reference

Layering:
- Level 0: Primitives, direct API wrappers
- Level 1: Utilities building on L0
- Level 2: Mid-level abstractions
- Level 3+: Orchestrators, entry points

## Headers

Use `#pragma once`. Never `#ifndef` guards.

Include order in project headers:
1. System headers
2. `#pragma pack(1)`
3. Project types and declarations

## Formatting Summary

- Tabs for indentation, not spaces
- Target 80 chars but single-line requirement wins
- No trailing whitespace
- Every statement on one line (function calls, declarations, control flow)
- Line-based editing friendly (whole line cut/paste safe)

## Anti-Patterns

❌ `size_t` for internal sizes (use `int32_t`, `uint32_t`)
❌ Implicit boolean: `if ( ptr )` → `if ( ptr != 0 )`
❌ Malloc/free in hot paths
❌ Manual bit shifting when bitfields work
❌ Functions > 50 lines
❌ O(N²) algorithms
❌ `#ifndef` header guards
❌ Blank lines inside functions
❌ `/* */` comments inside functions
❌ Guessing struct fields without reading the source

