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

Use explicit Spark fabric hosts and users:

```bash
ssh spark0 'mkdir -p /home/spark0/ds4_logs/waterfall; \
  cd ~/src/ds4_on_spark; \
  nohup python3 scripts/ds4_waterfall_stage_model.py \
    --source-full-dir /home/spark0/ds4_nvme/models/hf/lukealonso/GLM-5.2-NVFP4 \
    --repo-id lukealonso/GLM-5.2-NVFP4 \
    --ssh-host-template "{node}@{node}-200g" \
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

## Pitfalls

- Do not confuse `/mnt/mac/22tb0` with spark0 external NVMe.
- Do not wait for all shards to finish before beginning archive or waterfall
  transfer.
- Do not copy `.part` files.
- Do not use plain `{node}` for worker-to-worker transfer when the sender user
  differs from the target user. Use `{node}@{node}-200g`.
- Do not use `&& ... & echo $!` for background launchers; it can background the
  whole shell list and leave SSH sessions hanging. Use semicolons and redirect
  stdin from `/dev/null`.
- Do not use `rsync -aH` to the Mac SMB mount. Use
  `-rt --omit-dir-times --no-perms --no-owner --no-group`.
