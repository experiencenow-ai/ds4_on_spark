# DS4 v2 architecture

Centaur should call DS4 by service contract, not by runtime-specific flags.

```text
Centaur
  -> ds4-infer: inference by capability or pinned model profile
  -> ds4-tools: stable lattice tool IDs, versioned executors
  -> ds4-agent: bounded model/tool loop
  -> ds4-calibrate: measured profile promotion inputs
```

## Tool lattice

Tools are stable task addresses. A tool ID stays stable while its implementation may change after review. Invocation records include the exact tool implementation record, arguments, duration, and result.

The LLM should search, describe, and invoke tool atoms. It should not rediscover shell commands or flags.

## Bash executor

Bash is allowed only through registered tool atoms with fixed argv, JSON input, no `shell=True`, timeouts, and output caps. This keeps bash useful without turning it into arbitrary remote execution.
