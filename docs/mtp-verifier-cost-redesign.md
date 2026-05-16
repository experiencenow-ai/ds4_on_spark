# MTP Verifier Cost Redesign

Current measured state: baseline greedy is 14.65 t/s; MTP draft=2 is 2.00 t/s with 21/21 accepted draft tokens, 21 target eval calls, 21 output-head calls, and 0 cache syncs. MTP remains paused because acceptance is not the blocker; exact verifier cost is.

## Why draft=2 still pays target/output-head 21 times

The decode2 verifier accepts at most two draft suffix tokens per MTP cycle. For strict correctness it verifies each accepted draft position against the target model before committing it. Across the latest 32 emitted tokens, that produced 21 accepted draft positions, so the artifact records 21 target eval calls and 21 output-head calls. Cache sync is already not the issue in this run.

## What can be made cheaper

- Exact decode2 cannot skip target evaluation for an accepted position unless the system already has exact target hidden state/logits for that position. Trusting the draft would be a different, non-strict decoder.
- It can verify two accepted tokens in one verifier invocation, but strictness still requires target computation for both accepted draft positions. The win has to come from batching/fusing that work and avoiding extra heads/replays, not from counting acceptance as free target state.
- The current full-accept path no longer reads full row0 logits, but it still recomputes the row0 argmax through an output head and computes row1 logits so generation can continue after the accepted suffix.
- The output-head work is the obvious next target: row0 only needs top1 for verification, while row1 needs continuation logits. These should be emitted by one batched head/top1 operation for the two verifier rows, not two separate output-head command sequences.
- Target evaluation should use the same optimized decode graph/cache path as baseline wherever possible. A verifier target pass that is materially slower per position than baseline decode cannot win even with perfect acceptance.

## Cache state required for strictness

The verifier must preserve the exact checkpoint tokens, raw KV/cache rows, SWA/compressed-cache frontier, and continuation logits for the last committed token. It may stage speculative cache rows, but canonical cache state can only advance after the target verifier proves the accepted prefix. On partial accept or verifier failure it must restore the pre-MTP frontier before replaying or falling back.

## Minimal next code change

Replace the decode2 verifier's two separate output-head calls with a single batched verifier head that returns row0 top1 plus row1 continuation logits, while keeping row0 full logits disabled. The expected artifact change is `output_head_call_count` dropping from 21 to roughly the number of decode2 timing events. The smallest complete speed-path version is the same shape plus baseline decode-graph/cache reuse for the two target positions, so the verifier commits staged KV once and does not carry a separate per-position target replay path.
