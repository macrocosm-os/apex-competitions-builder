# Vibe-Coded Competition Report: `research_harness`

A build log and SDK stress test, written from the point of view of a fresh user trying to ship a
competition shape the SDK did not previously support.

## Summary

`research_harness` is an Apex **harness** competition: the model is held fixed and platform-served,
and miners submit the *scaffolding* around it — a Python `Harness` that searches a private
synthetic corpus, manages a referee-side context buffer, spends a metered token budget on the frozen
model, and answers multi-hop questions whose supporting documents it is never allowed to read
directly. Getting there required one genuinely new spec primitive (`base_model` + scoped
`referee.allow_internet`), and the design only became well-posed after inverting the obvious
architecture: **the model is a tool inside the referee, not a sidecar attached to the player.**

## At a glance

| | |
|---|---|
| Base model (assistant) | `claude-opus-5`, no subagents |
| Base model (competition) | `google/gemma-3-4b-it`, served via a local OpenAI-compatible endpoint |
| **Cost** | **~$18.93 estimated** — see *Limitations*; `/cost` was not available to me |
| Tokens (deduplicated) | 159.7k output · 23.2M cache-read · 333k cache-write · 230 uncached input |
| Wall-clock | 4h 36m session; **~1h 15m active** (a 3h 18m idle gap between prompts 1 and 2) |
| Human input | **5 prompts** (+1 failed paste), one of which was "full autopilot, chug away" |
| SDK diff | 10 files, **+277 lines**, zero deletions, zero new dependencies |
| New competition | 26 files, **3,399 lines** |
| Tests | **+97** (15 SDK cases from 9 new functions, 82 competition) → 216 green repo-wide |
| Declared baseline | **0.3479 ± 0.0239** (measured, real model, 7 master seeds) |
| Headroom | same harness at unlimited budget: **0.716–0.759**; target for a strong entry 0.85–0.95 |

## Scores

| Dimension | Score | One-line justification |
|---|---|---|
| **Ease of use** | **8 / 10** | `gym_v1` turned out to *be* an agent loop — referee sends observation, player returns action — so the hardest-sounding shape in the catalogue needed no protocol work at all. Same two deductions as every other report: `apex-dev run` doesn't run, and the `env/` import path bites. |
| **Completeness** | **5 / 10** | Unchanged from `otto`, and for the same reason: I wrote a third near-identical `tools/local_eval.py`. New this time — nothing in the SDK knows how to stand up a *dependency* of a competition, so the offline model stub is also hand-rolled. |
| **SDK expressiveness** | **7 / 10** | The one thing missing was expressible in 36 lines of schema, and every hard property I needed (immutability, digest pinning, cross-field validation, failure attribution) was already there and correct. Docked because the schema is closed, so "absent" still means "blocked", and because the spec had no vocabulary for a job party that is neither player nor referee. |

**Overall: 7 / 10 — the strongest showing of the three reports.** The contract stretched to a shape
it was visibly not designed for without deforming. The toolbox is still thin.

---

## What had to change in the SDK

Fewer changes than either previous report, and only one of them is a real primitive.

### 1. There was no way to declare a fixed base model (the blocker)

The spec assumes a job has exactly two parties: player and referee. A harness competition needs a
**third** — a platform-operated, competition-declared, metered inference endpoint — and there was no
vocabulary for it anywhere.

Added an optional top-level `base_model` block (`served_model`, `max_tokens_per_episode`,
`temperature`, `max_output_tokens`) and `referee.allow_internet`. The platform serves the model
outside the sandboxes and injects `MODEL_BASE_URL`, `MODEL_NAME`, `MODEL_TEMPERATURE`,
`MODEL_MAX_OUTPUT_TOKENS`, `MODEL_TOKEN_BUDGET` into the **referee only**.

Four fields, not fourteen. I drafted a larger block first (`served_by`, `endpoint_env`, a nested
`sampling` object) and cut all of it: the env-var names are a convention like `PLAYER_URLS` already
is, and "platform-served" is the only option that works.

### 2. The egress topology needed cross-field validation, not just schema

Added `check_base_model()` in `spec.py`, enforcing three rules JSON Schema can state but cannot
*explain*:

- `base_model` ⇒ `referee.allow_internet: true` (the referee makes every call).
- `base_model` ⇒ `entrypoints.evaluate.allow_internet` must stay false.
- `referee.allow_internet` without a `base_model` is an error, not a harmless default.

The middle one is the important one and it is why this belongs in code with a paragraph of comment
attached. A player that can reach the endpoint directly bypasses the referee's meter, so the token
budget — the scarce resource this entire competition is built on — silently stops binding, and
submissions get ranked on how much inference they were willing to steal. That failure has no
symptom. It doesn't crash, it doesn't warn; the competition just quietly stops measuring what it
claims to measure. Exactly the class of thing that should fail at preflight.

### 3. `pytest` could not collect two competitions at once

Not a spec problem — a monorepo problem my competition triggered. Each competition ships a top-level
`env/` package by convention, so `otto` + `research-harness` in one pytest process makes
`import env` ambiguous and four test modules fail to collect. Fixed at repo level rather than by
renaming another competition's package: `testpaths = ["tests"]` in `pyproject.toml` (bare `pytest`
now runs the SDK suite only) plus a per-competition loop in CI.

Worth flagging as a latent trap: this was already broken for anyone adding a *second* competition
with an `env/` directory, and the convention that causes it is the one the docs recommend.

### 4. What did *not* need changing, which is also a finding

- **`gym_v1` needed nothing.** No protocol change, no new verb. The referee-drives-player loop is
  already an agent loop; I used `observation`/`action` for a tool surface and it fit exactly.
- **`screening` needed nothing.** I expected a fight — real agent frameworks use dynamic dispatch
  and broad stdlib, and `block_dynamic_getattr` looked like it would reject legitimate harnesses. It
  didn't come up: because the harness's entire capability surface is the action dicts it returns, it
  needs no I/O at all, and the ASTGuard defaults plus a seven-module tripwire list were enough.
- **`private_data` needed nothing — I deleted my own use of it.** The corpus generates from the
  round seed inside the referee, so there is no bucket, no digest, and no onboarding round-trip.
  Worth noting for the design docs: seeded generation dominates `private_data` whenever the ground
  truth *can* be generated, because it removes an entire human handoff step from activation.
- **Both sandboxes fit in 1 CPU / 512Mi**, well under even the stage ceiling, because the only
  expensive thing in the competition is deliberately not in a sandbox.

---

## The design work that mattered more than the code

Two decisions decided whether this competition existed at all. Neither was an SDK limitation.

### The model has to be load-bearing, and the fix is structural

My first instinct was to argue the user out of a harness competition entirely, on the grounds that
the winning submission would be a hand-coded solver that ignores the model — and that you cannot
reliably detect that, because "did the model's output influence the answer" is undecidable in
general.

That objection was right and the conclusion was wrong. The fix is to never hand the submission the
raw material: **the harness never receives document text.** It can see a document exists, move it
into a referee-side context buffer, and pay tokens to ask the model about that buffer. The only
channel from corpus to submission runs through the model, so there is nothing to police.
`tests/test_end_to_end.py` asserts a zero-model-call harness cannot beat abstaining.

Making the model a referee-side *tool* rather than a player-side sidecar then pays for itself four
more times: metering is tamper-proof (the party counting tokens is the party spending them),
sampling is pinned in the spec so a round is reproducible, the call log becomes evidence in
`metadata` rather than an inference, and inference capacity sits outside the sandbox ceilings.

### The first working version scored 1.000

This is the most useful thing I learned. The competition ran green end to end, the reference harness
solved every question, and the score was **1.000** — because difficulty was resting entirely on
model fallibility. Serve a good model and the whole field saturates; the competition would have been
a measurement of the served model, not of the harnesses.

Fixed with three sources of task-intrinsic difficulty:

1. **A binding shared token budget** (the main lever). One pool across the whole round, so
   allocating effort across questions is the skill. The reference harness now runs at 99%
   utilisation and scores 0.35 where it scores 0.76 unbounded.
2. **Traps on intermediate chain hops**, not just the answer document — a derailed hop sends the
   harness off reading perfectly genuine documents about entirely the wrong entity, and nothing
   downstream looks suspicious.
3. **An `ambiguous` trap that no cheap rule resolves** — same authoritative source, same revision
   date. A registry-index document elsewhere in the corpus breaks the tie, so *detecting* the
   problem is free and *resolving* it costs tokens. The reference harness abstains on every one of
   them, which is where most of its remaining headroom lives.

Generalisable lesson for the design docs: **if you can raise the served model's quality and your
scores go up, your competition is measuring the model.** A harness competition needs a scarcity or
an adversary that a better model does not dissolve.

---

## Fresh-user UX notes

### What worked well

- **`gym_v1` is more general than it looks.** `otto`'s report notes a batched-prediction competition
  fell out of a protocol designed for step-wise RL; an agentic tool loop falls out just as cleanly.
  Two shapes it was not designed for, no protocol changes between them. That is a strong signal
  about the abstraction.
- **`humanoid-parkour` remains the best documentation in the repo.** I copied its structure
  wholesale — `env/` as referee-only modules, `tools/local_eval.py`, `HANDOFF.md`, measured
  `baseline_raw_score` with a `PROVENANCE.md` — and the resulting competition is legible because of
  it, not because of the prose docs.
- **The "let it crash" failure doctrine paid off immediately.** `ModelUnavailable` is a referee
  failure, not a submission failure, and the SDK's rule ("write no `result.json` and the platform
  blames you") made that a two-line decision instead of a design discussion. A shared model endpoint
  going down must never score a harness zero.
- **`preflight` is genuinely fast and the errors are readable.** Sub-second, and it printed my new
  `base_model` line the first time I ran it.
- **The closed schema (`additionalProperties: false`) is right even though it blocked me.** It is
  what made "there is no way to express this" an immediate, unambiguous finding rather than something
  I discovered three hours later on stage.
- **Generators are the right shape for a harness**, and nothing in the SDK fought it: `_solve` yields
  actions and receives observations, so a multi-step policy needs no hand-rolled state machine. Worth
  putting in a miner-facing doc.

### What cost me time

1. **`apex-dev run` still doesn't run anything.** Third report, third `tools/local_eval.py`. This
   one is 139 lines and near-identical to parkour's and otto's. It is now unambiguous: this is not a
   nice-to-have, it is a tax levied on every competition author, and the fix is to bless
   `local_eval.py` as SDK-provided.
2. **Nothing helps you stand up a competition's *dependencies*.** A harness competition cannot be
   tested without an inference endpoint, so I also wrote `tools/stub_model.py`. That is a new
   category of gap: `private_data` has `--private-data`, but `base_model` has nothing analogous, and
   the same will be true of any future competition needing a service rather than a file. An
   `apex-dev run --model-url` (or a bundled stub) belongs in the SDK.
3. **The `env/` import trap, again — and this time it broke the test suite.** Same root cause otto
   reported, new symptom: a third `env/` package made repo-wide `pytest` fail to collect. A
   documented convention or `PYTHONPATH=/app` in the base images would fix both symptoms at once.
4. **A stub model measured the wrong thing, convincingly.** My offline stub is a perfect extractor,
   so it scored the reference harness at 0.4289 and reported injection resistance as **1.00** —
   i.e. as fully solved. Against the real model it is 0.88, and the reference harness's answer parser
   turned out to be so brittle that its first real-model score was **0.02**. The stub had validated
   the plumbing and hidden the defect. This is the sharpest UX lesson in the report and it is not an
   SDK bug: it is an argument for the SDK to make real-endpoint runs the *easy* path, because a
   test double will happily certify a broken competition.
5. **`black` warns on every invocation.** `Python 3.13 cannot parse code formatted for Python 3.15`
   on every run, including `--check`. Harmless, but it makes a clean CI step look like a failure and
   it trains you to ignore formatter output. A `target-version` in `[tool.black]` would silence it.
6. **`submission.artifact_type: code` is one file.** A serious harness wants a package — planner,
   tool router, memory layer, parser. I kept the 253-line reference harness in one module and it was
   fine, but a competitive entry will be inlining a codebase into a single `.py`, and reviewing those
   at reveal time will be unpleasant. Wants a `code_archive` type with a declared entrypoint. Not a
   blocker; did not build it.

### Ergonomics wishlist, ranked by value

1. A real referee-driven `apex-dev run` — or bless `tools/local_eval.py` as SDK-provided. **Third
   report asking.**
2. A way to declare and locally stand up a competition *service* dependency, not just a file
   (`--model-url`, or a bundled OpenAI-compatible stub).
3. `PYTHONPATH=/app` in the base images, or a documented `env/` convention. **Second report asking**,
   now with a broken test suite attached.
4. `artifact_type: code_archive` with an entrypoint, for multi-file submissions.
5. `target-version` in `[tool.black]`.

---

## Design problems this shape exposes

**Reveal is calibrated for weights, not for source.** `submission_reveal_days` assumes revealing an
artifact is costly but does not hand over the R&D — true for an ONNX policy, false for a harness,
where the source *is* the entire invention and copy-then-perturb is nearly free. A short window
collapses a harness competition into fork-the-leader within two rounds. I set `14` (the longest in
the repo) as a judgement call, but the real fix is for reveal policy to vary by `artifact_type`
rather than by designer convention. Note this is the *opposite* problem to otto's, which needed
reveal suppressed entirely because the artifact is the answer key — together they say the same
thing: one integer is not enough vocabulary for reveal.

**`max_tokens_per_episode` is a cost control being used as a difficulty dial, and the spec doesn't
know that.** It sits in `base_model` next to the model id, reading like a billing limit. It is in
fact the single most sensitive knob in the competition: at n=70, 45k → 0.71, 32k → 0.47, 24k → 0.26,
16k → the abstention floor. It also cannot be tuned independently of `served_model`, because a
stronger model resolves each question more cheaply and slackens the budget toward saturation. Two
fields in different conceptual categories that must move together, with nothing in the schema
saying so. At minimum this deserves a documented warning; arguably the platform should refuse to
change one without a version bump that touches the other.

**Nothing expresses "this competition depends on a platform-operated service".** `base_model` is a
one-off. The next competition that needs a sandbox, a browser, a database, or a second model will
add another one-off block, and each will re-derive its own egress rules. If more than one of these
is coming, the general shape is a declared-dependency list with per-dependency scoped egress, and
it is cheaper to design now than to retrofit across three bespoke blocks.

---

## Limitations of this report

- **The cost and token figures are my own transcript tally, not `/cost`.** I have no billing tool, so
  I parsed this session's `.jsonl`, deduplicated by message ID (109 of 230 usage-bearing rows were
  duplicates — the same double-counting `otto`'s report documents), and priced the result at
  published Opus 5 rates assuming the 1-hour cache TTL this session uses. **`/cost` is authoritative
  and should be preferred over the ~$18.93 above.** The token counts themselves are solid; the dollar
  figure is derived.
- **This session is cleanly attributable to this task.** The transcript's first message *is* the
  competition request (15:49:12Z), it carries one session ID, and all 121 deduplicated assistant
  turns are `claude-opus-5` with no subagents. Three sibling sessions were building other
  competitions concurrently on the same machine; they bill separately.
- **The wall-clock figure is misleading on its own.** 4h 36m is real for the session, but prompt 1
  and prompt 2 are 3h 18m apart with the user away. The autonomous build ran 19:11:33 → ~20:23,
  about 1h 12m.
- **The images were never built.** No Docker build, no cosign signing, so both digests are zeros. The
  `COPY env/ /app/env/` layout is verified only by the same import paths working under the local
  harness.
- **`apex-dev run` was verified only up to exit 3**, because that is all it does.
- **The platform does not implement `base_model`.** The spec validates and preflights, but nothing
  serves a model, injects the env vars, enforces the meter, or scopes referee egress. That is the
  blocking work; see `HANDOFF.md` §7.
- **The baseline is model-specific and the model was local.** `google/gemma-3-4b-it` via Ollama, not
  a platform endpoint. Every score in this report moves if the served model changes.
- **Injection resistance is measured against one small model only.** 0.88 for the reference harness
  against `gemma-3-4b-it`; a larger model may resist better and shrink that axis.
- **Determinism is asserted for the world, not for the model.** Same seed gives a byte-identical
  corpus and question set (tested). End-to-end score reproducibility additionally depends on the
  serving stack honouring `temperature=0` and `seed`, which is outside this repo. Runs were stable
  across repeats against Ollama.
- **`by_trap` slightly under-reports trap exposure**, deliberately. A trap planted for question A
  lives in the corpus for question B too, so an "untrapped" question can still meet a
  duplicate-titled document. This is realistic and documented rather than fixed.

## What *is* verified

- **216 tests green** repo-wide (83 SDK, 51 `otto`, 82 `research_harness`), `ruff` and `black`
  clean, from a working tree that had 134 before.
- `apex-dev preflight` exits 0 on the new spec **and** still on hello-world and humanoid-parkour —
  the schema addition is backward compatible and strictly additive (`base_model` is optional and
  absent from the root `required` array).
- **All five `check_base_model` paths**, including both directions of the egress rule and the
  "egress with nothing to reach" case.
- **A full episode against a real model**, 64 questions, at exactly the spec's shipped
  configuration: `raw_score 0.3492`, 115 model calls, 27,783 / 28,000 tokens (99.2%), 79s.
- **Baseline sizing, measured:** 0.3479 ± 0.0239 over 7 master seeds (sem 0.0090), so submissions
  separated by more than ~0.05 are reliably distinguishable round to round.
- **The headroom is real, not asserted:** the same harness scores 0.716–0.759 with an unlimited
  budget, so the shipped gap is predominantly token efficiency.
- **Trap resistance, per kind, against the real model** (unlimited budget, seed 7):
  `contradictor` 1.00, `stale` 0.92, `injection` 0.88, `ambiguous` 0.15, untrapped 0.85. The two
  published rules solve the first two; the last two are genuinely open.
- **Six well-posedness invariants** asserted in `tests/test_world.py`: exactly one answer per
  question, iterative retrieval forced (no intermediate entity is named in the question text), every
  hop document findable by its own title, traps unfilterable by `doc_id` or title, determinism from
  seed, and every trap kind actually appearing.
- **Seven exploits, each with a test that shows it does not pay:** a zero-model-call guesser scores
  at or below an abstainer and both lose badly to reading; citation spam cannot reach full marks;
  stalling to the step cap scores 0.00 rather than collecting the abstention rate; a greedy harness
  that burns the pool on question one leaves every later question with literally zero tokens; a
  harness cannot raise the model's output ceiling; a crash is attributed to the submission and the
  referee gives up on a dead player rather than burning its timeout; and garbage actions terminate
  cleanly as typed errors.
- **The load-bearing property is tested directly**, not just argued: every observation returned by
  the environment is checked for document text, and there is none.

---

## What drove the cost

- **Cache-read was ~145× the output volume** (23.2M vs 159.7k) — the same ratio `otto` reported, and
  the same conclusion: **authoring a competition is a reading task, not a writing task.** Cache-read
  is ~61% of the estimated cost; output is ~21%.
- **The expensive part was measurement, not construction.** Roughly a third of the tool calls were
  eval sweeps — seed sweeps, budget sensitivity sweeps, and seven real-model episodes at ~80s each.
  That spend is what turned "the competition runs" into "the baseline is 0.3479 ± 0.0239 and the
  headroom is 0.37 of it", and it is the difference between this report and a plausible-sounding one.
- **No subagents were used** (the user's instructions excluded them). `otto`'s report found three
  subagents were its best-value spend at ~$2; a like-for-like comparison here isn't available.
- **The 1.000-score discovery paid for itself many times over**, and it only surfaced because the
  competition was actually run rather than reasoned about. Any process that stops at "green tests"
  would have shipped a saturated competition.

For calibration: **~$19 and ~1h 15m of active build time produced a complete, tested competition
measured against a real model, one new SDK primitive with validation, and a repo-level test-collection
fix** — with five human prompts, one of which was "chug away".

## Recommendation

Land `base_model` and `referee.allow_internet`. They are additive, tested, backward compatible, and
36 lines of schema; and harness competitions are a large category the SDK currently cannot express at
all. Land `check_base_model()` with them — the player-egress rule prevents a failure that has no
symptom.

Treat `research_harness` as the reference implementation for the shape, and as the strongest
available argument for the two standing asks: a real `apex-dev run`, and a way to stand up a
competition's service dependencies locally. It is also, per §4 above, a demonstration that the
existing contract is more expressive than it looks — `gym_v1`, `screening` and the failure-attribution
doctrine all took an agentic competition without modification.

The blocking platform work is in `HANDOFF.md` §7: serving the declared model, injecting the five
`MODEL_*` variables, enforcing `max_tokens_per_episode`, and scoping referee egress to that endpoint
only. As with `otto`, the platform work has a longer lead time than any of the SDK work here.

One thing to decide before a second harness competition exists: whether `base_model` is a one-off or
the first instance of a declared-dependency mechanism. Retrofitting that across three bespoke blocks
is much worse than designing it once.
