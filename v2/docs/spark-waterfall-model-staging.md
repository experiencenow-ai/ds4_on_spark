# Spark Waterfall Model Staging

This is the canonical workflow for getting a large sharded HF model onto the
Spark ring while an active download is still running.

## Storage Policy

- The full active archive lives on spark0 external NVMe, for example
  `/home/spark0/ds4_nvme/models/hf/lukealonso/GLM-5.2-NVFP4`.
- The Mac `22tb0` disk is an inactive archive mirror, for example
  `/mnt/mac/22tb0/models/hf/lukealonso/GLM-5.2-NVFP4`.
- The normal runtime directory on every Spark node is stage-local:
  `/home/{node}/models/hf/<org>/<model>`.
- spark0 must also have only its rank0 runtime view in
  `/home/spark0/models/hf/<org>/<model>`. The complete archive must not live on
  spark0 internal NVMe.
- Do not copy the complete model to every Spark node.

## Overlap Rule

Do not wait for the full HF download before doing useful work.

As soon as `model.safetensors.index.json` is present, completed files can move:

- rolling mirror to Mac `22tb0`;
- waterfall staging across the Spark ring;
- local rank0 staging on spark0.

The one hard rule is never copy `*.part` files. A completed file can be copied
as soon as it is visible with its final filename.

If HF has not downloaded the index yet, fetch it directly:

```bash
ssh spark0 'cd /home/spark0/ds4_nvme/models/hf/lukealonso/GLM-5.2-NVFP4 && \
  curl -L -f --retry 5 \
    -o model.safetensors.index.json.direct \
    https://huggingface.co/lukealonso/GLM-5.2-NVFP4/resolve/main/model.safetensors.index.json && \
  python3 -m json.tool model.safetensors.index.json.direct >/dev/null && \
  mv -f model.safetensors.index.json.direct model.safetensors.index.json'
```

## Rolling Mac Archive

Use SMB-safe rsync flags. The Mac share should not receive owner, group, mode,
or directory timestamp updates.

```bash
ssh spark0 'mkdir -p /mnt/mac/22tb0/models/hf/lukealonso/GLM-5.2-NVFP4 && \
  while pgrep -f "hf download lukealonso/GLM-5.2-NVFP4" >/dev/null; do \
    rsync -rt --omit-dir-times --no-perms --no-owner --no-group \
      --info=progress2 --exclude "*.part" \
      /home/spark0/ds4_nvme/models/hf/lukealonso/GLM-5.2-NVFP4/ \
      /mnt/mac/22tb0/models/hf/lukealonso/GLM-5.2-NVFP4/; \
    sleep 120; \
  done; \
  rsync -rt --omit-dir-times --no-perms --no-owner --no-group \
    --info=progress2 --exclude "*.part" \
    /home/spark0/ds4_nvme/models/hf/lukealonso/GLM-5.2-NVFP4/ \
    /mnt/mac/22tb0/models/hf/lukealonso/GLM-5.2-NVFP4/'
```

## Streaming Waterfall

Use `scripts/ds4_waterfall_stage_model.py --watch-source`.

The waterfall is per completed file:

1. spark0 installs files needed by rank0 into its runtime directory.
2. spark0 sends files needed by later ranks to spark1.
3. Each Spark installs files needed by its own rank.
4. Each Spark immediately forwards files needed by later ranks to the next
   Spark.
5. The set of files shrinks at every hop.

Spark-to-Spark payload bytes must use the repo fast transfer module
(`ds4_transfer.fast_copy` / `parallel_nc_fanout_200g_v1`). The script defaults
to `--transfer-mode fast-copy`, which launches striped unencrypted `nc` streams
on the static 200G fabric for each adjacent hop. Use `--transfer-mode rsync`
only as an emergency/debug fallback.

Use explicit Spark fabric hosts and users:

```bash
ssh spark0 'mkdir -p /home/spark0/ds4_logs/waterfall; \
  cd ~/src/ds4_on_spark; \
  nohup python3 scripts/ds4_waterfall_stage_model.py \
    --source-full-dir /home/spark0/ds4_nvme/models/hf/lukealonso/GLM-5.2-NVFP4 \
    --repo-id lukealonso/GLM-5.2-NVFP4 \
    --ssh-host-template "{node}@{node}-200g" \
    --transfer-mode fast-copy \
    --replace-existing \
    --execute \
    --watch-source \
    < /dev/null \
    > /home/spark0/ds4_logs/waterfall/glm52_nvfp4_waterfall_streaming.log \
    2>&1 & echo $!'
```

## Monitoring

```bash
ssh spark0 'pgrep -af "hf download .*GLM-5.2-NVFP4" || true'
ssh spark0 'tail -n 50 /home/spark0/ds4_logs/waterfall/glm52_nvfp4_waterfall_streaming.log'
ssh spark0 'log=$(ls -t /home/spark0/ds4_logs/downloads/glm52_nvfp4_archive_to_22tb0_rolling_*.log 2>/dev/null | head -1); [ -n "$log" ] && tail -n 50 "$log"'
ssh spark0 'du -sh /home/spark0/ds4_nvme/models/hf/lukealonso/GLM-5.2-NVFP4 /mnt/mac/22tb0/models/hf/lukealonso/GLM-5.2-NVFP4'
```

Check worker coverage:

```bash
for n in spark1 spark2 spark3 spark4 spark5 spark6 spark7 spark8 spark9 sparka sparkb sparkc; do
  printf '%s ' "$n"
  ssh -o BatchMode=yes -o ConnectTimeout=4 "$n" \
    'ps -eo args= | grep "ds4_waterfall_stage_model.py --worker" | grep -v grep | wc -l'
done
```

## Launch Isolation Notes

Do not confuse model staging with model quality. A successful waterfall means
the full archive is on spark0 external NVMe and each Spark internal NVMe has
only the files needed by that pipeline rank. The next checks are vLLM load,
`/v1/models`, first-forward, and output sanity.

For GLM-5.2-NVFP4 on the Spark SM120/SM121 GPUs, FlashInfer XQA MLA requires
FP8 KV cache. The BF16-KV path can finish loading but fail on first forward
with:

```text
XQA MLA only supports fp8 operation on SM120/SM121 GPUs
```

This still uses FP4 weights. `--kv-cache-dtype fp8_e4m3` is the KV-cache dtype,
not a return to the FP8 model.

Use lifecycle overrides to isolate launch behavior without hand-editing
generated scripts. For example, removing the generated KV-transfer connector is
the supported no-LMCache canary path:

```bash
PYTHONPATH=src python3 scripts/ds4_pipeline_lifecycle.py launch \
  --topology profiles/topology/static_sparks_glm52_nvfp4_pp13.json \
  --service glm52_nvfp4_pp13 \
  --execute --stagger-s 3 --probe-timeout-s 900 \
  --remote-env VLLM_USE_FLASHINFER_MOE_FP4=0 \
  --remote-remove-arg=--kv-transfer-config \
  --remote-set-arg-kv=--attention-backend=FLASHINFER_MLA_SPARSE \
  --remote-set-arg-kv=--kv-cache-dtype=fp8_e4m3 \
  --remote-set-arg-kv=--linear-backend=cutlass \
  --remote-set-arg-kv=--moe-backend=cutlass \
  --remote-set-arg-kv=--max-num-seqs=1 \
  --remote-set-arg-kv=--max-num-batched-tokens=4096 \
  --remote-arg=--no-enable-flashinfer-autotune
```

Live evidence from the 2026-06-22 canary: all 13 ranks loaded and `/v1/models`
served `glm-5.2-nvfp4-pp13`; a one-token completion executed through the ring.
The output was not coherent, and the logs warned that FP8 KV scaling fell back
to `1.0`, so treat bad text here as a backend/KV-scale investigation, not a
waterfall-staging failure.

## Pitfalls

- Do not confuse `/mnt/mac/22tb0` with spark0 external NVMe.
- Do not wait for all shards to finish before beginning archive or waterfall
  transfer.
- Do not copy `.part` files.
- Do not use Spark-to-Spark `rsync` for normal waterfall staging. It is
  encrypted, single-file-at-a-time, and far slower than the 200G fast-copy path.
- Do not use plain `{node}` for worker-to-worker transfer when the sender user
  differs from the target user. Use `{node}@{node}-200g`.
- Do not use `&& ... & echo $!` for background launchers; it can background the
  whole shell list and leave SSH sessions hanging. Use semicolons and redirect
  stdin from `/dev/null`.
- Do not use `rsync -aH` to the Mac SMB mount. Use
  `-rt --omit-dir-times --no-perms --no-owner --no-group`.
