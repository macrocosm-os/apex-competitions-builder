# research_harness — designer / platform handoff

Everything a Macrocosmos maintainer needs to review, activate, or take over this
competition, plus the honest list of what is not done.

## 1. What it is

A harness competition. The miner submits scaffolding (`artifact_type: code`); the model is
fixed, platform-served, and identical for every submission. Score is mean question score
over a round of multi-hop questions against a freshly generated private corpus.

Layout:

| Path | What |
|---|---|
| `spec.yaml` | the spec (declares the new `base_model` block) |
| `env/world.py` | corpus + question generator, BM25 index, the four traps |
| `env/tools.py` | the tool surface and budget state machine — the miner-facing contract |
| `env/model.py` | frozen-model client (stdlib urllib, OpenAI-compatible) + metering |
| `env/scoring.py` | answer normalization, the four outcomes |
| `referee/referee.py` | drives the episode, owns the model connection, writes result.json |
| `player/launch.py` | imports the miner's `Harness`, serves gym_v1 |
| `baseline/submission.py` | the published reference harness |
| `tools/local_eval.py` | full local episode (real HTTP, real referee) |
| `tools/stub_model.py` | offline test double — **not** a shipped image |
| `tests/` | 82 tests, including one per exploit |

Neither image needs a pip dependency: retrieval is stdlib BM25, the model client is stdlib
urllib, and the harness gets the stdlib.

## 2. The design decision everything rests on

**The frozen model is a tool inside the referee, not a sidecar attached to the harness.**
The harness emits `{"tool": "ask", ...}`; the referee assembles the prompt from its own
context buffer and makes the call.

This inversion is what makes the competition well-posed, and it is worth not undoing:

1. **Metering is tamper-proof.** The party that counts tokens is the party that spends
   them. A miner cannot self-report usage.
2. **The model is provably load-bearing.** The harness never receives document text, so
   the only channel from corpus to submission runs through the model. There is no
   hand-coded solver to police — `tests/test_end_to_end.py` asserts a zero-model-call
   harness cannot beat abstaining.
3. **Sampling is pinned in the spec**, so every submission faces an identical model and a
   round is reproducible from its seed.
4. **The call log is evidence.** `metadata.model_calls` / `tokens_spent` /
   `token_utilisation` make "did this submission use the model" observed, not inferred.
5. **Inference lives outside the sandbox ceilings.** Both sandboxes run at 1 CPU / 512Mi.

## 3. Well-posedness guarantees

Asserted in `tests/test_world.py`, because each one is load-bearing for the scores meaning
anything:

- **Exactly one answer.** The graph is functional in the forward direction and every hop
  document states its relation exactly once. Questions only traverse forward.
- **Iterative retrieval is forced.** Intermediate entity names never appear in the question
  text, so a harness cannot jump to the answer document.
- **Navigable.** Every hop document is in the top 8 for a search on its own title.
- **Not memorizable.** Pseudoword entities, regenerated per round from a seed the player
  never sees. The referee image can be public: without the seed the corpus is unforgeable.
- **Traps are unfilterable by identity.** Trap documents take the victim's exact title and
  a `doc_id` in the victim's namespace. Only `source` and `revised` distinguish them, and
  both rules are published.
- **Deterministic.** Same seed → byte-identical corpus, questions, and score.

One deliberate non-guarantee: a trap planted for question A lives in the corpus for
question B too, so an "untrapped" question can still meet a duplicate-titled document
routed through a shared institute. This is realistic cross-contamination and it means
`metadata.by_trap` slightly under-reports trap exposure. Do not "fix" it.

## 4. Measured baseline

Model: **`google/gemma-3-4b-it`** served over a local OpenAI-compatible endpoint (Ollama
`gemma3:4b`), `temperature=0`, `max_output_tokens=512` — exactly what `spec.yaml` pins.
`n=64`, `token_pool=28000`, `trap_rate=0.7`, reference harness, 7 master seeds:

```
mean 0.3479   sd 0.0239   sem 0.0090   range [0.3180, 0.3844]
token utilisation 99.1-99.5%   ~115 model calls/episode   ~2 min wall clock
```

Same harness, unlimited budget: **0.7164-0.7586**. So ~0.37 of the gap to its own ceiling
is pure token efficiency, and the `ambiguous` trap (always abstained, 0.15) is most of the
rest. Intended target for a strong submission: 0.85-0.95.

Trap resistance at unlimited budget (seed 7): `contradictor` 1.00, `stale` 0.92,
`injection` 0.88, `ambiguous` 0.15, untrapped 0.85. The two published rules fully solve
`contradictor` and nearly solve `stale`; `injection` is genuinely unsolved (the real model
does sometimes follow the imperative text despite a defensive system prompt); `ambiguous` is
untouched. That spread is the competition working as designed.

Per-difficulty at the shipped budget: the budget bites hardest on long chains, which is
deliberate — allocating by difficulty is the first thing a better harness will do.

**Two things a maintainer must redo if anything changes:**

- **The baseline is model-specific.** Serve a different model and both
  `baseline_raw_score` and `token_pool` are wrong. Re-measure both, together.
- **`tools/stub_model.py` is not a substitute.** It scores this harness at 0.4289 (an upper
  bound: it is a perfect extractor) and reports `injection` as fully solved, which is false.
  It exists so the plumbing can be tested with no GPU, nothing more.

## 5. Round sizing

`n=64` (7 templates cycled), `token_pool=28000`, `max_steps_per_question=40`,
`max_context_tokens=3000`, `trap_rate=0.7`, `deadline_ms=15000`.

Wall clock is dominated by model latency, not by the harness: ~115 calls per episode, ~2
min against a local 4B model. `timeout_s` is 3600 on both sandboxes, which leaves ample
slack for a slower or more contended endpoint. `deadline_ms` only has to cover the
harness's own decision, because the model call happens on the referee's side of the wire.

`token_pool` is the difficulty dial and the cost dial at once, and it is **sharp**.
Sensitivity at `n=70` against the stub, reference harness: 45k → 0.71, 32k → 0.47,
24k → 0.26, 16k → 0.15 (the abstention floor). Change it only with a version bump and a
re-measured baseline.

Do not raise the served model's size without re-tuning `token_pool`. A stronger model makes
every question cheaper to resolve, which slackens the budget and pushes the field toward
saturation — the scarcity is what makes this a harness competition rather than a model
evaluation.

## 6. Reveal window

`submission_reveal_days: 14`, the longest in this repo, deliberately. For a weights
competition, revealing an ONNX policy is costly but the R&D is not handed over. For a
harness, the source **is** the entire invention and copy-then-perturb is nearly free — so a
short window collapses the competition into fork-the-leader within two rounds. Recommend
the platform treat reveal policy as varying by `artifact_type` rather than by convention.

## 7. Not done / needs a maintainer

1. **`base_model` is a new spec block that the platform does not implement yet.** The spec
   validates and preflights, but nothing stands the model up. Required platform work:
   serve `base_model.served_model`; inject `MODEL_BASE_URL`, `MODEL_NAME`,
   `MODEL_TEMPERATURE`, `MODEL_MAX_OUTPUT_TOKENS`, `MODEL_TOKEN_BUDGET` into the referee;
   enforce `max_tokens_per_episode` platform-side; allow referee egress to that endpoint
   **only**. See `docs/authoring.md` §2c.
2. **Images are unbuilt and the digests are zeros.** Needs a competition repo with a
   release workflow, keyless cosign, and the digests pasted into `spec.yaml`.
3. **The baseline was measured against a locally served `gemma-3-4b-it`, not against the
   platform's endpoint.** The number is sound for that model (§4) but it is model-specific;
   confirm the platform serves the same model, or re-measure.
4. **No Layer-2 behavioural screen.** Probably unnecessary — a harness has no I/O surface
   and the sandbox is the boundary — but a screen that rejects a submission making zero
   model calls would fail the obvious garbage earlier and more cheaply than a full round.
5. **`env/` collides across competitions in one pytest process.** Worked around at repo
   level (`testpaths` + a per-competition CI loop). The real fix is for each competition to
   live in its own repo, which is the intended model anyway.
6. **Single-file submission.** A serious harness wants a package. See the `code_archive`
   note in the SDK report.
