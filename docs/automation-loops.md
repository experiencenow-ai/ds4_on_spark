# Automation Loops

Each loop should run in roughly 30 minutes and leave a short status note:
what changed, what was measured, what blocked, and the next command.

All loops must follow `docs/automation-github-protocol.md`.

## Loop 1: Spark Access

Goal: make `ssh spark0@aitopatom-9ab9.local` passwordless from the Mac.

Tasks:

- Verify hostname resolution and port 22 reachability.
- Install the Mac public key into `spark0` once account auth works.
- Add a stable wired IPv4 route or alias if needed.
- Run `scripts/spark_probe.sh`.

Exit: passwordless SSH works and probe output exists.

## Loop 2: Hardware Baseline

Goal: capture reproducible Spark hardware metadata.

Tasks:

- Run CUDA, driver, clock, power, memory, and network checks.
- Record thermal/power behavior while idle and under a small CUDA workload.
- Identify exact CUDA compute capability reported by the device.

Exit: committed redacted hardware report.

## Loop 3: Upstream Intake

Goal: collect references without committing huge vendored trees.

Tasks:

- Record exact upstream commits for `antirez/ds4`, DeepGEMM, DeepSeek HF code,
  and Spark llama.cpp experiments.
- Create scripts or docs for fetching each source.
- Note license constraints.

Exit: upstream manifest and fetch commands.

## Loop 4: Model Contract

Goal: define the actual V4 Flash execution contract.

Tasks:

- Extract config JSON and tensor metadata.
- Document layer types, MoE schedule, cache layer types, tokenizer/encoding.
- Generate small oracle prompts and expected logits from official code.

Exit: initial `docs/model-contract.md` and fixture plan.

## Loop 5: Existing Baseline

Goal: get any DS4 Flash runtime producing tokens on Spark, with a quantized
single-Spark run as the first execution milestone.

Tasks:

- Run known llama.cpp/antirez path if available.
- Try a V4-capable external runtime with the smallest credible quantized V4
  Flash artifact on Spark0 before attempting native DS4 or dual-Spark work.
- If the runtime can expose hooks, collect per-token latency, routing traces,
  expert batch sizes, and MTP accept/reject counters for the quantized
  high-performance path.
- Capture command line, context, quant, t/s, TTFT, memory use.
- Record failures exactly.

Exit: one baseline report, even if performance is poor, plus one quantized
single-Spark success or exact failure report.

## Loop 6: DeepGEMM Spike

Goal: determine whether DeepGEMM is usable on GB10.

Tasks:

- Build/import DeepGEMM.
- Run the smallest FP8/FP4 and Mega MoE tests that match DS4 shapes.
- Record compile errors, unsupported arch errors, or measured throughput.

Exit: compatibility matrix with go/no-go recommendation.

## Loop 7: Repo Skeleton

Goal: create the buildable C/CUDA project shell.

Tasks:

- Add CMake/Make wrapper.
- Add config, logging, static allocator, CUDA error wrappers.
- Add placeholder unit tests and CI-friendly CPU-only checks.

Exit: local build/test command succeeds on Mac where possible.

## Loop 8: Scheduler Model

Goal: build and test scheduler logic before CUDA integration, using real
quantized-runtime traces as soon as they exist.

Tasks:

- Implement host-only scheduler simulation.
- Feed synthetic expert routing traces.
- Replay quantized-runtime routing traces when the baseline loop can collect
  them.
- Model expert queueing and MTP accept/reject behavior before patching runtime
  code.
- Measure queue fill, starvation, K selection, and oscillation.

Exit: scheduler simulator with tests, replayable route traces, and quantified
expert-queue/MTP recommendations.
