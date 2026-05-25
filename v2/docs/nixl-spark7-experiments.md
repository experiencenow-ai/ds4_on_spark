# Spark7 NIXL experiment plan

Spark7 is the only lane that should load/unload experimental vLLM builds. Production lanes remain fixed:

- spark0-3: Qwen resident lanes
- spark4+spark5: DSV4 vLLM/MTP grouped lane
- spark6: antirez/support lane
- spark7: experimental lane

## Why this exists

The current packaged vLLM runtime can have NIXL installed correctly and still fail for Qwen GDN models. The useful test is not another package-install check; it is a vLLM build check against a revision containing GDN NIXL support.

The tracked upstream change is vLLM PR
[#41869](https://github.com/vllm-project/vllm/pull/41869), which merged GDN
conv-state layout support for NIXL KV transfer on May 14, 2026 and tested
`Qwen/Qwen3.5-0.8B` with `VLLM_SSM_CONV_STATE_LAYOUT=DS`,
`--trust-remote-code`, `--no-disable-hybrid-kv-cache-manager`, and
`--no-async-scheduling`.

The first target is the small GDN smoke profile:

```text
profiles/nixl/qwen35_0_8b_spark7_gdn_nixl_smoke.json
```

Only after that passes should xhigh try the heavy Qwen27 profile:

```text
profiles/nixl/qwen27_spark7_gdn_nixl_experimental.json
```

DSV4 NIXL remains important, but it needs spark4+spark5 and should be tested when those lanes are free.

## Generate spark7 scripts

```bash
PYTHONPATH=v2/src python3 -m ds4_nixl.cli write-spark7-experiment \
  --deployment v2/profiles/nixl/qwen35_0_8b_spark7_gdn_nixl_smoke.json \
  --vllm-build v2/profiles/vllm_builds/vllm_main_after_gdn_nixl_41869.json \
  --output-dir /tmp/ds4_nixl_gdn_smoke
```

Run on spark7:

```bash
cd /tmp/ds4_nixl_gdn_smoke
./00_install_experimental_vllm.sh
source /home/spark7/standard-runtimes/vllm-main-gdn-nixl/venv/bin/activate
./start_prefiller.sh > prefiller.log 2>&1 &
./start_decoder.sh > decoder.log 2>&1 &
./start_proxy.sh > proxy.log 2>&1 &
./04_smoke_request.sh
```

Stop:

```bash
./05_stop_experiment.sh
```

## Heavy Qwen27 follow-up

Only after the small smoke passes:

```bash
PYTHONPATH=v2/src python3 -m ds4_nixl.cli write-spark7-experiment \
  --deployment v2/profiles/nixl/qwen27_spark7_gdn_nixl_experimental.json \
  --vllm-build v2/profiles/vllm_builds/vllm_main_after_gdn_nixl_41869.json \
  --output-dir /tmp/ds4_nixl_qwen27
```

The heavy profile may not fit two Qwen27 vLLM instances on one Spark. If it does not fit, that is still useful: the GDN smoke tells us whether the vLLM build is correct, and the heavy Qwen27 P/D deployment can then move to an available two-Spark experimental window.

## DSV4 analysis

The compatibility matrix says MLA/DeepSeek-style models have Basic PD support with NIXL, but speculative decode requires matching configuration between prefiller and decoder. Treat MTP as a second test after no-MTP DSV4 NIXL works.

Recommended sequence for spark4+spark5 tomorrow:

1. DSV4 NIXL, no MTP, `kv_load_failure_policy=fail`.
2. Long shared-prefix TTFT comparison against non-NIXL.
3. DSV4 NIXL + MTP only after the no-MTP baseline passes.
