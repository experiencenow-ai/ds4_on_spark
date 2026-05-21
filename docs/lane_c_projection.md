# Lane C PP=3 K Projection

Source run: `fixtures/pipeline_one_prompt/lane_a2_64tok_spark234_pp3_20260521T0200Z.stdout`.
Comparator run: `fixtures/standard_runtime_benchmarks/vllm_deepseek_v4_flash_tp2_no_mtp_spark45_batch_sweep_20260521.example.json`.

The Lane A2 B=1 PP=3 run records exact steady decode throughput
`steady_tok_s_excluding_step0 = 0.7765547550855313` in the JSON payload
(`line 96`) and the full per-step `stage_elapsed_ms` vectors in both the JSON
steps and the summary list (`line 2771`). The comparison target for this paper
check is vLLM PP=2 at concurrency 64: `310.31684000791483 tok/s`
(`line 56`), usually rounded to `310 tok/s`.

## Formula

For a saturated PP=3 row-replacement run, the optimistic steady aggregate rate
is bounded by the slowest stage service time:

```text
bottleneck_stage_ms = max(mean(stage_elapsed_ms[1:][stage_id]))
projected_tok_s(K) = K * 1000 / bottleneck_stage_ms
minimum_K_to_beat_target = floor(target_tok_s * bottleneck_stage_ms / 1000) + 1
```

Step 0 is excluded because it includes first-token prefill/warmup behavior. The
`+ 1` is intentional: Lane C must beat the c=64 vLLM comparator, not merely tie
it.

## Result

Using steps 1..63:

```text
stage0 mean = 1988.8237936507937 ms
stage1 mean = 1936.0844920634920 ms
stage2 mean = 1933.0659047619047 ms
bottleneck = stage0 = 1988.8237936507937 ms
bottleneck row rate = 1000 / 1988.8237936507937 = 0.5028097527757074 tok/s
minimum K = floor(310.31684000791483 * 1988.8237936507937 / 1000) + 1 = 618
```

The naive linear projection from the measured B=1 steady rate is less strict:

```text
floor(310 / 0.7765547550855313) + 1 = 400
```

The stage-vector projection is the number Lane C should treat as the early doom
check because it is tied to the PP=3 service bottleneck. At the currently
natural `K=512`, the same model gives only:

```text
512 * 1000 / 1988.8237936507937 = 257.4385934211622 tok/s
```

So the paper projection says current PP=3 row replacement needs `K=618` to beat
the exact `310.31684000791483 tok/s` vLLM PP=2 c=64 comparator. If the runtime
is capped at `K<=512` without reducing per-stage service time, Lane C cannot
make the economic case.
