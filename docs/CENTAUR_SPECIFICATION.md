# Centaur specification

> Supersedes: `docs/CENTAUR_SPECIFICATION.md`

This is a canonical document. Update this file instead of adding overlapping docs.

> Status: **first complete draft, 2026-05-21T17:30Z.** Authored from accumulated conversation context plus the original C-compiler vision the founder articulated. Subject to revision by the founder; modules and acceptance criteria below are proposals, not final.
>
> Read this with `docs/CENTAUR_DASHBOARD.md` (live progress per component) and `.github/LANES.md` (work coordination protocol).

## 1. Vision in one paragraph

Centaur is a **general state-machine factory**. Given any problem domain that admits an objective metric function, Centaur evolves a population of candidate state machines (hybrid workflows of deterministic operations and LLM calls) and promotes the most cost-efficient candidate that meets the domain's quality bar. The end product is not "an AI that solves your problem" but "a *machine* that builds machines that solve problems." Once a winning state machine for a domain is promoted, it is a deterministic, replayable, debuggable artifact — not a language model output — and it costs orders of magnitude less to run than a frontier LLM call because its internal nodes were strength-reduced during evolution to the cheapest sufficient provider per step.

## 1.5. The diamond-quality standard

ct framing 2026-05-23:
> code quality analogy using carbon atom: when every atom has a reason for existing in its exact place and is in perfect coordination with all the other carbon atoms, you get a diamond. just a small distance away is a lump of coal. but the AI slop is like a cloud of diesel smoke. Clearly, AI can code and actually solve problems, but can AI write code at diamond quality level?

This document's commitment: **the state machines Centaur evolves and promotes must meet a diamond-quality bar — every node, every transition, every line of generated configuration must have a measurable reason to exist in its exact place.**

The three states:

- **Diesel smoke** (current AI-generated code): high entropy, no structure, every solution drags along unjustified helpers, every line could be deleted without measurable harm.
- **Coal**: DRY, no obvious duplication, but abstractions exist without justification and near-duplicates pass byte-equality checks.
- **Diamond**: every line answers "would removal change correctness, completeness, or clarity in a non-trivial way?" Yes for every line. Every abstraction has > 1 caller AND hides complexity that callers measurably benefit from not seeing. Every function does one thing that another function does not already do.

Centaur reaches diamond when both of the following are true:

1. **The factory's output is diamond.** Each promoted state machine, when serialized, passes a diamond-quality audit (issue #1340): no single-caller abstractions in the machine, no near-duplicate nodes, no documentation lines that another line already covers.

2. **The factory itself is diamond.** This codebase (`experiencenow-ai/ds4_on_spark` + `experiencenow-ai/centaur` + `experiencenow-ai/trimind-brain`) passes the same diamond-quality audit. A coal-quality factory cannot reliably produce diamond-quality machines; it will inject its own structural slop into every candidate it builds.

This is why halt-mode cleanup (#1326, #1330, #1331, #1328) is a precondition for serious factory output. Until the factory itself is at least at coal level (DRY, distilled docs, complexity-gated), the diamond standard cannot be enforced on its outputs. Halt-mode exit moves us to coal; issue #1340 defines the diamond audit; the factory eventually self-improves to diamond on both itself and its outputs.

Centaur Module 8 (Evaluator) MUST include the diamond audit as one of its scoring signals once the audit is built. A candidate state machine that solves the problem but is itself diesel smoke is not promotable — quality of the artifact matters as much as quality of the answer.

## 2. The LongMemEval zeroth domain — fast-path proof the factory works

Before the Crenshaw curriculum (§3) drives the factory to compiler-class capability, the **first real domain** Centaur attempts is `trimind-brain`'s existing `tests/longmemeval/bench.py`. This is the fast-path. The proof-test for "the factory exists and works" comes from this domain, not from Crenshaw.

**Why this domain first.**

- **Metrics already exist.** bench.py returns oracle accuracy (0..1) per question across a 500-question batch. Cost and latency per run are measurable as side effects.
- **HWM is known.** The current hand-tuned high-water-mark config (tools-haiku reader, sonnet escalation, opus judge, thinking=10000, sonnet codec) hits 96.6% oracle. That's the quality bar to beat or match at lower cost.
- **The state-machine search space is well-defined.** A LongMem state machine is a configuration plus a flow: which model handles reading, when to escalate, which judge to use, thinking budget, codec selection. Each axis is a mutation surface.
- **Cost matters from day 1.** A 500-question batch costs real dollars. Module 14 (budget control) and Module 7 (model router) are exercised immediately, not deferred until Crenshaw stages need them.
- **Strength reduction has concrete targets.** Can we replace opus-judge with sonnet-judge at >95% retention? Can we drop escalation entirely on questions a small reader is confident about? Each candidate state machine answers one of these empirically.

**What a LongMem state machine looks like.**

```
input: a LongMemEval question + the candidate's memory store

n1 (deterministic): retrieve top-K relevant memories via existing IVF-PQ search
n2 (LLM call, role=reader, tier_required >= local_coder):
    prompt = "given these memories, answer the question or say 'need escalation'"
n3 (deterministic): check if reader said 'need escalation' or confidence below θ
n4 (LLM call, role=escalator, tier_required = near_frontier_local):
    only invoked if n3 said escalate; prompt = reader's draft + retrieval context
n5 (LLM call, role=judge, tier_required varies):
    score the final answer against gold

output: (answer, confidence, total_cost, total_latency)
```

Mutations Centaur applies:

- **Reader-tier swap**: tools-haiku → qwen-coder-7b → llama-3.2-3b → ...
- **Skip escalation entirely**: remove n4
- **Lower thinking budget**: 10000 → 5000 → 2000 → 500
- **Codec swap**: sonnet → haiku
- **Conditional judge**: use opus-judge only when reader and escalator disagree
- **Retrieve more / fewer memories**: K = 20 → 50 → 5
- **Add cross-check**: spawn 2 readers in parallel, score-vote

**Score function.** Composite:

```
correctness = passed_questions / 500  (must be >= 0.95 — the hard floor)
cost = 1 - clamp(dollars / domain_budget, 0, 1)
latency = 1 - clamp(p95_question_ms / latency_budget, 0, 1)
composite = (correctness >= 0.95) ? (0.5 * correctness + 0.4 * cost + 0.1 * latency) : 0
```

That step-function on correctness ensures Centaur cannot "win" by being cheap-and-wrong. Below 95%, the candidate scores zero. Above the floor, cost dominates because that's what Centaur should be optimizing.

**End-state for this domain.** Centaur evolves a state machine that hits ≥95% oracle accuracy at materially lower cost than the HWM. If the SM hits 96.6% (matching HWM) at half the cost, that's the win. If it hits 97% at the same cost, also a win. If it cannot exceed the HWM's economics at all, that's a real finding (HWM is optimal, no slack) and the system has still demonstrated the factory works by surfacing that fact empirically.

**Why this matters for the broader spec.** Crenshaw is the proof that Centaur is *general*. LongMem is the proof that Centaur *exists at all*. The 11-module critical path in §10 has been reordered so LongMem-shaped work comes first.

---

## 2.5. The diamond refinement domain — first real Centaur use case for self-improvement

Per ct direction 2026-05-23, the **first real Centaur state-machine use case** is the diamond-refinement loop: take working but coal-quality Python code and mechanically refine it into functionally-equivalent diamond-quality code via local-model proposal + deterministic verification.

This is the architectural prototype for how Centaur produces diamond output across all future domains (§1.5).

**Why this is a real domain:**

| Module | Role in the diamond-refinement domain |
|---|---|
| 1 (Domain def) | `python_diamond_refinement` — metric is `(tests_pass × audit_score_delta)`. Test set is every Python file in `scripts/` and `centaur/` with passing tests. |
| 4 (Candidate gen) | Local small models on Spark2 (qualified corpus per #1308). Candidates are refactor proposals. |
| 5 (Mutator) | Mutates the refactor prompt, model choice, retry count, target-selection heuristic. |
| 6 (Executor) | Runs proposed refactor in sandbox; runs tests; runs audit. Deterministic. |
| 7 (Router) | Picks the local model. Spark2's `local_small`/`local_coder` tiers. Zero frontier API. |
| 8 (Evaluator) | Scores `correctness × artifact_quality_delta`. Correctness is "tests still pass byte-identically." Artifact quality is the audit. |
| 9 (Promoter) | Keeps refactor pipelines that consistently produce positive deltas. Retires the ones that regress or no-op. |

**The methodology distinction (per ct):**

> "code prototyping where you just want anything that works as quickly as possible without any code quality constraints — then that process converts an ambiguous and fuzzy english language specification into a verifiable (compilable) specification. Given that it becomes a lot more mechanical and does not require genius level thinking, just excellent craftsmanship. And we both know AI can do this."

Two distinct methodologies:

- **Creative prototyping** (ambiguous English → working code): requires genius-level reasoning. Done by xhigh agents on frontier APIs.
- **Mechanical refinement** (working code → diamond code): requires craftsmanship, not invention. Done by Sparks on local models.

The diamond-refinement domain is the canonical instance of mechanical refinement. Once it works on this codebase, the same Centaur harness handles "refine X for diamond" for any future X — generated assembly from a Crenshaw compiler candidate, a state machine emitted by a higher-level Centaur run, etc.

**Why this comes before Crenshaw in practice.** The diamond-refinement domain has all the properties of a real Centaur domain (deterministic metric, bounded test set, local-model-amenable workload) but with three killer features for getting started:

1. **No API cost.** Frontier calls are not in the loop.
2. **The test set is real code we already own.** No domain authoring required for the first batch — the codebase is the domain.
3. **The diamond standard from §1.5 is the fitness function.** The same standard the factory is supposed to enforce on its own output. Self-application: the first job of the diamond-making machine is to make the diamond-making machine itself diamond.

**The diamond-making process is itself two state machines, run in sequence (ct direction 2026-05-23):**

### 2.5.1. The mechanical refinement loop (#1345 — Sparks, local models, zero API cost)

Within-function transformations. Reduce LOC, inline single-caller helpers, eliminate exact duplicates, decompose long functions. Each transformation is small enough that small-models on Sparks handle it competently. Verification is byte-identical test output + audit-score improvement.

**Output of this loop:** diesel smoke → coal. The codebase becomes one where each remaining function does roughly one thing, with no obvious sprawl.

### 2.5.2. The frontier-intelligence clustering loop (#1348 — frontier models, after coal is visible)

Cross-function transformations. ct framing:
> "there is still need for frontier intelligence in identifying non-identical but similar enough pieces of coal that can be combined. The combining two pieces of coal into one denser piece (without making it more complex!) that can only happen after the smoke clears and we see all the lumps of coal and can properly categorize them to see which ones are neighbors."

The loop:
1. Compute the similarity matrix across all functions using Centaur's `dry_similarity` (returns `llm_judgement_required: True` for non-byte-identical pairs — exactly the cases needing frontier reasoning).
2. Cluster by similarity threshold. Each cluster = `{f1, f2, ..., fN}` of combinable functions.
3. Frontier model proposes a unified replacement that covers all N use cases, reduces total LOC, and preserves byte-identical behavior at every original call site.
4. Verify byte-identically. Verify audit-score improves.
5. Commit as one PR removing N originals, adding 1 unified function.

**Output of this loop:** coal → diamond. The remaining functions are not just non-duplicate; they are *unique and necessary*.

### 2.5.3. Model evolvability (the meta-loop point)

ct: "the whole point is we can test a variety of models and evolve the most efficient diamond making one."

In both loops, the model choice is a *parameter* of the state machine, not a hardcoded selection. Module 5 (Mutator) varies model_id, prompt template, threshold, retry policy. Module 9 (Promoter) keeps configurations that produce the highest `(diamond_delta × verification_success_rate) / cost_per_attempt` ratio.

Over generations, the diamond-maker evolves toward the most cost-efficient model for each loop:
- For mechanical refinement: probably a small 3-7B model is enough (small structural transformations). The evolution loop finds the cheapest model that maintains an acceptable success rate.
- For clustering: probably needs a stronger model (the synthesis step is hard). But "stronger" might mean Sonnet, not Opus — same Centaur strength-reduction principle says use the cheapest sufficient.

This is not theoretical. DeepSeek-V4-Flash at 30 tok/s on the Spark stack is fast enough to be tested in either loop. Once the evolution loop runs, the system *empirically* determines which model class wins for each kind of diamond work.

**Issues #1345 (mechanical) and #1348 (clustering) capture the implementation.** #1345 ships first; #1348 runs after #1345 has substantially completed (clustering noisy code produces noise).

---

## 3. The Crenshaw forcing function (multi-target generality test)

The general-purpose proof-test is **Jack Crenshaw's *Let's Build a Compiler* curriculum**. Per founder direction (2026-05-21), we **extract as many useful problems as possible** from Crenshaw rather than treating each lesson as a single domain. The 16 lessons contain dozens of separable sub-problems with distinct metrics — lexing, parsing, expression evaluation, control-flow lowering, type checking, register allocation, peephole optimization, error recovery, etc. Each becomes a domain in its own right, with its own gold test set and metric functions.

Additionally, **assembly target diversity is itself a domain dimension**: a Crenshaw sub-problem implemented for 68000 (Crenshaw's original) is a different concrete domain from the same sub-problem implemented for x86-64. The same evolved state machine architecture should solve both with retargeted emit primitives — and the system's ability to do that retargeting is itself a generality test.

| Lesson | Capability | Example extractable sub-domains |
|---:|---|---|
| 1 | Single-digit arithmetic expressions → assembly | `expr-tokenize-onedigit`, `expr-emit-add-mul-68k`, `expr-emit-add-mul-x86`, `expr-end-to-end-onedigit` |
| 2 | Multi-digit numbers, named variables | `lexer-numeric-multidigit`, `symbol-table-vars`, `expr-with-vars-emit` |
| 3 | Control structures (if/else, while, do/until) | `parse-if-else`, `parse-while`, `lower-ctrl-flow-labels`, `branch-fold` |
| 4 | Boolean expressions, relational operators | `tokenize-rel-ops`, `bool-expr-shortcircuit`, `bool-emit-flags` |
| 5 | Lexical scanning (tokenizer as separate phase) | `tokenizer-state-machine`, `tokenizer-error-recovery` |
| 6 | Parsing as a separate phase (AST) | `parse-to-ast`, `ast-walker`, `ast-prettyprint` |
| 7 | Calls and procedures | `parse-decl`, `parse-call`, `call-emit-conv-68k`, `call-emit-conv-x86` |
| 8 | Top-down expression parsing — full precedence | `parse-precedence`, `parse-assoc` |
| 9 | Types — char, int, long, signed/unsigned | `type-tokens`, `type-promote`, `type-check-binop` |
| 10 | Pointers and arrays | `parse-ptr-decl`, `addrof-emit`, `array-index-emit` |
| 11 | Multi-character identifiers, full lexer | `lexer-multichar-ident`, `lexer-keyword-table` |
| 12 | Miscellany — preprocessor, comments | `preproc-define`, `preproc-include`, `comment-strip` |
| 13 | Procedure parameters, locals, recursion | `stack-frame-68k`, `stack-frame-x86`, `recursion-emit` |
| 14 | Structures and unions | `parse-struct`, `struct-layout`, `union-overlap` |
| 15 | Back to the future — code generation refinements | `peephole-pass-1`, `reg-alloc-simple`, `reg-alloc-graph-color` |
| 16 | Unit construction — multi-file compilation, linking | `multi-tu`, `link-resolve-symbols`, `emit-object-format` |

The right-hand column is suggestive, not final — the founder will direct exactly which extractions are worth domain-ifying. Each extraction is independent work: writing test cases, metric functions, and accepting that the domain is registered.

After enough sub-domains land (probably ~30+) Centaur should hold one or more state machines that, given any C source program in a defined subset, emit working assembly for at least one target. The **measure of generality** is then: take an unrelated domain (e.g., "find the top-3 hotspots in a recorded profile trace") and Centaur produces a winning state machine for it without re-engineering the factory.

## 4. End-state walkthrough

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

## 5. The four-component decomposition (cross-referencing the existing vision)

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

## 6. Module-by-module specification

### Module 1 — Domain definition

**Purpose.** Specifies what "solving this problem" means in objective, runnable terms.

**Schema.** A domain is a directory in `domains/<name>/` containing both Python harness code (full flexibility for domain-specific glue) and YAML metadata (declarative description for the factory). Per founder decision (2026-05-21):

| File | Purpose | Format |
|---|---|---|
| `domain.yaml` | Name, description, parent domain, accepted I/O schemas, budget hints, level membership | YAML |
| `test_cases.jsonl` | One line per test case: input, expected output (or expected-property), gold metadata | JSONL |
| `metric_functions/` | Python modules implementing the metric callables (correctness, performance, quality, cost, custom) | Python |
| `seed_machines/` | Optional starter state machines provided by a human | JSON |
| `harness.py` | Domain-specific glue: how to feed a candidate state machine an input, how to capture its output, how to invoke the metrics, how to estimate cost | Python |

The split is deliberate: `domain.yaml` is the *contract* the factory reads to know how to handle the domain (what tier of provider is needed, what budget is reasonable, what the parent/level relationship is). `harness.py` is the *runtime* that knows the domain-specific gluing — exactly how to invoke `bench.py` for LongMem, or how to run a compiled assembly program for Crenshaw, or whatever the domain needs.

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
- **Reparameterize**: change one node's config (prompt template, temperature, **model_id (which specific model — frontier, mid-tier, local)**, model tier requirement, retry policy, etc.) without changing structure. **The model choice is a first-class evolvable parameter, not a hardcoded selection.** Per ct direction 2026-05-23: "we can test a variety of models and evolve the most efficient diamond making one." This is how Centaur empirically discovers which model class is cheapest-sufficient for which kind of node.
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

**Routing decision.** Inputs: required tier (`>= local_small`), required capability tags (`{coding, control-flow}`), latency budget, cost budget, current load on each tier, *and* required concurrency shape (single-stream vs batched). Output: a specific provider endpoint to call with a specific batching configuration. The router records why it chose what it chose (for replay and audit).

**Strength reduction.** When a node has been observed to succeed at `local_small` for N consecutive evaluations, the router *can* lock the choice to that tier for future calls of the same node-config — captured as memory (Module 11) and used as a hint for mutators (Module 5).

**Batched-throughput economics.** Per founder direction (2026-05-23), the big throughput gains for small models come from batched serving, not single-stream. The router must understand that the same model has different `(tok/s, latency)` characteristics at c=1 vs c=8 vs c=32 vs c=128. A tier's qualification record must include:

- Single-stream tok/s (latency-optimized; what one user-facing request sees)
- Aggregate tok/s at multiple concurrency points (throughput-optimized; what evolution loops in parallel can sustain)
- Per-request p50 and p95 latency at each concurrency
- Peak VRAM at each concurrency

For Centaur evolution loops, multiple candidates evaluating against the same dataset in parallel hit the *aggregate* curve, not the single-stream curve. A 24 tok/s c=1 model that delivers 200+ tok/s aggregate at c=32 is a different economic offering than the c=1 number alone implies. Router decisions must use the right curve for the workload shape.

**Quality requirement.** Every qualified provider must have a real quality measurement on a benchmark appropriate to its intended task class — LongMemEval for memory-reading tiers, ds4-eval for reasoning, humaneval-class for coder tiers. Liveness checks (4-prompt string-match tests) are NOT quality measurements and cannot be the basis for routing decisions.

**Acceptance.** Router has live qualification records for every tier with (single-stream tok/s, aggregate tok/s curve, p50/p95 latency curve, peak VRAM curve, real quality score). Routing decisions are logged and replayable. Routing failure (no compatible provider available) returns a structured error with a specific blocker (not silently degrading to a different tier).

**Status today (2026-05-23).** Skeleton in centaur. `near_frontier_local` is the only fully-qualified tier (centaur PR #100; quality vs antirez IQ2XXS not yet measured per #1296). `local_small`/`local_coder` qualification corpus exists on Spark2 with single-stream throughput numbers per PR #1308, but: (a) no batched/aggregate throughput data exists (#1319 filed), (b) "pass_rate" is on 4 trivial liveness prompts, not a real quality measurement (#1320 filed). Router wire-up pending (#1272). `frontier_api` exists for escalation but unqualified.

---

### Module 8 — Evaluator / scorer

**Purpose.** Given a candidate's traces across the domain's test set, compute a per-candidate score that the promoter can use.

**Score components (per domain configuration).**

```
correctness ∈ [0, 1]   = passed_tests / total_tests
quality ∈ [0, 1]       = normalized domain-specific quality (e.g., 1 - asm_bytes/max_asm_bytes)
cost ∈ [0, 1]          = 1 - clamp(total_dollars / domain_budget_per_eval, 0, 1)
latency ∈ [0, 1]       = 1 - clamp(p95_compile_ms / domain_latency_budget, 0, 1)
artifact_quality ∈ [0,1] = 1 - clamp(diamond_audit_violations / max_violations, 0, 1)

composite = w_c * correctness + w_q * quality + w_$ * cost + w_l * latency + w_a * artifact_quality
```

Domain authors specify the weights. Default for most domains is correctness ≥ a hard threshold (e.g., 1.0) and *then* lexicographic on (artifact_quality, cost, quality, latency).

**Artifact-quality component (the diamond audit) — see §1.5.** When the diamond audit (issue #1340) is built, every candidate's *serialized state machine* is run through it. Single-caller abstractions in the machine, near-duplicate nodes, and documentation overlap each register as violations. A machine that solves the domain perfectly but is itself diesel-smoke quality scores low on `artifact_quality` and may lose to a slightly-worse-correctness but higher-quality competitor when weights make it. This is how Centaur is taught to produce diamond, not just to produce *answers*.

**Reproducibility check.** Every candidate is re-scored on a held-out test subset after promotion to confirm the score didn't come from overfitting to the visible test set.

**Acceptance.** Scorer takes a trace bundle + a domain definition and returns a structured score record with per-component breakdowns including `artifact_quality`. Re-running the scorer on the same inputs produces byte-identical scores.

**Status today.** Not built. `complexity-*` and `procedure-*` CLI commands have score-card primitives but no evolution-loop integration. Diamond audit (#1340) not yet built — but once available, it slots in as the `artifact_quality` component without changing the scoring framework.

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

### Module 11 — Memory subsystem (Trimind integration + DAS-backed archive)

**Purpose.** Knowledge that persists across runs, across domains, and improves future candidates. **And** the long-term storage of KV cache pages that let Centaur reuse long contexts across candidate evaluations without paying repeated prefill cost.

Per founder direction (2026-05-23), **KV cache is the memory model**. Embedded memory facts (the Trimind/IVF-PQ layer below) are one part of Module 11; KV cache pages stored on the DAS-backed archive are the other. Both must work together.

#### 11.1 The semantic layer (Trimind binding)

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

#### 11.2 The KV-cache archive layer (DAS-backed)

**Why this exists.** VRAM is the scarcest resource on the GB10s. A long context (1M tokens, 256k KV entries) costs gigabytes of VRAM that could otherwise hold MoE expert weights or larger models. For Centaur evolution loops — where the same system prompt + retrieved memories are reused across many candidate evaluations of the same question — re-prefilling that context every time is pure waste. Storing the KV cache to long-term archive and staging it back into VRAM on demand reclaims that VRAM.

The DAS is the physical substrate.

**Physical layout (2026-05-23 baseline; parameters subject to growth):**

- 6-bay DAS enclosure hung off the Mac Studio
- **5 × 16TB drives = data tier** with XOR parity striped across the 5 drives such that any one drive can fail and be rebuilt from the others. NOT a dedicated parity drive — XOR is rolled into the data drives to preserve the parallel-fetch property
- **1 × 22TB drive = staging tier**, NOT part of the parity set. 6TB of its capacity exceeds the data-tier drive size; that excess is allocated as scratch for high-write-rate work (frequent overwrites, log writes, work-in-progress staging) where the slower archive drives would burn lifetime
- Sparks reach the DAS at 10 Gbps over the LAN; Centaur orchestration runs on the Mac

**System parameters (must be configurable; not hardcoded literals):**

```
ARCHIVE_DATA_DRIVE_COUNT     = 5    # currently
ARCHIVE_STAGING_DRIVE_COUNT  = 1
ARCHIVE_DATA_DRIVE_TIB       = 16
ARCHIVE_STAGING_DRIVE_TIB    = 22
ARCHIVE_STAGING_USABLE_TIB   = 6    # the part of the staging drive that exceeds the data-tier size
ARCHIVE_PARITY_TOLERANCE     = 1    # number of data drives that can fail without data loss
```

Adding drives later changes these constants; no code rewrite.

**Storage invariants:**

- **Append-mostly, not strictly append-only.** Manifest rewrites, garbage collection of orphaned blobs, version pruning of obsolete bundles — all permitted, all bounded. Hot path is append.
- **Related-data co-located.** A single Centaur node call typically fetches several related KV blobs (system prompt + 5 retrieved memories + per-question prefix). The layout must group related blobs such that one parallel-5 fetch retrieves the related set. For Centaur this means: same domain, same generation, same candidate lineage cluster onto the same drive (or stripe per-blob so all 5 drives contribute in parallel).
- **XOR parity** across the 5 data drives. Tolerates 1 drive failure. Monthly XOR re-check; alarm on drive failure; rebuild from parity.

**API (provided by the archive manager subsystem):**

```
archive.put_kv_blob(key, blob_bytes, related_group, ttl?) -> blob_id
archive.get_kv_blob(blob_id) -> bytes              # may issue parallel-fetch across drives
archive.get_kv_blob_group(group_id) -> [bytes,...] # parallel-fetch the whole related set
archive.stage_for_vram(blob_ids) -> staged_path    # decompress + format for the serving stack
archive.put_bundle(bundle_dir) -> bundle_id
archive.get_bundle(bundle_id) -> path
archive.gc(older_than)
archive.parity_check()
archive.parity_rebuild(failed_drive_index)
archive.tier_metrics() -> usage_per_drive, staging_writes_per_min, parity_age
```

**Critical architectural point:** Centaur is the orchestrator. The serving stacks (vLLM, llama.cpp) do NOT fetch from SATA. They have no business knowing about long-term storage. Centaur decides which KV blobs need to be staged into VRAM before a node call, invokes `stage_for_vram`, and hands the resulting memory-mapped path to the serving stack via a stack-specific load-prefix-KV-from-blob API (vLLM patch + llama.cpp patch are downstream issues).

**Typical flow for one LongMem candidate evaluation:**

1. Centaur picks the candidate to evaluate against question Q.
2. Candidate's state machine declares: "I need the system prompt KV + memories M1..M5 KV in VRAM before my first node."
3. Centaur archive manager: `archive.stage_for_vram([sysprompt_kv_id, m1_kv_id, ..., m5_kv_id])`. This issues parallel reads across the 5 data drives; the related-data layout ensures these come up in one parallel batch.
4. The serving stack (vLLM on Spark4/5 or llama.cpp on Spark2) loads from the staged memory-mapped path. The prefix-cache is populated without prefill.
5. The candidate's nodes execute against the warm KV cache.
6. KV cache pages generated during execution that should be remembered get `put_kv_blob`'d back to the archive.

**Acceptance for Module 11.**

Across two sequential domains where domain B is a strict extension of domain A, candidates seeded with retrieved A-winners (from the semantic layer) AND fed pre-staged KV from the archive layer reach convergence in measurably fewer generations than candidates without either. End-to-end: the same question evaluated 50 times across 50 candidate variations does NOT pay 50 prefill costs.

**Status today (2026-05-23).** Trimind primitives exist and are good (~75% of the semantic layer). Centaur ⇄ Trimind binding does not exist (~15%). Archive manager + serving-stack patches are filed as issues #1315/#1316/#1317 but not yet built. **The combined memory subsystem remains the single largest gap between today and the end state.**

---

### Module 12 — Curriculum manager (concurrent multi-level evolution with backward injection)

**Purpose.** Orchestrate progression across a curriculum where many levels evolve **simultaneously**, with newly-promoted lower-level winners injected back into higher-level populations as fresh genetic material. Per founder direction (2026-05-21), the curriculum is *not* sequential ("solve level N before starting level N+1").

**Core model.**

```
Level 1: evolving continuously toward 100% (never stops)
Level 2: spawned when Level 1 hits 90%; evolving continuously
Level 3: spawned when Level 2 hits 90%; evolving continuously
...
Level K: spawned when Level K-1 hits 90%

Backward injection: every time Level N promotes a new winner
  → that winner (and its sub-paths) becomes a fresh seed in Level N+1, N+2, ...
  → existing populations at those levels get re-shuffled with the new material
  → diversity-preservation rules in Module 9 ensure the injection adds variation,
    not just replaces the current best
```

**Why this model.** Sequential probe-and-skip discards information. The lower-level population is the most *empirically grounded* representation of "how to solve this kind of sub-problem." As that population continues to improve, the higher-level populations benefit from the improved foundation without having to rediscover it. A 95% Level-1 winner injected into Level 2 gives Level 2 a head start; when Level 1 reaches 98%, Level 2 gets another injection round and improves further. Genetic material flows upward continuously, not in one-shot.

**Curriculum specification.**

```yaml
curriculum: crenshaw-extracted-domains
levels:
  - id: level-1-lex-onedigit
    domains: [expr-tokenize-onedigit, expr-emit-add-mul-68k]
    target_score: 1.00
    spawn_next_at: 0.90

  - id: level-2-expr-multidigit
    depends_on: [level-1-lex-onedigit]
    domains: [lexer-numeric-multidigit, expr-with-vars-emit]
    target_score: 1.00
    spawn_next_at: 0.90
    inject_from: [level-1-lex-onedigit]   # winners from level 1 are injected here

  - id: level-3-ctrl-flow
    depends_on: [level-2-expr-multidigit]
    domains: [parse-if-else, parse-while, lower-ctrl-flow-labels]
    inject_from: [level-1-lex-onedigit, level-2-expr-multidigit]

  ...

cross_level_injection:
  trigger: "any time a level promotes a new winner with score Δ ≥ 0.02 over previous best"
  payload: "promoted SM + its top sub-paths flagged for splice candidates"
  destination: "all dependent levels currently active"
  rate_limit: "no more than 1 injection per dependent level per N minutes (avoid thrashing)"

continuous_run:
  scheduler: "all spawned levels run concurrently as long as budget allows"
  budget_split: "lower levels get more weight initially; redistributes as upper levels mature"
  termination_per_level: "only when target_score is hit OR explicit human stop"
```

**Concurrent execution.** The factory's executor (Module 6) is now driving N populations simultaneously, not one. Schedule:

- A budget allocator splits the curriculum-wide budget across active levels weighted by (level priority × current rate of improvement × time-since-last-promotion).
- Within each level, the standard evolve loop runs (generate, evaluate, score, promote, mutate, repeat).
- The promoter posts every promotion event to a curriculum bus.
- Subscribers (other active levels with `inject_from` referencing the promoting level) consume the event and add the new winner to their next generation's seed set.

**Acceptance.** End-to-end:

1. Curriculum YAML defines ≥3 dependent levels.
2. Centaur launches all 3 concurrently (subject to budget).
3. Level 1 hits 90% → Level 2 receives its first injection.
4. Level 1 continues to 95% → Level 2 receives a second injection.
5. Level 2's convergence rate after the second injection is measurably faster than Level 2's solo evolution would have been (the empirical demonstration that backward injection helps).
6. Promotion log clearly shows which Level-2 winners had Level-1-derived sub-paths in their lineage.

**Status today.** Not built. The current `dogfood-*` project pattern in centaur has milestone-style sequential progression, which is the wrong shape.

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

## 7. Cross-module data flow (LongMem zeroth-domain worked example)

This is the trace of one full evolution run on the LongMem domain — the first domain Centaur attempts.

```
1. The LongMem domain is authored as domains/longmem-oracle/ containing:
     - domain.yaml: parent=null, level=null, target_score=0.97 at cost <= $0.50/q
     - test_cases.jsonl: 500 LongMemEval questions (from trimind-brain/tests/longmemeval)
     - metric_functions/oracle_accuracy.py: wraps existing bench.py judge logic
     - metric_functions/cost_per_question.py: tracks dollar spend per question
     - harness.py: invokes bench.py with the candidate's SM-encoded configuration
   Module 1 validates the schema; the harness smoke-tests against a 10-question subset.

2. `centaur evolve longmem-oracle --budget 200.00 --generations 8 --population 16`
   Module 4 generates 16 candidates:
     - 1 from the HWM seed (tools-haiku/sonnet/opus/thinking=10000/sonnet-codec)
     - 5 from mutating the HWM along a single axis (different reader, different judge, etc.)
     - 5 from library random walk (combinations of available reader/escalation/judge nodes)
     - 5 from cross-axis mutations (drop escalation, halve thinking budget, etc.)

3. For generation 1, Module 6 (executor) runs each candidate's harness.py against
   the 500-question batch. Each LLM call inside bench.py is routed through Module 7
   (model router) which picks the candidate's declared tier (or strength-reduces
   if a smaller tier has been observed sufficient in past runs).

   Budget governor (Module 14) enforces: $12.50/generation (200/16); a candidate
   that's burning faster than 16% of its share by question 50 gets aborted with
   a budget_exhausted marker.

4. Module 8 (evaluator) scores each candidate's run:
     - correctness = passed_questions / 500 (must be >= 0.95 floor or candidate scores 0)
     - cost = 1 - clamp(dollars / 25, 0, 1)  (the budget floor weighting)
     - latency = 1 - clamp(p95_question_ms / 30000, 0, 1)
     - composite = 0.5*correctness + 0.4*cost + 0.1*latency  (above the floor)

   Initial generation typically shows: HWM seed scores ~0.94 (high correctness, low cost
   weight). Mutations like "drop escalation entirely" score 0.0 because correctness
   drops below the 0.95 floor. Mutations like "swap opus-judge to sonnet-judge"
   score around 0.97 if correctness holds and cost drops materially.

5. Module 9 (promoter) keeps top-4 elites, mutates 8 from them, accepts 4 new
   library-walk seeds for generation 2.

6. Generations 2-6 explore the cost-correctness frontier. Generation 7 finds
   a candidate at correctness=0.967, cost=$0.21/q (vs HWM $0.43/q) — that's
   2x cost reduction at parity. Generation 8 sharpens; convergence detected.

7. Module 10 (replay) emits the bundle. Replay sanity test: same SM, same 500
   questions, same scored output byte-identical.

8. Module 11 (memory) deposits ~30 facts:
     - "sonnet-judge sufficed when reader-confidence > 0.85" (90% of questions)
     - "opus-judge only needed on the 10% of questions where reader & escalator disagreed"
     - "thinking=5000 sufficed for 80% of questions; 10000 only needed for math-heavy"
     - "haiku-reader sufficed when retrieval returned high-similarity memories (cosine > 0.91)"
     - ... more

9. Domain done. The promoted SM is the first live, replayable, mutation-history-tracked
   state machine in the Centaur system.

10. (No automatic next domain — LongMem is not part of the Crenshaw curriculum.)
    The factory itself is now validated. The Crenshaw curriculum (§3) launches next
    as the multi-level concurrent evolution test.
```

### 7.1 Cross-module data flow (Crenshaw level-3 worked example, multi-level concurrent)

After LongMem validates the factory, the Crenshaw curriculum starts. This trace shows the **concurrent multi-level + backward injection** model (per founder decision on §11 Q3) in action.

```
T=0:    centaur curriculum start crenshaw-extracted.yaml
        Module 12 launches Level 1 (expr-tokenize-onedigit, expr-emit-add-mul-68k).
        Level 1 starts evolving.

T=2hr:  Level 1's best candidate scores 0.91 (above the 0.90 spawn threshold).
        Module 12 spawns Level 2 (lexer-numeric-multidigit, expr-with-vars-emit)
        with Level 1's current best as initial seed. Level 1 keeps evolving toward 1.00.
        Curriculum bus: Level 1 has subscribers [Level 2].

T=4hr:  Level 1 hits 0.94. Promotion event posted to curriculum bus.
        Level 2 (subscribed) consumes the event: its next generation gets the new
        Level 1 winner injected as a fresh seed candidate. Level 2's population
        diversity-preservation rules (Module 9) ensure injection adds variety,
        not just replaces current best.

T=5hr:  Level 2 hits 0.91. Module 12 spawns Level 3 (parse-if-else, parse-while,
        lower-ctrl-flow-labels) with Level 2's current best plus the latest Level 1
        material as initial seeds. Curriculum bus subscribers now: Level 1 -> [L2, L3];
        Level 2 -> [L3].

T=8hr:  Three levels active. Level 1 at 0.97, Level 2 at 0.93, Level 3 at 0.89.
        Budget allocator (Module 12) has shifted weight: Level 1 was getting 60% at
        T=0; now Level 1 gets 25%, Level 2 gets 40%, Level 3 gets 35%. Lower-priority
        because Level 1 is approaching the asymptote and marginal generations buy
        diminishing returns; Level 3 is in steepest gradient.

T=12hr: Level 1 hits 0.99. Promotion event posted. L2 and L3 both consume; both
        get fresh injection material. Level 2 jumps from 0.93 to 0.95 in the
        generation that consumed the injection (faster than the previous generation's
        Δ of 0.01). Empirical evidence that backward injection helps.

T=24hr: Level 1 at 1.00. Level 2 at 0.98. Level 3 at 0.95. Level 4 spawned at
        T=18hr when Level 3 crossed 0.90; now active with seeds from L1, L2, L3.

T=48hr: Levels 1-3 at 1.00 (asymptote). Levels 4-6 active. The factory has produced
        12 promoted state machines across 6 active levels in 48 hours of clock time.
```

The empirical question this design answers: does backward injection produce measurably faster convergence than solo evolution at each level? Module 12 includes telemetry that records, for each promoted candidate, whether any of its lineage came from injection events (vs pure within-level mutation), so this can be measured.

## 8. What "done" looks like per component

| Component | "100%" means |
|---|---|
| **Component 1** (factory core) | Crenshaw lesson 16 winner produced and replay-verified. Curriculum manager fires generalization probes successfully. `centaur evolve` runs on a new non-compiler domain and produces a winner with no factory code changes. |
| **Component 2** (memory) | Trimind ↔ Centaur binding exists; retrieval-augmented generation 1 candidates measurably converge faster than non-retrieved; LongMemEval ≥96.6% sustained when reached via a Centaur-orchestrated candidate. |
| **Component 3** (providers) | All five tiers have current, live, measured qualification records. Strength reduction is observed in practice: state machines that initially used `near_frontier_local` get observed-and-promoted to using `local_coder` for sub-tasks where it suffices, with cost halving. |
| **Component 4** (product) | A user submits a domain spec and a budget; receives a winner-bundle and a replayable result; can inspect why it won within 5 minutes; can promote, reject, or hand-mutate from the UI. |

## 9. Status today vs spec (rough)

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

## 10. Critical path from today to first promoted state machine

Per founder direction (2026-05-21), the first domain Centaur attempts is **LongMem oracle** using trimind-brain's existing `tests/longmemeval/bench.py`. This is the fast path to validating the factory exists. Crenshaw extraction starts in parallel as the broader generality test.

### Critical path to LongMem first promotion

Minimum modules required to attempt the LongMem zeroth domain end-to-end:

1. **Module 1** (domain definition) — author `domains/longmem-oracle/` with `domain.yaml`, `test_cases.jsonl` (500 LongMemEval questions), `metric_functions/`, `harness.py` that calls `bench.py`. Schema validator exists.
2. **Module 2** (node library, scoped subset) — at minimum: retrieve-from-trimind, llm-call (with tier-required parameter), conditional-branch (for escalation logic), score-and-judge. The harness encodes a state machine as a dict of (reader_tier, escalator_tier, judge_tier, thinking_budget, codec, K_retrieved).
3. **Module 3** (SM JSON shape + validator) — minimal version, no graph-execution semantics; the LongMem SM is configuration-shaped, not graph-shaped.
4. **Module 4** (candidate generator) — HWM seed mutator only. Library random walk deferred.
5. **Module 5** (mutator) — reader-tier swap, escalator drop, thinking budget halve, codec swap, judge-tier-swap. Just these five operators.
6. **Module 6** (executor) — invokes the harness for one candidate. Concurrency deferred (run candidates serially).
7. **Module 7** (model router) — `near_frontier_local` is live; needs `local_small`/`local_coder` from #1215.
8. **Module 8** (evaluator) — wraps bench.py's existing judge output as correctness; adds cost tracking.
9. **Module 9** (promoter) — top-K elitism only; tournament/diversity deferred.
10. **Module 10** (replay) — bundle emit with the LLM-cache; full replay verification deferred.
11. **Module 14** (budget control) — basic per-domain budget cap with prediction (LongMem at 500 questions × candidates is expensive; cost prediction is mandatory from day 1).

That's 11 modules at scoped-MVP scope. **This is the spec-derived backlog.** Each is a discrete shippable PR or small chain. The current ad-hoc backlog is no longer the source of truth; this is.

### Critical path to Crenshaw first sub-domain win

After LongMem first promotion lands (proving the factory works), the Crenshaw curriculum starts. Minimum additional modules:

12. **Module 1 (Crenshaw instance)** — author `domains/crenshaw-01-expr-tokenize-onedigit/` and friends (see §3 table).
13. **Module 2 (Crenshaw nodes)** — add tokenizer, parser, ast-emit, asm-emit nodes for the 68k or x86-64 targets.
14. **Module 3 (graph-shaped SM)** — extend Module 3 from configuration-shaped to graph-shaped, with type-checked edges.
15. **Module 6 (graph executor)** — extend Module 6 to execute typed graphs, not just call a single harness.
16. **Module 12** (curriculum manager — concurrent multi-level + backward injection per §6 Module 12 spec).

After this expansion, the system can run the Crenshaw curriculum in the concurrent-multi-level mode described in §7.1.

## 11. Open questions and founder's decisions

Resolved decisions are recorded here as part of the spec's truth. Deferred items remain open.

### Resolved (2026-05-21 founder direction)

**Q1 — Domain schema authoring.** ✅ **Python harness + YAML metadata**, both. YAML describes the contract the factory needs; harness.py is the runtime glue. Updated in Module 1.

**Q2 — Crenshaw assembly target.** ✅ **Extract as many useful problems as possible from Crenshaw.** Each Crenshaw lesson has multiple separable sub-problems (lexing, parsing, control-flow lowering, code emission per architecture, etc.). Each becomes its own domain. Target diversity (68000 vs x86-64) becomes a domain dimension — same problem, different concrete target. Updated in §3.

**Q3 — Generalization-probe / level-progression threshold.** ✅ **Concurrent multi-level evolution with backward injection.** Lower levels never stop until 100%. At 90%, the next level spawns and starts evolving with the current best as seed. As lower levels continue to improve, their new winners are injected back into all dependent higher-level populations as fresh genetic material. Module 12 rewritten to reflect this; §7.1 walks through it with the Crenshaw curriculum example.

### Deferred (founder will revisit when more data is available)

**Q4 — Memory growth budget.** Trimind storage isn't free; at scale across hundreds of domains the brain grows. Retention policy: forget facts not retrieved in N evaluations? Status: deferred. Document the question, observe the actual growth shape, decide later.

**Q5 — Self-improvement boundary.** At what point does Centaur evolve its own mutators (Module 15)? Recommendation: not until at least 3 unrelated domains have produced winners via static-policy mutator. Status: deferred. Self-improvement remains off by default; Module 15 stays in the spec but unimplemented.

**Q6 — The vLLM 310 vs 106 tok/s regression (#1208).** Must resolve before any cost-based scoring is honest. Tactical work proceeding in parallel; not blocking spec sign-off. Status: hardware-track issue, not a spec question.

## 12. What this document is and isn't

This is the *specification*. It is not the project plan. The dashboard tracks progress against this spec. The issue backlog drives the next concrete work. The protocol coordinates the agents doing the work.

This document is expected to be revised. Every revision must be a PR with a `Closes #N` reference where N is a "spec amendment" issue summarizing the change. The current revision is **v1.5, 2026-05-23T07:30Z** (§2.5 extended with the two-loop architecture: §2.5.1 mechanical refinement on Sparks (#1345) for within-function transformations, §2.5.2 frontier-intelligence clustering (#1348) for cross-function N-to-1 combinations after the codebase reaches coal level, §2.5.3 model evolvability — the model choice in both loops is a first-class evolvable parameter, not hardcoded. Module 5 mutator Reparameterize operator extended to call out model_id explicitly).

Earlier revisions: **v1.4, 2026-05-23T07:00Z** (§2.5 added — diamond refinement domain as first real Centaur use case). **v1.3, 2026-05-23T06:30Z** (§1.5 diamond-quality standard; Module 8 artifact_quality scoring). **v1.2, 2026-05-23T03:30Z** (Module 11 KV-cache archive; Module 7 batched-throughput + real quality). **v1.1, 2026-05-21T17:30Z** (founder Q1/Q2/Q3 resolved; LongMem zeroth-domain added).

Earlier revisions: **v1.2, 2026-05-23T03:30Z** (Module 11 expanded to cover the DAS-backed KV-cache archive subsystem; Module 7 extended to require batched-throughput economics and real quality measurement). **v1.1, 2026-05-21T17:30Z** (founder review applied — Q1, Q2, Q3 resolved; LongMem zeroth-domain added).

Earlier revisions: **v1.1, 2026-05-21T17:30Z** (founder review applied — Q1, Q2, Q3 resolved; LongMem zeroth-domain added per founder direction; Module 12 rewritten for concurrent multi-level + backward injection; §10 critical path now LongMem-first then Crenshaw).
