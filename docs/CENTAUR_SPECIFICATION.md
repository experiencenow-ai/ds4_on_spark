# Centaur specification

> Status: **first complete draft, 2026-05-21T17:30Z.** Authored from accumulated conversation context plus the original C-compiler vision the founder articulated. Subject to revision by the founder; modules and acceptance criteria below are proposals, not final.
>
> Read this with `docs/CENTAUR_DASHBOARD.md` (live progress per component) and `.github/LANES.md` (work coordination protocol).

## 1. Vision in one paragraph

Centaur is a **general state-machine factory**. Given any problem domain that admits an objective metric function, Centaur evolves a population of candidate state machines (hybrid workflows of deterministic operations and LLM calls) and promotes the most cost-efficient candidate that meets the domain's quality bar. The end product is not "an AI that solves your problem" but "a *machine* that builds machines that solve problems." Once a winning state machine for a domain is promoted, it is a deterministic, replayable, debuggable artifact — not a language model output — and it costs orders of magnitude less to run than a frontier LLM call because its internal nodes were strength-reduced during evolution to the cheapest sufficient provider per step.

## 2. The Crenshaw forcing function

The proof-test for the general system is **Jack Crenshaw's *Let's Build a Compiler* curriculum**. The 16 lessons compose a complete, well-scoped, incrementally-deepening domain with crisp metrics at every level.

| Lesson | Capability | Metric inputs |
|---:|---|---|
| 1 | Single-digit arithmetic expressions → assembly | Correctness on N test expressions; output assembly executes and produces correct results; generated code size; compile wall time; LLM cost |
| 2 | Multi-digit numbers, named variables, multiplication / division | Same shape |
| 3 | Control structures (if/else, while, do/until) | Same |
| 4 | Boolean expressions, relational operators | Same |
| 5 | Lexical scanning (tokenizer) | Same |
| 6 | Parsing as a separate phase (AST) | Same |
| 7 | Calls and procedures | Same |
| 8 | Top-down expression parsing — full operator precedence | Same |
| 9 | Types — char, int, long, signed/unsigned | Same |
| 10 | Pointers and arrays | Same |
| 11 | Multi-character identifiers, full lexer | Same |
| 12 | Miscellany — preprocessor, comments | Same |
| 13 | Procedure parameters, locals, recursion | Same |
| 14 | Structures and unions | Same |
| 15 | Back to the future — code generation refinements | Same |
| 16 | Unit construction — multi-file compilation, linking | Same |

After lesson 16 (or earlier — see §10 on emergent generalization), Centaur should hold one or more state machines that, given any C source program in a defined subset, emit working assembly. The proof that the **system itself** is general is then: take a different domain (say, "write a profiler that pinpoints hotspots given a recorded execution trace") and Centaur produces a winning state machine for that too, without re-engineering the factory.

The user has explicitly named compiler construction as the proof because solving it implies solving most coding tasks (the holes being multi-threaded concurrency, systems-level bugs). Adding a debugging domain on top covers those holes.

## 3. End-state walkthrough

A founder-tier user, three months from now, has this experience:

```
$ centaur domain submit crenshaw-lesson-3-control-flow.yaml
domain registered: crenshaw-03-ctrl
metrics: correctness (0..1 by passing test ratio), code_size (asm bytes, lower better),
         compile_wall_ms (lower better), llm_cost_cents (lower better)
inheritance: parent domain crenshaw-02-vars, 1 promoted SM available as seed
test set: 84 test cases, gold outputs committed

$ centaur evolve crenshaw-03-ctrl --budget 250.00 --generations 12 --population 24
generation 1/12: 24 candidates spawned (3 from seed mutation, 21 from library)
  evaluating: ████████████████████████ 24/24 (live providers used: 7)
  scores: best 0.71 / cost-weighted 0.62 / mean 0.34
generation 2/12: 24 candidates (12 mutations of top-8, 6 new template seeds, 6 crossovers)
  evaluating: ████████████████████████ 24/24
  scores: best 0.84 / cost-weighted 0.81 / mean 0.51
...
generation 9/12: convergence detected (Δscore < 0.005 for 3 gens)
  promoting: candidate sm_3_g9_c11 (correctness 1.00, code_size 0.87, cost $0.03/test)
  emitting run bundle: bundles/crenshaw-03-ctrl/sm_3_g9_c11.bundle
  $ centaur replay bundles/crenshaw-03-ctrl/sm_3_g9_c11.bundle test_42
    [executes deterministically, no live providers, exact reproduction]
  memory deposited: 14 facts about effective node compositions for control-flow lowering

$ centaur evolve crenshaw-04-bool --seed-from crenshaw-03-ctrl
[parent SM and memory carries forward; faster convergence expected]
```

The user does not edit prompts. The user does not pick models. The user **does not write the state machine.** The user submits a domain specification and a budget; Centaur returns a state machine that meets the bar within budget or reports honestly that it cannot.

## 4. The four-component decomposition (cross-referencing the existing vision)

Centaur's vision document names four workstream components. This spec keeps that decomposition and details the modules within each.

```
Component 1 — State-machine factory core
    Modules 3-6, 8-10, 12, 14, 15

Component 2 — Memory / Trimind / LongMem domain
    Module 11 (+ Trimind subsystem in trimind-brain repo)

Component 3 — Provider + model portfolio
    Module 7

Component 4 — Product API / UI / debug / release
    Module 13

Cross-cutting:
    Module 1 (domain definition) lives wherever the domain author lives
    Module 2 (node library) is the shared substrate
```

## 5. Module-by-module specification

### Module 1 — Domain definition

**Purpose.** Specifies what "solving this problem" means in objective, runnable terms.

**Schema.** A domain is a directory in `domains/<name>/` containing:

| File | Purpose |
|---|---|
| `domain.yaml` | Name, description, parent domain, accepted I/O schemas, budget hints |
| `test_cases.jsonl` | One line per test case: input, expected output (or expected-property), gold metadata |
| `metric_functions/` | Python modules implementing the metric callables (correctness, performance, quality, cost, custom) |
| `seed_machines/` | Optional starter state machines provided by a human |
| `harness.py` | Domain-specific glue: how to feed a candidate state machine an input, how to capture its output, how to invoke the metrics |

**Acceptance for a Module 1 implementation.** `centaur domain submit <path>` validates the directory, runs all metric functions against the seed machines on a smoke subset of test cases, and either rejects with a specific schema/runtime error or registers the domain in the active set.

**Status today.** Not built. The `centaur_state_machine_factory.py` module has placeholder hooks; there is no `centaur domain submit` command. **Priority: P0** to ship before Crenshaw lesson 1 can be attempted.

---

### Module 2 — Node library (the substrate)

**Purpose.** The set of typed, composable primitive operations from which state machines are built. Both deterministic ops and LLM-call shapes are nodes.

**Node taxonomy.** Each node has a type signature `(inputs, outputs, side_effects, cost_model)`.

| Category | Examples |
|---|---|
| Parsing | PEG parser, recursive-descent parser, regex tokenizer, GLR parser, error-recovery wrapper |
| AST manipulation | Walker, rewriter, scope analyzer, type inferer, constant folder, dead-code eliminator |
| Code emission | Template emitter, assembly formatter, basic-block scheduler, register allocator (simple/graph-color), peephole optimizer |
| LLM calls | "Explain this AST", "Suggest optimization for this block", "Diagnose this failure", "Synthesize missing case", "Refactor this code" — each with a slot for the model-router decision |
| Validation | Syntax check, type check, semantic equivalence check, fuzz tester, property tester |
| Memory | Store-fact, retrieve-fact, embed-and-search (Trimind plumbing), retrieve-similar-past-solution |
| Tool/execution | Compile-and-run, profile-execution, diff-outputs, measure-binary-size, measure-asm-quality |
| Control flow | If, while, foreach, fork-and-join, race, retry-with-backoff |

**Acceptance for a Module 2 implementation.** A new node can be added with: a Python class implementing a stable interface, a type signature, a cost model (declared dollar/token/wall-time cost as a function of inputs), and zero or more unit tests. The factory's mutator must be able to discover the new node from a registry and consider it as a candidate insertion point.

**Status today.** Partially exists as the procedure registry (`.centaur/procedure_registry.json`) plus the 14 `tool-*` CLI commands. Typed signatures are not enforced; cost models are not declared. **Priority: P0** alongside Module 1.

---

### Module 3 — State-machine representation

**Purpose.** The canonical data structure that a "candidate" is.

**Representation.** A state machine is a directed graph in JSON-serializable form:

```json
{
  "id": "sm_3_g9_c11",
  "domain": "crenshaw-03-ctrl",
  "parent_id": "sm_3_g8_c4",
  "mutation_history": ["seed_template_recursive_descent", "swap_emitter_3", "splice_validator_2"],
  "nodes": [
    {"id": "n0", "kind": "tokenize_with_regex", "config": {...}},
    {"id": "n1", "kind": "parse_recursive_descent", "config": {"grammar_ref": "g_v3"}},
    {"id": "n2", "kind": "llm_call",
        "config": {
            "role": "ast_optimizer",
            "tier_required": "local_small_or_better",
            "prompt_template": "tmpl_v7",
            "temperature": 0.0
        }},
    {"id": "n3", "kind": "emit_assembly_template", "config": {"target": "68k"}}
  ],
  "edges": [
    {"from": "input", "to": "n0"},
    {"from": "n0", "to": "n1"},
    {"from": "n1", "to": "n2"},
    {"from": "n2", "to": "n3"},
    {"from": "n3", "to": "output"}
  ],
  "kv_slots": [],
  "metadata": {"score": 0.96, "cost_per_test": 0.027, ...}
}
```

**Acceptance.** A state machine can be (a) serialized round-trip without information loss, (b) topologically sorted and validated for input/output type compatibility at every edge, (c) re-executed deterministically given the same inputs *if* all LLM calls were recorded in a bundle.

**Status today.** Sketch exists in centaur. No type-validated graph; no canonical JSON schema; no round-trip serialization test.

---

### Module 4 — Candidate generator

**Purpose.** Produce initial candidate state machines for a domain when the population is empty or seeds are insufficient.

**Generation strategies.**

1. **From templates** — known-good architectures registered as starting points (e.g., "lex → parse → emit", "recursive-descent + LLM-as-codegen", "parse + LLM-as-optimizer + emit"). Each template instantiates with the domain's I/O types.
2. **From parent domain seed** — if the domain declares a parent, the parent's promoted state machine is the dominant seed (with mutations).
3. **From the library by random walk** — pick a node compatible with `input_type → ?`, pick the next compatible with `? → ?`, until reaching `? → output_type`. Constrained by max-depth and budget.
4. **From human-supplied seed** — if the domain author committed seed machines in `seed_machines/`, they enter the initial population.

**Acceptance.** Given a domain with type signature `input → output`, generator produces N valid state machines (type-correct, terminating, within budget envelope) in O(N) time. At least one is non-trivial (depth ≥ 3 nodes); diversity is enforced by a structural similarity threshold.

**Status today.** Not built.

---

### Module 5 — Mutator

**Purpose.** Given a state machine, produce a slightly different one. Drives evolution.

**Mutation operators.**

- **Swap-node**: replace one node with another from the library that has the same type signature.
- **Insert-node**: at an edge `A → B`, insert a node `N` such that `A → N → B` is type-correct.
- **Delete-node**: remove a node whose input and output types are compatible (effectively short-circuiting).
- **Reparameterize**: change one node's config (prompt template, temperature, model tier requirement, etc.) without changing structure.
- **Splice**: take a sub-path from another candidate (especially a recent winner from a sibling domain) and graft into this one.
- **Promote-validator**: take a node currently running as a validator and elevate it to a generator (or vice versa).
- **Strength-reduce**: replace an LLM node with a deterministic-op subgraph that approximates its behavior (when one exists in the library).
- **Strength-raise**: replace a deterministic node that's failing to meet quality with an LLM call (with cost-budget governor).

**Mutation selection.** The mutator itself has a small policy: which mutation operator to apply given the candidate's recent fitness signal. Initially uniform; can become learned.

**Acceptance.** A mutator call against a valid SM produces (a) a different but valid SM, (b) a non-degenerate change (not "delete then re-add the same node"), (c) within a configured "mutation distance" so changes are incremental.

**Status today.** Not built. The 18 `state-*` CLI subcommands hint at state-machine factory infrastructure but none implement mutation.

---

### Module 6 — Executor / runtime

**Purpose.** Run a state machine on a problem instance and produce an output plus a complete execution trace.

**Execution semantics.**

- Topological-sort the graph.
- For each node in order (with optional parallelism for nodes with no data dependency between them), execute it.
- LLM nodes route through the model router (Module 7) and produce a record of `(prompt, model_chosen, completion, latency, dollar_cost, token_count)`.
- Deterministic nodes run in-process or as subprocesses depending on the node's declared isolation requirement.
- All inputs, all intermediate values, all outputs, all timings, all costs are recorded into the trace.
- Hard limits: per-node wall time, per-machine total cost, per-machine total wall time. Hitting any → execution returns a partial trace with a failure marker.

**Acceptance.** Executor runs the same SM on the same input twice and produces byte-identical traces *if* LLM calls are replayed from the prior run's cache, or stochastic-within-noise traces if LLM calls go live (depending on temperature). Concurrent execution honors the data-flow dependencies. Hard limits are enforced (no run exceeds budget).

**Status today.** Procedure-registry runs procedures; not state machines. The graph executor itself is the gap.

---

### Module 7 — Model router (provider gateway)

**Purpose.** When an LLM node executes, the router picks the cheapest sufficient provider for the requested capability tier and configuration.

**Tier definitions.**

| Tier | Capability bar | Example providers |
|---|---|---|
| `deterministic` | Pure code/tools, no LLM | Internal Python, system tools |
| `local_small` | ≤7B params, simple reasoning | Qwen-2.5-1.5B, Llama-3.2-3B (qualified on Spark2) |
| `local_coder` | Coding-specialized small models | Qwen-2.5-Coder-7B, DeepSeek-Coder-6.7B (qualified on Spark2) |
| `near_frontier_local` | DSv4-Flash class | vLLM TP=2 on Spark4/5 (live) |
| `frontier_api` | Sonnet, GPT-class | Anthropic / OpenAI |

**Routing decision.** Inputs: required tier (`>= local_small`), required capability tags (`{coding, control-flow}`), latency budget, cost budget, current load on each tier. Output: a specific provider endpoint to call. The router records why it chose what it chose (for replay and audit).

**Strength reduction.** When a node has been observed to succeed at `local_small` for N consecutive evaluations, the router *can* lock the choice to that tier for future calls of the same node-config — captured as memory (Module 11) and used as a hint for mutators (Module 5).

**Acceptance.** Router has live qualification records for every tier; routing decisions are logged and replayable; routing failure (no compatible provider available) returns a structured error with a specific blocker (not silently degrading to a different tier).

**Status today.** Skeleton in centaur. `near_frontier_local` is the only fully-qualified tier (centaur PR #100). `local_small`/`local_coder` qualification corpus exists on Spark2 (#1213/#1214 chain); router wire-up pending (#1215). `frontier_api` exists for escalation but unqualified.

---

### Module 8 — Evaluator / scorer

**Purpose.** Given a candidate's traces across the domain's test set, compute a per-candidate score that the promoter can use.

**Score components (per domain configuration).**

```
correctness ∈ [0, 1]   = passed_tests / total_tests
quality ∈ [0, 1]       = normalized domain-specific quality (e.g., 1 - asm_bytes/max_asm_bytes)
cost ∈ [0, 1]          = 1 - clamp(total_dollars / domain_budget_per_eval, 0, 1)
latency ∈ [0, 1]       = 1 - clamp(p95_compile_ms / domain_latency_budget, 0, 1)

composite = w_c * correctness + w_q * quality + w_$ * cost + w_l * latency
```

Domain authors specify the weights. Default for most domains is correctness ≥ a hard threshold (e.g., 1.0) and *then* lexicographic on (cost, quality, latency).

**Reproducibility check.** Every candidate is re-scored on a held-out test subset after promotion to confirm the score didn't come from overfitting to the visible test set.

**Acceptance.** Scorer takes a trace bundle + a domain definition and returns a structured score record with per-component breakdowns. Re-running the scorer on the same inputs produces byte-identical scores.

**Status today.** Not built. `complexity-*` and `procedure-*` CLI commands have score-card primitives but no evolution-loop integration.

---

### Module 9 — Promoter / selector

**Purpose.** Given a population of scored candidates, decide which survive to the next generation, which are mutated, which are discarded, and when to declare a winner.

**Selection policy.**

- **Elitism**: top-K candidates carry over unchanged.
- **Tournament**: pick winners by pairwise comparison on the composite score, with ties broken by held-out reproducibility.
- **Diversity preservation**: enforce a minimum structural-similarity distance between survivors to prevent premature convergence.
- **Mutation budget**: M new candidates per generation, drawn from the survivors by mutating each with a randomly-chosen mutation operator.
- **Crossover**: when a sibling-domain winner exists, splice a sub-path from it into a sibling-domain attempt.

**Termination conditions.**

- **Win**: best candidate's composite score is above threshold AND held-out reproducibility passes.
- **Convergence**: Δ(best score) < ε for K consecutive generations → declare current best and stop.
- **Budget exhausted**: total dollars spent on this domain ≥ budget → either declare current best with a "below-bar" annotation, or report failure honestly.
- **No-progress fail**: best score stuck below feasibility threshold for K generations → emit failure record naming what was tried.

**Acceptance.** Given a population + scores + termination policy, promoter returns next-generation set of candidates + a promotion record. Failure modes are explicit, not silent.

**Status today.** Not built.

---

### Module 10 — Replay system

**Purpose.** Every promoted candidate produces a bundle that re-executes deterministically, off-line, without live LLMs.

**Bundle contents.**

```
bundles/<domain>/<sm-id>.bundle/
    machine.json          — the state machine itself
    domain_snapshot.json  — pinned domain spec + test cases at the time of run
    traces/               — one trace per test case
        test_001.trace.json
            inputs, outputs, per-node values, LLM call (prompt, model, completion), timings, costs
    score.json            — the score record
    replay_manifest.json  — checksums, version pins, dependency list
    README.md             — auto-generated human-readable summary
```

**Replay command.** `centaur replay <bundle> [test_case_id]` re-executes the SM against the snapshotted test case, using cached LLM completions instead of live providers. Byte-identical output is the acceptance bar.

**Mutation context.** When the mutator picks a parent for a new candidate, it can fetch the parent's bundle to inspect what worked and what didn't on specific test cases — making mutation choices smarter.

**Acceptance.** A promoted bundle replays byte-identical six months later (modulo environment-level breaking changes). The replay manifest's checksums detect drift loudly.

**Status today.** Procedure registry has replayability for procedures; no bundle format for full SM runs.

---

### Module 11 — Memory subsystem (Trimind integration)

**Purpose.** Knowledge that persists across runs, across domains, and improves future candidates.

**What gets remembered.**

- **Promotion records**: every win — machine ID, domain, score, what mutation produced it, parent ID.
- **Mutation effectiveness**: which mutation operators tend to improve which kinds of machines on which kinds of domains.
- **Node performance traces**: a node's observed success rate per tier per domain category — feeds Module 5's strength-reduction decisions.
- **Failed-attempt records**: candidates that failed and why — prevents re-trying the same dead end across domains.
- **Cross-domain analogies**: when domain A's winning sub-path solves part of domain B, that analogy is recorded.

**Storage.** Trimind-brain's existing IVF-PQ over model2vec embeddings; ktok 18-facet extractor; brain forest as the durable store. Embeddings are over `(domain_signature, machine_structure, score_delta)` tuples.

**Retrieval API.**

```python
brain.retrieve(
    query="machine for parsing tasks with control flow output",
    domain="compiler-like",
    min_score=0.85,
    top_k=10
)
→ list of (machine_id, score, similarity, abstract_summary)
```

**Acceptance.** Across two sequential domains where domain B is a strict extension of domain A, candidates seeded with retrieved A-winners reach convergence in measurably fewer generations than candidates without retrieval. This is the "factory learns" empirical demonstration.

**Status today.** Trimind primitives exist and are good. Centaur ⇄ Trimind binding does not exist. **The single largest gap between today and the end state.**

---

### Module 12 — Curriculum manager

**Purpose.** For multi-stage curricula (Crenshaw is the canonical example), orchestrate progression — which domain to attempt next, which seed machines to carry forward, when to detect that a more general machine has emerged.

**Curriculum definition.** A YAML file listing domains in dependency order, with explicit edges:

```yaml
curriculum: crenshaw-lets-build-a-compiler
domains:
  - id: crenshaw-01-single-digit
    depends_on: []
  - id: crenshaw-02-multi-digit-vars
    depends_on: [crenshaw-01-single-digit]
    inherits_seed: true
  - id: crenshaw-03-ctrl
    depends_on: [crenshaw-02-multi-digit-vars]
    inherits_seed: true
  ...
generalization_probe:
  every_n_domains: 3
  test: "take the current best SM for the latest domain and run it on the test sets of all prior domains; if it scores ≥0.9 on all, promote it as a universal-stage and skip the next two domains' evolution"
```

**Curriculum execution.** `centaur curriculum run <curriculum-yaml>` walks the dependency graph, running `centaur evolve` on each domain. The generalization probe is the killer feature — detecting that the system has *induced* a machine general enough to handle several upcoming domains without further evolution.

**Acceptance.** End-to-end: Crenshaw curriculum runs to lesson 16 with all 16 winners promoted, OR runs further than lesson N with a generalization probe firing at some point. The execution log shows clearly which lessons required full evolution and which were resolved by a generalized machine from earlier.

**Status today.** Not built. The dogfood project pattern (`.centaur/projects.json`) has milestone tracking but not curriculum-shaped progression.

---

### Module 13 — Inspection / debug UI

**Purpose.** Humans (founder, operator, eventually external users) can see what the factory is doing, why it picked what it picked, and intervene when needed.

**Surfaces.**

| Surface | Use case |
|---|---|
| `centaur evolve` live TUI | Real-time during evolution: generation N, score histogram, top-K candidates, current evaluation queue |
| `centaur diff <sm-a> <sm-b>` | Side-by-side graph diff with shared sub-paths highlighted |
| `centaur replay <bundle> [test]` | Off-line deterministic reproduction with full per-node value inspection |
| `centaur trace <bundle> <test>` | Drill into one test case: see every LLM prompt/completion, every deterministic node's inputs/outputs |
| Web dashboard (eventually) | Cross-domain view: which domains have winners, score-vs-cost frontiers, memory growth curves, cost burn over time |
| `centaur inject <sm-id> --mutation-hint <yaml>` | Human suggests a mutation; goes into the next generation as one candidate among many |

**Acceptance.** From any merged PR, a human can take the linked bundle and answer in under 5 minutes: which test case had the largest delta, which LLM call was the cost driver, which mutation was the breakthrough.

**Status today.** Partial. `procedure-*` and `complexity-*` CLI commands have inspection primitives. No live TUI; no diff command in the spec's sense; no web dashboard for cross-domain view (the `CENTAUR_DASHBOARD.md` file is a manual proxy).

---

### Module 14 — Cost accounting / budget control

**Purpose.** Hard guarantees on dollars and wall time per domain, per generation, per candidate.

**Levels of budget.**

```
Global:    --max-total-cost $5000.00
Curriculum: --per-curriculum-cost $1500.00
Domain:    --per-domain-cost $250.00
Generation: derived (per-domain ÷ gen_count)
Candidate:  derived (per-generation ÷ population_size)
Per-LLM-call: derived (per-candidate ÷ expected_call_count)
```

Every node call checks the accumulated cost against the budget for its level. Hitting the limit fails the call with a `budget_exhausted` marker.

**Cost prediction.** Before launching a new generation, the budget controller checks the cost-model declarations of every node in every candidate and aborts the generation if projected total exceeds remaining budget — fail fast, not after burning $300.

**Acceptance.** A `centaur evolve` invocation with `--budget` flag never exceeds the budget by more than 5%, and reports honestly the cost burn at every termination event.

**Status today.** Not built. `complexity-*` has loose cost gates; nothing this rigorous.

---

### Module 15 — Self-improvement (recursive)

**Purpose.** Centaur itself can be modeled as a domain, and Centaur can evolve better versions of its own modules.

**Concrete self-improvement targets.**

- **Better mutators**: the mutation operator policy in Module 5 is itself a state machine that can be evolved. Score: how quickly the operators it picks lead to fitness improvement on held-out target domains.
- **Better node primitives**: a state machine could compose multiple existing nodes into a higher-level node that is observably useful across many domains; that composition is promoted into Module 2.
- **Better curriculum scheduling**: the curriculum manager (Module 12) can be evolved — the policy of when to fire generalization probes, when to skip ahead, when to backfill earlier domains.

**Constraints.** Self-improvement is gated. Module 15 is **off by default**. Enabling it requires a separate flag and a separate budget envelope, and the human can roll back any self-improvement at any time via the bundle replay system. Recursive improvement explicitly does not modify any module's interface — only internal policies.

**Acceptance.** Far future. Initial work focuses on making the *interfaces* clean enough that self-improvement at the policy level becomes possible without redesign.

**Status today.** Not built. Mentioned for completeness; explicitly de-prioritized below Modules 1–14.

---

## 6. Cross-module data flow (Crenshaw lesson 3 worked example)

This is the trace of one full evolution run, top to bottom:

```
1. Founder authors domains/crenshaw-03-ctrl/ with control-flow test cases.
   Module 1 validates the schema.

2. `centaur curriculum run crenshaw.yaml` walks to lesson 3.
   Module 12 detects lesson 2 has a promoted winner; passes it as seed.

3. Module 4 (candidate generator) produces population of 24:
     - 3 from mutation of the lesson-2 seed
     - 11 from library random walks (lex+parse+emit template variants)
     - 4 from human-seed machines committed to seed_machines/
     - 6 from cross-domain splicing (Trimind retrieves similar past wins)

4. For generation 1, Module 6 (executor) runs each candidate on the 84
   test cases. Each LLM node call goes through Module 7 (model router),
   which picks: deterministic for tokenize; local_coder for AST optimize;
   near_frontier_local for hard cases. Module 14 (budget) enforces $4/gen.

5. Module 8 (evaluator) scores all 24 candidates against
   correctness + asm-size + compile-wall + cost weights.

6. Module 9 (promoter) keeps top 8 elites, mutates 12 from them, accepts
   4 new template seeds for generation 2.

7. Generations 2-9 repeat. Convergence detected at gen 9 by score-delta
   threshold.

8. Module 10 (replay) emits the bundle for sm_3_g9_c11. Replay sanity test
   passes byte-identical.

9. Module 11 (memory) deposits 14 facts:
     - "tokenize+recursive-descent+llm-codegen template is strong for
        control-flow domains"
     - "local_coder tier sufficed for AST optimizer in this domain"
     - "splicing a parser from crenshaw-02 won 3 candidates' starts"
     - ... 11 more

10. Module 12 (curriculum) advances to lesson 4. Seed inheritance carries
    sm_3_g9_c11 forward, Trimind retrieval primes generation 1 with similar
    motif fragments.

11. After lesson 12, Module 12 fires the generalization probe: takes the
    current best lesson-12 SM, runs it on all of lesson 1-11's test sets.
    Result: scores ≥0.92 on all. Promotes as universal-stage,
    skips lesson 13's full evolution, jumps to lesson 14 with the
    generalized seed.

12. After lesson 16 (or earlier via generalization), the curriculum's
    end-state is one or more compiler state machines that handle a
    significant subset of C → assembly with measured (correctness, cost,
    speed, quality) profiles.

13. The founder runs `centaur evolve` on a *new* domain unrelated to
    compilers — "given a profile trace, suggest the top-3 optimization
    targets" — and the factory works without re-engineering. That
    demonstrates Centaur is a general factory, not a compiler-specific
    pipeline.
```

## 7. What "done" looks like per component

| Component | "100%" means |
|---|---|
| **Component 1** (factory core) | Crenshaw lesson 16 winner produced and replay-verified. Curriculum manager fires generalization probes successfully. `centaur evolve` runs on a new non-compiler domain and produces a winner with no factory code changes. |
| **Component 2** (memory) | Trimind ↔ Centaur binding exists; retrieval-augmented generation 1 candidates measurably converge faster than non-retrieved; LongMemEval ≥96.6% sustained when reached via a Centaur-orchestrated candidate. |
| **Component 3** (providers) | All five tiers have current, live, measured qualification records. Strength reduction is observed in practice: state machines that initially used `near_frontier_local` get observed-and-promoted to using `local_coder` for sub-tasks where it suffices, with cost halving. |
| **Component 4** (product) | A user submits a domain spec and a budget; receives a winner-bundle and a replayable result; can inspect why it won within 5 minutes; can promote, reject, or hand-mutate from the UI. |

## 8. Status today vs spec (rough)

| Module | % toward spec | Largest gap |
|---:|---:|---|
| 1 — Domain definition | 10 | `centaur domain submit` doesn't exist; no domain schema |
| 2 — Node library | 25 | Procedure registry exists; type signatures and cost models do not |
| 3 — SM representation | 15 | JSON shape is sketchy, no round-trip test |
| 4 — Candidate generator | 5 | Not started |
| 5 — Mutator | 5 | Not started |
| 6 — Executor | 30 | Procedure executor works; SM-graph executor does not |
| 7 — Model router | 55 | One tier live; small-model corpus exists; wiring pending (#1215) |
| 8 — Evaluator | 20 | `complexity-*` and `procedure-*` have score primitives; not evolution-shaped |
| 9 — Promoter | 5 | Not started |
| 10 — Replay system | 30 | Procedure bundles exist; SM-run bundles do not |
| 11 — Memory | 40 | Trimind itself ~75%; binding to Centaur 15% |
| 12 — Curriculum manager | 10 | Milestone-style projects exist; curriculum-shaped progression does not |
| 13 — Inspection UI | 35 | CLI inspection partial; no diff/replay-trace/dashboard surfaces |
| 14 — Budget control | 15 | Loose gates; no rigorous cost projection |
| 15 — Self-improvement | 0 | Deliberately deferred |

**Overall: ~22% of the spec realized.** Generously rounded.

## 9. Critical path from today to Crenshaw lesson 1

Minimum modules required to attempt lesson 1 end-to-end:

1. Module 1 (domain definition + Crenshaw-01 authored)
2. Module 2 (with at least: regex tokenizer, recursive-descent parser primitive, emit-asm template, LLM-call shape)
3. Module 3 (SM JSON schema + validator)
4. Module 4 (template-based generator only; library random walk deferred)
5. Module 6 (executor)
6. Module 7 (already mostly there; needs #1215 to wire local_small/local_coder)
7. Module 8 (correctness + cost scoring; quality/latency deferred)
8. Module 9 (elitism + tournament selection; mutation policies later)
9. Module 5 (just swap-node and reparameterize; advanced operators later)
10. Module 10 (bundle emit; full replay can lag)
11. Module 14 (basic per-domain budget; full hierarchy later)

That's 11 modules at minimum-viable scope. Each is a discrete shippable PR or small chain. **This is the spec-derived backlog.** It supersedes the current ad-hoc backlog as the source of truth for "what to build next."

## 10. Open questions for the founder

1. **Domain schema authoring** — do domain authors write Python harness code (full flexibility, higher friction) or YAML-only declarative specs (lower friction, may not generalize)? Recommendation: Python harness + YAML metadata; tighter than HuggingFace datasets, looser than Kaggle competitions.

2. **Crenshaw assembly target** — 68000 (Crenshaw's original) or x86-64 (modern but more complex)? Recommendation: 68000 verbatim for lessons 1–10, then a separate "port to x86-64" domain to test the system's ability to refactor a state machine for a new target.

3. **Generalization-probe threshold** — when does a state machine count as "general enough to skip the next lesson"? Recommendation: 0.92 mean composite score across all prior lessons' test sets, with no individual lesson scoring below 0.85.

4. **Memory growth budget** — Trimind storage isn't free; at scale across hundreds of domains the brain grows. Should there be a retention policy (forget facts not retrieved in N evaluations)? Recommendation: yes, but not for v1; document the question.

5. **Self-improvement boundary** — at what point does Centaur start evolving its own mutators (Module 15)? Recommendation: not until at least 3 unrelated domains have produced winners via the static-policy mutator, so we have a baseline.

6. **The vLLM 310 vs 106 tok/s number** (#1208 unblocked today) — must be resolved before any cost-based scoring is honest, since the cost model relies on knowing real provider throughput. P0 not just for throughput but for spec correctness.

## 11. What this document is and isn't

This is the *specification*. It is not the project plan. The dashboard tracks progress against this spec. The issue backlog drives the next concrete work. The protocol coordinates the agents doing the work.

This document is expected to be revised. Every revision must be a PR with a `Closes #N` reference where N is a "spec amendment" issue summarizing the change. The current revision is **draft v1, 2026-05-21T17:30Z, authored by Claude in chat from accumulated context plus founder articulation of the C-compiler test case**. Founder review and sign-off pending.
