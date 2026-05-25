# ds4_on_spark v2

This branch intentionally replaces the old lab/probe tree. It does **not** preserve backward-compatible gateway endpoints, legacy flags, or one-off launch scripts.

The live substrate has five contracts:

1. **ds4-infer** resolves capability requests such as `smartest`, `smart`, `efficient`, or `fastest` into calibrated or pinned model profiles. It owns queueing, immediate requests, shape buckets, and backend selection.
2. **ds4-tools** exposes stable lattice-addressed tools such as `tool:ds4.json.validate` and `tool:repo.tests.echo_contract`. A tool ID is a task location; the registry resolves it to the latest approved implementation.
3. **ds4-agent** runs a bounded model + tool loop. Models may request tools, but only the tool service executes approved implementations.
4. **ds4-calibrate** produces profile calibration plans so runtime batch sizes, output budgets, and chat/completion choices are measured inside the service layer instead of leaking into Centaur.
5. **ds4-transfer** plans and runs direct Spark-to-Spark file transfers over the 200Gbps fabric without hairpinning payloads through the controller.

The main repository's Git history is the archive. Obsolete scripts are purged from live main instead of carried forward behind compatibility shims.

## Quick checks

```bash
python3 -m compileall -q src tests
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Capability routing

Use capability descriptors when any calibrated model is acceptable:

```json
{"capability":"efficient","job_class":"atom_edit","chat":false}
```

Use `model_pin.profile_id` when reproducibility matters.

Initial default intent:

- `smartest`: best-quality DSV4 profile, explicit thinking/output budget expected.
- `smart`: performant DSV4 profile, with antirez/vLLM selected by calibration and chat flag.
- `efficient`: `Qwen/Qwen3.6-27B-FP8`, currently the default local mechanical-work profile from the 76/92 DS4-eval result.
- `fastest`: smaller qualified local model for summaries, triage, and JSON repair; current placeholder profiles must be calibrated before becoming defaults.

## Static Spark topology

The production Spark allocation is fixed in `profiles/topology/static_sparks.json`:

- spark0-3 host resident Qwen lanes;
- spark4+spark5 jointly host one DSV4 vLLM/MTP lane because that profile consumes both Sparks;
- spark6 is antirez/support only, with no Qwen resident profiles;
- spark7 is the only dynamic experiment lane.

This keeps Centaur-facing requests capability-based instead of Spark/backend-specific. See `docs/static-spark-topology.md`.

Production Sparks should run `ds4-infer startup-models` after reboot. The
command warms only the resident profiles assigned to that Spark by topology;
spark7 stays on demand.

## Inference queue

Centaur submits individual requests and can poll either a request, a batch, or an event stream:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-submit \
  --queue-dir /tmp/ds4_queue \
  --profiles-dir profiles/models \
  --topology profiles/topology/static_sparks.json \
  --requests requests.jsonl \
  --batch-id centaur-run-001

PYTHONPATH=src python3 -m ds4_infer.cli queue-work \
  --queue-dir /tmp/ds4_queue \
  --profiles-dir profiles/models \
  --runner spark \
  --node-id spark0 \
  --limit 16

PYTHONPATH=src python3 -m ds4_infer.cli queue-poll \
  --queue-dir /tmp/ds4_queue \
  --after-event-id 0
```

The queue internally groups requests by model/profile, Spark node, chat mode, job class, input/output/thinking buckets, and shared prefix hash. Centaur does not need to know batch-size folklore.

For Centaur lattice and LongMem batches, workers can prewarm vLLM Automatic
Prefix Caching for repeated skeletons:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-work \
  --queue-dir /tmp/ds4_queue \
  --profiles-dir profiles/models \
  --runner spark \
  --node-id spark0 \
  --warm-prefixes \
  --limit 128
```

This is best-effort cache warming, not raw KV export/import: DS4 sends one tiny
request per shared-prefix group on the same resident lane, then processes the
real requests with byte-identical `shared_prefix` text.

`--runner spark` executes the model request on the selected Spark over SSH,
using that Spark's local `http://127.0.0.1:8000` unified/OpenAI-compatible API.
It tries `/ds4/batches` first and falls back to `/v1/chat/completions` or
`/v1/completions` when only vLLM is exposed.

SparkRunner-compatible batches now use the queue path:

```bash
v2/scripts/sparkrunner_queue_adapter.sh \
  --input requests.jsonl \
  --output responses.jsonl \
  --model ds4v
```

For direct Centaur diamond queue integration, use
`--response-format inference` to write raw `ds4-inference-result-v1` JSONL
instead of the SparkRunner response contract.

## Tool lattice

Tools are invoked by stable IDs, not rediscovered shell commands:

```text
tool:ds4.json.validate
tool:ds4.sha256
tool:ds4.regex.match
tool:ds4.diff.stats
tool:ds4.cpu.services
tool:ds4.cpu.batch
tool:repo.tests.echo_contract
tool:web.fetch
tool:spark.status
tool:spark7.command.run
tool:spark.transfer.plan
tool:spark.transfer.run
```

Bash-backed tools use fixed argv, schema validation, timeouts, output caps, and no `shell=True`. CPU service batches use a bounded process-wide pool; allowlisted commands come only from `CPU_SERVICE_COMMANDS_JSON`.

## Spark transfer

Plan a direct Spark-to-Spark transfer:

```bash
PYTHONPATH=src python3 -m ds4_transfer.cli plan \
  --topology profiles/transfer/spark_200g.json \
  --request-json '{"format":"ds4-transfer-request-v1","source_node":"spark0","source_path":"/mnt/data/batch/","destination_node":"spark4","destination_path":"/mnt/data/batch/"}'
```

The generated command SSHes into the source Spark and runs rsync from source to destination, so data flows over the Spark fabric rather than through the controller.

## No local forge layer

A separate local GitHub/Forgejo layer is not part of v2. Merged PRs in the main repository already provide full Git history. Centaur can deterministically map source commits and PR diffs to atom/lattice changes.

## Live runners, web tools, and Spark chat

Live runner adapters now exist for OpenAI-compatible vLLM, vLLM/MTP, and antirez-style completion endpoints. See `docs/llm-runners.md`.

`tool:web.fetch` provides rendered-page access through Playwright when installed, with a plain HTML fallback for simple pages. See `docs/web-tools.md`.

`ds4-spark-chat -m ds4v` is a simple Mac Studio-friendly chat CLI that keeps
full history locally but runs inference on the selected Spark. See
`docs/spark-chat.md` and `docs/spark-queue-runbook.md`.

Gateway, transfer, and audit extraction notes live in
`docs/model-gateway-operational-notes.md`, `docs/spark-transfer.md`, and
`docs/audit-handoff.md`.
