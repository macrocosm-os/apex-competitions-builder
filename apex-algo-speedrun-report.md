# Vibe-Coded Competition Report: `algo_speedrun`

A build log and SDK stress test, written from the point of view of a fresh user trying to ship a
competition shape the SDK did not previously support: the referee, not the player, runs untrusted
code, and does real GPU training while doing it.

## Summary

`algo_speedrun` is a nanochat-style (karpathy/nanochat) speedrun competition: miners submit
overrides to a pinned, referee-owned copy of nanochat's training loop (architecture+optimizer,
LR/momentum/weight-decay schedule, and training-data packing), the referee actually trains a tiny
proxy model with those overrides applied and scores validation bits-per-byte, and a separate,
out-of-band weekly job promotes the top-K submissions to a real, full-scale nanochat run on rented
GPU infra. Getting there required inverting the SDK's own player/referee trust boundary — the
referee executes miner code directly, in-process, not the player — and a genuinely new schema
primitive (`referee.resources`) that four prior competitions in this repo never needed.

## At a glance

| | |
|---|---|
| Base model (assistant) | `claude-sonnet-5`, 2 background `Explore` agents used only for up-front research (schema + precedent reading), zero subagents for build/hardening |
| Base model (competition) | **none served** — trains a nanoGPT-style model from scratch (`karpathy/nanochat`, pinned commit `92d63d4`), the opposite shape from `research_harness`'s served-model design |
| Cost / tokens / wall-clock | **not available to me** — no `/cost` tool and no transcript file to tally in this environment; see *Limitations* |
| Human input | **9 free-text prompts** + **2 structured clarifying-question answers, the second reversing the first** (schema-gap handling: "proposal only" while just designing → "implement it now" once the goal became "merge to mainnet") |
| SDK diff (mine, isolated from the shared working tree) | 3 files touched, **~130-155 lines my own** (`referee.resources` `$defs` extraction + property in the schema, `_check_resources_block` + refactored `check_resource_ceilings` in `spec.py`, 3 new tests) — see *Limitations* for why `git diff --stat` shows more |
| New competition | 23 files, **2,269 lines** (1,039 Python excl. tests, 407 tests, 823 docs/config) |
| Tests | **+34 competition tests** (20 test functions, some parametrized), **+3 SDK tests** → 86 SDK tests green, 34/34 competition tests green when nanochat is on the path (all skip cleanly, not fail, when it isn't) |
| Declared baseline | **2.5773 ± 0.0606 val-bpb** (measured, n=5 seeds, real downloaded ClimbMix-400B data + a real trained tokenizer, not mocks) |
| Headroom | **not applicable, and that's a finding** — see *Design problems this shape exposes* |

## Scores

| Dimension | Score | One-line justification |
|---|---|---|
| **Ease of use** | **5 / 10** | The easy 80% (spec, screening, gym_v1 reuse for a one-shot file-fetch) was genuinely easy. The other 20% — a referee that must execute untrusted code itself — has no supported pattern in the SDK at all, and I had to consciously override the base `Referee` class's own failure-attribution doctrine to make it safe. |
| **Completeness** | **5 / 10** | Real Docker builds, a real measured baseline, real economics — this is more end-to-end-verified than a typical first pass. Docked for the same universal complaint every report in this repo makes (`apex-dev run` doesn't run anything) plus two genuinely new gaps this shape exposed: no multi-file submission artifact, no tiered/staged evaluation primitive. |
| **SDK expressiveness** | **6 / 10** | `gym_v1`'s reset/act shape happily carried a one-shot "give me your file" exchange with zero protocol changes — that's a real strength, twice-proven now. But the schema has no vocabulary for "the referee is the untrusted-code sandbox this round," and multi-file submissions have no representation at all; both had to be worked around entirely in competition code, not expressed. |

**Overall: 5.3 / 10 average — real, but this shape found harder edges than the ones before it.**
`research_harness` needed one new primitive and the existing contract stretched to fit everything
else. `algo_speedrun` needed that same primitive category again (`referee.resources`, this time
implemented rather than left as a proposal) **and** ran directly into the one thing every prior
report's execution model assumed away: that the referee is always the trusted party.

---

## What had to change in the SDK

### 1. `referee.resources` did not exist — the schema assumed one resource declaration is enough

Every field in the schema's `resources` block was, by convention, sized for the *player*. The
`referee` block had `protocol`/`image`/`timeout_s`/`allow_internet` and nothing about CPU, memory,
or GPU. That's fine when the referee only judges — every one of this repo's four prior competitions
uses it that way — but here the referee has to *train a model*, which needs GPU, and there was no
way to say so.

Fixed by extracting the existing `resources` shape into `$defs/resources` and adding an optional
`referee.resources` property using the same `$def`, plus a `_check_resources_block` helper in
`spec.py` that both the top-level `resources` and the new `referee.resources` now call
independently. Additive and backward compatible: every existing spec that never sets
`referee.resources` is unaffected, verified by `test_referee_resources_optional_and_valid` alongside
new ceiling/GPU-gating tests for the field itself.

This started life as a `PLATFORM_PROPOSAL.md` (the `energy-forecast`-precedent pattern: ship a
CPU-shaped fallback now, ask for the real thing later) and was only actually implemented once the
user's goal changed from "design this" to "get this to mainnet" — a genuine instance of scope
depending on stated intent, not on what the competition technically needed. Worth noting for anyone
reading this repo's other `PLATFORM_PROPOSAL.md` files: they are real, live asks, not just
documentation.

### 2. Nothing lets a submission be more than one file — worked around, not fixed

`submission.artifact_type: code` is one file at one `target_path`, no exceptions, and a
training-loop change is naturally multi-file (a model definition, an optimizer, a data loader are
different concerns). I didn't touch the schema for this — asking for a new artifact type is a much
bigger, higher-risk ask than `referee.resources`, and it wasn't necessary. The workaround:
`submission.py` carries an `EXTRA_FILES: dict[str, str]` map of virtual files, which the referee
re-materializes to disk before importing. It works, `tools/pack_submission.py` makes authoring it
not-miserable, and it's documented in `HANDOFF.md` as a deliberate choice, not a discovery — but
it's a workaround, and the platform's Layer-1 ASTGuard has no idea the virtual files exist (see #4).

### 3. The referee-executes-untrusted-code pattern doesn't exist anywhere else, and the SDK's own
   safety doctrine has to be deliberately overridden to use it safely

This is the one that actually cost design time. Every other competition in this repo — including
`research_harness`, which also has an unusual shape — keeps the invariant that the **player**
sandbox holds the miner's code and the **referee** only ever observes it over HTTP. GPU doctrine in
this repo (`evaluation-design.md`: "8 of 9 production competitions are CPU-only end-to-end; the one
GPU competition uses GPU only on the scoring side") pushed hard toward putting training in the
referee, which means the referee has to `exec()` the miner's Python directly, in its own process.

The base `Referee` class's documented doctrine is "let unexpected exceptions propagate so the
platform blames the referee, not the submission" — correct when the referee never runs miner code,
actively wrong here, since a bad submission (a shape error, a hang) would otherwise read as a
referee crash and zero the whole round. I had to write a deliberate, documented deviation: a broad
`try`/`except` around `exec`+train, plus a hand-rolled daemon-thread watchdog
(`_run_with_deadline`) so a hang gets attributed to the submission well before the container's own
timeout kills everything indiscriminately. None of this is SDK-provided; all of it had to be
built and independently verified (a `time.sleep(999)` submission test, an actual measurement of the
resulting `terminal_reason`) because getting it wrong silently breaks the platform's own "who do we
blame" contract.

### 4. The platform's Layer-1 ASTGuard doesn't reach into `EXTRA_FILES` — had to reimplement it

A direct consequence of #2: the platform's generic screener only ever looks at `target_path`'s
literal bytes, so a competition doing the virtual-files trick gets zero automatic screening on the
part of the submission that actually matters. `referee/screen.py` reimplements an equivalent
(and, after actually red-teaming it, a materially larger) AST tripwire by hand — including a real
arbitrary-file-write bug in my own first draft that only a test suite caught (`torch.hub.load(...)`
wasn't blocked by a single-level `(module, attr)` call check because it's a nested attribute chain;
fixed once `pytest` surfaced it, not before).

### 5. No native tiered/staged evaluation — solved entirely out-of-band, no schema touched

Checked the schema, the docs, and every shipped competition: nothing supports "cheap eval every
round, expensive eval for the top-K periodically," which this competition genuinely needs (nanochat
at real scale is hours on 8xH100; that cannot run per-submission-per-round). Unlike #1, I did not
implement this — `tools/run_deep_eval.py` runs entirely outside the round lifecycle, on a separate
cadence and separate infra, so the competition ships without it. `PLATFORM_PROPOSAL.md` records the
ask as still open and explicitly non-blocking.

---

## The design work that mattered more than the code

### Actually running the code found four real vulnerabilities code review would have missed

Threat-modeling "the referee executes fully miner-controlled code" — rather than assuming the
sandbox model from every other competition still applied — surfaced four issues, and I want to be
specific that each was *verified* with a working exploit before being called fixed, not just
reasoned into existence:

1. `scratch_path / rel_path` silently discards `scratch_path` when `rel_path` is absolute
   (`Path("/tmp/x") / "/etc/passwd" == Path("/etc/passwd")` — genuinely surprising pathlib
   behavior) — an `EXTRA_FILES` key of `"/etc/passwd"` would have written anywhere the referee
   process could reach.
2. A malicious `data.py` could special-case `split == "val"` to fake an arbitrarily good score —
   closed by making the validation split **never** overridable, verified by confirming a cheating
   submission scores identically to an honest one (the cheat path is unreachable, not just
   discouraged).
3. `evaluate_bpb` trusts the model's own self-reported loss — a malicious `forward()` could lie
   about it. Closed by having the referee call the model with `targets=None` (nanochat's own
   `forward()` returns raw logits in that case, confirmed by reading the pinned commit) and compute
   cross-entropy independently; verified against a model that reports a fake near-zero loss during
   training and still scores an honest (bad) `val_bpb`.
4. A hang reads as a referee crash under the SDK's own doctrine — closed with the watchdog in
   change #3 above.

None of this shows up if you only build the happy path and run the test suite once. It shows up
when you sit down and ask "what can code I don't trust, running inside my own process, actually
do" — which is a genuinely different exercise from anything the other three reports in this repo
describe, because none of their competitions run miner code anywhere but the player sandbox.

### The "headroom" concept from other reports doesn't transfer, and that's worth naming

`research_harness`'s report can say "the reference harness scores 0.35 bounded, 0.72-0.76
unbounded, so the shipped gap is headroom." `algo_speedrun` has no equivalent number: the baseline
is "zero training-loop changes," and the ceiling is "however good a training-loop change can
possibly make a fixed architecture class" — which is an open research question, not a measurable
constant. This isn't a gap in this report; it's a structural property of an open-ended
algorithmic-improvement competition versus a bounded-resource-allocation one, and worth flagging for
anyone using "headroom" as a go/no-go gate across competition types: it doesn't apply uniformly.

---

## Fresh-user UX notes

### What worked well

- **`gym_v1`'s reset/act shape carried a completely different job than it was built for, again.**
  `research_harness` used it as an agent tool loop; here the player just needs to hand over one file
  over one `act()` call. Same protocol, zero changes, second proof this abstraction generalizes
  further than its own docs suggest.
- **The security checklist's own vocabulary ported cleanly to a boundary it wasn't written for.**
  "Never send validation criteria to the player" (written for a scored-response competition) is the
  exact right frame for "the validation split must never be miner-overridable" here, just with the
  boundary moved from sandbox-vs-sandbox to in-process.
- **`apex-dev preflight` caught the intentional stage/prod split immediately and correctly** — this
  spec fails on `stage` (no GPU pool, and the referee's `cpu_limit` exceeds stage's ceiling anyway)
  and passes on `prod`, which is exactly the right behavior for a competition that genuinely cannot
  run without a GPU, and it needed zero extra code to express once `referee.resources` existed.
- **The pinned-image-fetched-at-build-time pattern (already implicit in how base images work)
  generalized to a much bigger external dependency (nanochat) without any new mechanism** — a Docker
  build already has network access; nanochat is just one more thing fetched and hashed at that time,
  not a live dependency at eval time.

### What cost me time

1. **`apex-dev run` still doesn't run anything — fourth report, same complaint.** I built
   `tools/local_eval.py` from scratch again.
2. **Docker builds found bugs no local Python testing could have, and nothing in the SDK helped find
   them earlier.** `apex-referee-base`'s minimal Debian image has neither `curl` nor a C++
   compiler; the second one (`g++`) is needed at *training* time, not build time, because nanochat's
   own optimizer JIT-compiles a fused kernel via `torch.compile` on first `optimizer.step()`. This
   is invisible until you actually run a container, and I only found it because I did.
3. **The referee-executes-code pattern has no SDK support and no prior art in this repo to copy
   from.** Every piece of it — the exec sandboxing, the AST re-screening, the path-traversal
   validation, the watchdog — was hand-rolled, and each piece independently needed its own
   adversarial test because there was no existing convention to lean on for "is this actually safe."
4. **A real baseline measurement needed real external infrastructure the SDK has no opinion about.**
   Nanochat needs a trained tokenizer and real pretraining data shards; there's no
   `--offline-stub` equivalent that would have been honest here (a fake tokenizer would make the
   measured `val_bpb` meaningless), so getting one real number required downloading ~184MB of real
   data and training a real BPE tokenizer, entirely outside anything the SDK provides or expects.
5. **This machine's Docker Desktop disk was too small for the real (CUDA) `torch` install** — an
   environment problem, not an SDK one, but it meant the actual production Dockerfile line has only
   been logic-validated via a CPU-only substitution, not built as-shipped. Documented plainly in
   `DOCKER_BUILD_NOTES.md` rather than glossed over.

### Ergonomics wishlist, ranked by value

1. A real referee-driven `apex-dev run` — or bless `tools/local_eval.py` as SDK-provided.
   **Fourth report asking.**
2. A supported pattern for "the referee executes untrusted code," if more than one competition ever
   needs this shape — right now it's entirely bespoke, and the failure-attribution override (item 3
   above) is exactly the kind of thing that should be a documented recipe, not something every
   author re-derives and re-verifies from scratch.
3. A multi-file submission artifact type, even a constrained one (a small tarball with a declared
   entrypoint manifest) — `research_harness`'s report already asked for this from a different angle
   (`code_archive`); this is the second independent ask for the same primitive.
4. Native tiered/staged evaluation (cheap-every-round, expensive-for-the-top-K-periodically) — not
   blocking (this competition ships without it), but likely to be asked for again by any competition
   whose full evaluation is too expensive to run at volume.

---

## Design problems this shape exposes

**"Referee owns the model" (from `research_harness`) generalizes to "referee owns the trainer," but
the SDK's trust model doesn't know the generalization happened.** The whole safety story in this
repo rests on player-holds-untrusted-code / referee-is-trusted being an invariant, not a
convention. This competition needed that invariant to bend without breaking anything else it
implies (failure attribution, screening coverage, resource isolation), and doing that safely
required understanding *why* each of those things exists, not just what they do — a much higher bar
than composing existing primitives, which is what every prior report in this repo describes doing.

**A schema that validates spec shape has no way to validate "is this execution model actually
safe."** `referee.resources` is a genuine, clean, additive schema fix. The much bigger risk in this
competition — a referee that executes fully miner-controlled code — is invisible to
`apex-dev preflight` entirely, because it's not a spec-shape problem, it's an execution-safety
problem, and the schema has no vocabulary for "this referee image runs untrusted code" as a
declared, reviewable fact. Worth a `referee.executes_submission_code: true` field, if only so a
human reviewer's attention is directed at exactly the file that needs the closest read.

---

## Limitations of this report

- **No cost, token, or wall-clock figures.** I have no `/cost` tool in this environment and no
  session transcript file to tally the way the `research_harness`/`otto` reports did — those numbers
  are genuinely unavailable to me here, not omitted for convenience. Read the token-heavy prior
  reports' methodology sections if you want a sense of how those figures would typically be derived.
- **The SDK diff line count is an isolated estimate, not a clean git diff.** `src/apex_sdk/spec.py`,
  the schema JSON, and `tests/test_spec.py` were already modified in this working tree before my
  session began (other competitions' own SDK asks — `base_model`, `private_data`, `screening` —
  are cumulative, uncommitted changes in the same files). `git diff --stat` against `HEAD` reports
  ~592 lines across those three files; I am only claiming the `referee.resources` portion
  (~130-155 lines) as mine, isolated by knowing exactly what I wrote, not by a clean commit boundary.
- **GPU execution was never exercised.** Every real run in this report — the CPU baseline
  measurement, the in-container training run — ran on CPU. This environment has no GPU passthrough
  to Docker, so `referee.resources.gpu_count: 1` has never actually been exercised end-to-end.
- **The real (CUDA) `torch` install has not itself completed a Docker build here** — see
  `DOCKER_BUILD_NOTES.md` for the exact substitution used to validate the rest of the pipeline
  instead, and why.
- **Cosign signing, registry push, and platform spec sync were not performed** — external actions
  outside what this repository or session can do.
- **The deep-eval script (`tools/run_deep_eval.py`) has two explicit `TODO`s** where it depends on
  platform infrastructure (a real round-history export, a full nanochat checkout for full-scale
  runs) that doesn't exist yet — described precisely in the code rather than silently assumed away.
- **The 2 background `Explore` agents used at the very start of this session** (reading the schema
  and the `research_harness` precedent) are not reflected in the "no subagents" framing above for
  the build/hardening work — noted for accuracy, since a stress-test of the SDK should also be
  honest about what tooling around the SDK was used.

## What is verified

- **86 SDK tests green, 34/34 competition tests green** (with nanochat available; all 20 test
  functions skip cleanly rather than fail when it isn't), full repo suite unaffected.
- **`apex-dev preflight` passes on `prod` and correctly fails on `stage`** (no GPU pool, and the
  referee's declared `cpu_limit` exceeds stage's ceiling independently) — the intended,
  GPU-only-in-prod behavior, not an accident.
- **A real baseline measurement**: 2.5773 ± 0.0606 val-bpb over 5 seeds, against a real downloaded
  ClimbMix-400B data shard and a real trained BPE tokenizer (not a stub), reproduced independently
  via `tools/local_eval.py` matching the number computed by calling `train_runner.py` directly.
- **Both competition Docker images actually built**; the referee image's full pipeline (nanochat
  fetch + verify, pinned data shard fetch + verify, tokenizer training baked at build time) ran
  successfully inside a real container, including an actual training run
  (`val_bpb: 2.602`, close to the CPU measurement) and a full `referee.py` `play_game()` call with
  a path-traversal adversarial test confirmed blocked inside the real container filesystem.
- **All four adversarial fixes independently verified against real `nanochat.gpt.GPT`**, not mocks:
  the path-traversal write, the val-split cheat, the self-reported-loss cheat, and the hang/watchdog
  each have a passing test that exercises the actual exploit, not just the fix's absence of an
  error.
- **The `referee.resources` schema addition is backward compatible**: every existing spec that never
  sets it validates unchanged (`test_referee_resources_optional_and_valid`), and the new ceiling/GPU
  gating is checked independently of the player's own `resources` block.

## What drove the design effort

Unlike the token-volume analyses in prior reports (unavailable to me here), the qualitative driver
was clear: **the two hardest problems in this competition were not "can the SDK express this
spec," they were "is the resulting execution model actually safe," and the SDK has no tooling for
the second question at all.** `referee.resources` — the one thing that *is* a schema gap — took a
JSON `$ref` extraction and 25 lines in `spec.py`. The threat model that made this competition safe
to run at all took reading real nanochat source to understand exactly what `forward(idx,
targets=None)` returns, constructing four working exploits, and verifying each fix against the real
vulnerable code path rather than the described one.

## Recommendation

Land `referee.resources` — additive, backward compatible, tested, and the second competition in
this repo (after `research_harness`'s `base_model`) to need a resourcing primitive the schema didn't
have. Treat `algo_speedrun` as the reference implementation for "the referee executes untrusted
code," and seriously consider whether that deserves first-class SDK support (a documented failure-
attribution override pattern, at minimum) rather than staying a one-off: any competition scoring a
submission by *running* it rather than *judging its output* will hit the exact same four
vulnerabilities this one did, and there is currently nothing stopping the next author from shipping
without finding them first.

The out-of-band deep-eval design (`tools/run_deep_eval.py`, `PLATFORM_PROPOSAL.md`) is a template
worth reusing for any future competition whose real evaluation cost doesn't fit inside a bounded
per-round timeout — it ships today, without waiting on native tiered-evaluation scheduling, and
names that scheduling gap explicitly as a non-blocking future ask rather than working around it
silently.
