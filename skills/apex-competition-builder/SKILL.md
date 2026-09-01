---
name: apex-competition-builder
description: Build a competition for the Apex platform (Bittensor Subnet 1) as an external designer. Use when designing a new Apex competition or authoring its `apex.competition.v1` spec, player image, and referee image for the apex-competitions-builder flow. Covers submission-format design, anti-exploit hardening, auditable per-task evaluation records, evaluation sizing for statistical significance, and resource/timeout budgeting.
---

# Building an Apex Competition (External Designer Guide)

Apex is a competition platform running as Bittensor Subnet 1. You (the competition designer) define a problem; independent **miners** submit solutions continuously; every submission is evaluated in a locked-down sandbox and ranked on a leaderboard; token emissions flow winner-takes-all to the current top miner. A new submission takes the lead only if it beats the current top **raw score by at least 1%**. That one number should drive most of your design decisions — see `reference/evaluation-design.md`.

Read first (public):

- This repo — schema, base images, `apex-dev` CLI: start with the
  [authoring guide](https://github.com/macrocosm-os/apex-competitions-builder/blob/main/docs/authoring.md)
- The worked example competition, laid out exactly like the repo you'll build (fork it): https://github.com/macrocosm-os/apex-competition-hello-world
- Full docs index (agent-friendly, one fetch): https://docs.macrocosmos.ai/llms.txt
- Platform overview: https://docs.macrocosmos.ai/subnets/subnet-1-apex
- How live competitions describe their scoring: https://docs.macrocosmos.ai/subnets/subnet-1-apex/subnet-1-current-competitions
- Incentive mechanism (emissions, burn, winner-takes-all): https://docs.macrocosmos.ai/subnets/subnet-1-apex/incentive-mechanism
- Miner-side view (CLI, submission formats, per-competition READMEs and baselines): https://github.com/macrocosm-os/apex

## Start in a separate competition repository

Never implement a competition inside the toolkit or an installed copy of this skill. Ask the user
for a destination directory outside the toolkit, then create the new repository from the
[organization-owned worked example](https://github.com/macrocosm-os/apex-competition-hello-world)
using the host's Git tools. Keep the template remote as `template-upstream` so the user can add
their own `origin`, and preserve the checked-out template commit in Git history as provenance.

The worked example already contains the vendored, top-level `gym_v1` package in both images. Keep
those copies unless deliberately updating to a different toolkit release. For an update, copy
`src/apex_sdk/gym_v1/` from one pinned toolkit tag into both `player/gym_v1/` and
`referee/gym_v1/`, then rewrite internal imports from `apex_sdk.gym_v1` to top-level `gym_v1`.
Perform every design and implementation step in the new competition repository.

## What you deliver

A competition is a **declarative, versioned, signed spec** (`apex.competition.v1`) plus the container image(s) it references. The platform never imports your code — it validates your spec, verifies and mirrors your signed images by digest, and executes them through generic runners. Nothing you write runs inside a Macrocosmos process.

| # | Deliverable | What it is |
|---|---|---|
| 1 | **`spec.yaml`** | The competition itself: kind (`solo`/`duel`), resources, submission contract, screening config, round defaults, entrypoints, images, cosign identity. Copy [hello-world's `spec.yaml`](https://github.com/macrocosm-os/apex-competition-hello-world/blob/main/spec.yaml) and edit. |
| 2 | **Player image** | Runs the miner's submission as an isolated HTTP server (`gym_v1` or `custom` protocol) that the referee drives. **Vendor the toolkit's `gym_v1/` into your repo and build on `FROM python:3.12-slim`** — do **not** use `FROM apex-player-base` (not usable yet; see *Getting the toolkit into your images* below). Digest-pinned, cosign-signed. |
| 3 | **Referee image** | Competition-owned scorer. Holds ALL domain logic: game rules, datasets, ground truth, scoring. Drives the player(s) over the per-job network and writes `/data/result.json`. Required for both solo and duel. |
| 4 | **Round generator** (optional) | `entrypoints.generate_round` in your spec: a command run once per round, in your **player** image, that reads `/data/input.json` and writes `{tasks, sandbox_data}` to its declared `output_file`. Derive everything from the master seed the platform passes in `generator_args.seed`, or the round stops being reproducible — and vary the round's *conditions*, not just its instances (design step 7). Omit it if the platform-injected per-round seed is enough. Full contract: the [authoring guide](https://github.com/macrocosm-os/apex-competitions-builder/blob/main/docs/authoring.md). |
| 5 | **Layer-2 screen image** (optional) | `entrypoints.screen`: bespoke behavioural checks in their **own** image (exit 0 = pass), so secret checks stay isolated from the player image even if the player image is made public. Aim to not need one — see design step 2. |

Plus, alongside those: an `input_schema` (JSON Schema, emitted from a pydantic model) with input fixtures, a **working baseline submission** (must score > 0; it's your integration test and your sizing instrument — not necessarily the `baseline_raw_score` you declare, which is normally 0), an **adversarial submission set** that must *not* score (design step 5), the **per-task evaluation records** your referee writes plus a tool that reads them back (design step 6), and a miner-facing README that lets miners iterate locally without leaking ground truth.

There is **no partner-side normalizer**: your referee returns `raw_score` and the platform derives leaderboard placement from it, against the baselines you declare in the spec's `defaults`.

## The architecture in one picture

```
Miner ──apex submit──▶ Apex orchestrator ──▶ queue ──▶ Apex worker
                                                          │  spawns one per-job network
                     ┌────────────────────────────────────┤
                     ▼                                    ▼
          PLAYER sandbox(es)  ◀────HTTP (gym_v1)────  REFEREE sandbox
          your player image;                          your referee image;
          submission written to                       game rules, datasets,
          submission.target_path,                     ground truth, scoring;
          served as /health /reset /act               writes /data/result.json
```

The submission and your scoring logic **never share a sandbox** — a submission can't read or patch the scorer, and the scorer's data never enters the miner-reachable container. Solo is simply a 1-player duel: same two images, one player.

Off to the side, the control plane: your spec lives in your competition repo (public or private, your choice); a Macrocosmos maintainer copies it into the private `apex-competitions-registry`, and a platform spec-syncer validates it, verifies the cosign signature, mirrors your images by digest (including private packages), and activates the version per environment. Trust = signed digests + admin-merged pointers, both reviewable in git — not repo visibility.

## Design order (do these before writing code)

### 1. Write down what success looks like — before any metric

One short paragraph stating what a winning solution should *be*, in domain terms, even if parts of it are vague or not fully understood ("a matching policy we would actually deploy: improves session quality without starving small providers, using resources a real client has"). The score is a proxy; this paragraph is the thing itself, and it is the only instrument that can tell you when the proxy has drifted.

Then make alignment with it checkable:

- Derive 2–3 concrete checks from the goal ("runs within deployment resource limits", "wins aren't concentrated in one scenario type", "the strategy is explainable").
- Each round or so, pull the top submissions and ask: do they embody the goal, or just the metric? Track secondary diagnostics that are **not** used for ranking — divergence between them and the leaderboard is your early-warning signal that miners are winning wrong.
- When score and goal drift apart, treat it as a metric bug: adjust gates or the metric between rounds (bump your spec `version`) and announce the change in the miner README. Every production competition that got surprised by miners "winning wrong" was missing this loop at launch.

The goal statement is a required section of `HANDOFF.md` and drives everything downstream: the submission format (§2), the metric and its anti-Goodhart gates (§4), the unintended scoring pathways you have to close (§5), what you reveal to miners, and the operating parameters (§8).

### 2. Pick the most constrained submission format that can express a winning solution

`submission.artifact_type` supports `onnx`, `torchscript`, and `code`. In order of preference:

1. **`onnx`** — a pure model artifact with a closed grammar. The miner sends no executable code: your player image loads the graph, validates shapes/opsets with typed errors, and serves it. Nothing to screen.
2. **`torchscript`** — still an artifact, but a TorchScript archive contains Python code by design, so it needs structural screening (the generic Layer-1 weights validator: size, magic bytes, code-to-weights ratio). Use it when ONNX can't express the model.
3. **`code`** — the miner's source runs inside the player sandbox. Attack surface is bounded by the sandbox (no egress, resource caps, timeouts) plus Layer-1 AST screening, but you now own the problem of miner code probing your protocol instead of solving your task.

Rule of thumb: if you're tempted to screen submissions for "dangerous code," first ask whether the competition can be reformulated so the submission isn't code at all. A model-artifact competition with a hard-coded architecture is strictly more robust than a "submit any code" competition with screening bolted on — and it pushes miners toward better solutions of the actual problem instead of engineering around your checks. We steer, not enforce: if code is truly required, use it, but treat that as a cost you justified, not a default.

### 3. Choose the competition kind: `solo` unless quality is inherently relative

`solo` — every submission scored independently by your referee against the round input, leadership via the 1% takeover rule — is the default (7 of 9 production competitions). Choose `duel` (head-to-head bracket; the round winner comes from the bracket, **not** the 1% rule) only when no meaningful absolute metric exists — when a solution's quality *is* how it plays against an adversary. Duels buy adversarial realism at a cost: fair mirrored matches (`duel.swap_sides` cancels first-mover advantage across games), deterministic tiebreaks, per-move deadlines, and forfeit handling (catch `PlayerError` in your referee and forfeit, don't crash) are all on you to design. Mechanically both kinds are the same two images — solo is a 1-player duel. A solo competition can still request several **isolated sandboxes of the same submission** via `solo.player_sandboxes` (the referee gets that many `PLAYER_URLS`) when distinct phases of one submission must not share memory or filesystem — e.g. compress in one sandbox, decompress in a separate one so a submission can't stash the input during compression and replay it during decompression.

### 4. Define the metric before the task

You need a single scalar `raw_score` where "1% better" is meaningful and monotone in real-world value. Decide:

- Higher-is-better or lower-is-better (both supported; declare `lower_is_better` in the spec's `defaults`).
- The raw range, and the `baseline_raw_score` you declare in `defaults`: a submission must beat `max(baseline, current_top) × 1.01` to take the lead (or `× 0.99` if lower-is-better).
- **Don't be afraid to declare a baseline of 0.** Every production competition does — 0, or for lower-is-better a bound loose enough that any valid submission clears it — which makes the first submission that scores the de facto baseline and lets the leaderboard climb from wherever the field actually starts. You are not setting a new precedent by doing the same. A non-zero floor is a number you then have to defend: pitch it above what miners reach early and the competition sits empty while emissions burn, pitch it from a reference solution you later find was buggy or over-tuned and correcting it costs a new spec `version`, re-signed and re-activated. Declare one only when scoring below some level is genuinely worthless (not merely unimpressive), and say why in `HANDOFF.md` §3. Your reference solution still matters either way — it sizes the evaluation (§8) and it is your integration test, and it must score > 0 end to end — it just doesn't have to be the leaderboard's floor.
- **Nothing in the score may be measured in wall-clock time.** Evaluations run on shared compute that can be throttled or contended, so the same submission takes different real time on two runs — and every scored term derived from `time.time()` (elapsed seconds, throughput, a latency component, a speed bonus) imports that noise straight into `raw_score`. It breaks the determinism the platform requires of you (same submission + round input + seed → same score), it makes score differences near the 1% threshold unattributable, and it hands miners a free source of resubmission variance to fish in. If speed is genuinely part of what you're measuring, measure it in units the host cannot move: simulator steps or ticks, moves to solution, number of `act` calls, nodes expanded, tokens emitted, operations counted, bytes produced. Wall clock keeps its proper job as a **boundary, not a quantity** — `deadline_ms` and `timeout_s` decide whether a response counted at all, and never how much it was worth.
- **Anti-Goodhart gates**: secondary checks in your referee that zero out degenerate solutions that game the metric without solving the problem (validity/coherence judges, efficiency or minimal-intervention penalties, NaN/Inf guards, output sanity constraints). Derive them from your success statement (§1): every way a submission could score without embodying the goal is a gate you need. Production competitions that skipped these regretted it. Metric gaming is only the polite half of the problem — §5 covers the rest, and both belong in the metric from the first version of it.

### 5. Design the scoring so the only pathway to a high score is the one you intended

Assume every submission is a rational adversary that wants the top of the leaderboard and is indifferent to your problem. Emissions are winner-takes-all and continuous, so the moment a cheaper route to a high score exists it is the dominant strategy — and production competitions have had miners find those routes within days. §4 defines the intended route; this step is where you enumerate the unintended ones and make them score nothing **in the scoring itself**. This is part of building the competition, not a hardening pass afterwards: closing a pathway later means a new spec `version` re-reviewed and re-activated while miners are already earning through the hole, so the exploit pays for as long as your fix takes.

Enumerate before you implement. For your task, write down every way a submission could place high without doing the work:

- **Attack the referee instead of the task.** Everything a player returns is attacker-controlled input to your scorer: wrong types, NaN/Inf, enormous or deeply-nested payloads, invalid unicode, out-of-range indices, responses shaped to make your scoring code raise, hang, or fall into a default branch.
- **Fail profitably.** Crashing your referee, stalling until a timeout, going unhealthy mid-match, or returning nothing must never pay more than an honest bad answer. Every "benefit of the doubt" path — partial credit for completed instances, a neutral score for a missing output, a retry after an exception, an unscored forfeit — becomes the strategy the moment it beats trying.
- **Exploit the aggregation.** Banking easy instances and timing out on hard ones, blowing up one instance's contribution to carry the mean, riding an unbounded or divide-by-small term, or making instances drop out of the denominator instead of scoring zero.
- **Reach the answer without solving.** Reconstructing ground truth from anything inside the sandbox, memoizing across calls or phases, replaying the referee's own query stream back at it, or copying the leader with a trivial perturbation once the reveal delay passes.
- **Degenerate solutions the metric happens to like** — the Goodhart cases from §4, plus constant, empty, and random submissions.

Then close each one structurally, so the defense is a property of how score is computed rather than a check bolted on top:

- Score only from what your referee observed, graded against ground truth only it holds. Treat every player response as untrusted input: validate type, shape, and range at the boundary, and make anything that fails validation a **scoreable low outcome you compute deliberately** — never an exception, never a default that carries credit.
- Make the intended path the only path that produces score. All instances are required and a missing one scores zero (never dropped from the denominator); per-instance contributions are clamped; every term is bounded and monotone; timeouts, forfeits, and malformed responses resolve to explicit low scores.
- Do the arithmetic before launch: what does a submission that returns nothing score? One that stalls to the deadline? One that kills the match? If any of them lands near the top of the distribution, the metric is wrong, not the miner.
- Ship an **adversarial submission set** alongside your baseline — empty, constant, random, malformed-response, deadline-stalling, exception-inducing, plus your own best-guess exploit. Keep them in your repo's tests; every one must score at or below your zero floor before you onboard.

**Do not describe any of this in anything a miner can read.** No "prevents cheating" comments in the referee, no anti-exploit notes in docstrings, no section in the miner README, no `anti_cheat_penalty` field in `result.json` metadata, nothing in error text beyond what was wrong with the submission. Written down, a defense is a map: it names the boundary to route around and, by omission, what you did not think of. Express these as ordinary rules of the game in domain terms — "an action scores only if it is well-formed and arrives within the deadline" is a rule; `# stop miners crashing the referee for credit` is an invitation. The one place you *do* write them down is `HANDOFF.md` §5, which reaches Macrocosmos through the private onboarding channel.

### 6. Make the evaluation leave a record of every load-bearing decision

An evaluation that returns only a scalar is unauditable. You cannot answer "why did this submission score 0.31?", you cannot show a miner their run was scored fairly, and you cannot tell whether the leader embodies your success statement (§1) or found a pathway you missed (§5). Design the record alongside the metric: **every task in an evaluation must leave a log or history file behind**, written by your referee and collected by the platform.

Load-bearing means anything that moved the score or could have — the conditions the task was drawn with, every call your referee made to the player and what came back (or which fault it raised), every gate, clamp, penalty, or validity check that fired and the value that tripped it, the terminal reason, and the per-task score with the arithmetic that produced it. If a number in `raw_score` can't be traced to a line in the record, the record is incomplete.

The platform collects these to S3 and exposes them on the miner's submission once the round completes. Pick the channel that matches your per-task unit:

| Channel | Written by | Carries |
|---|---|---|
| `metadata` in `/data/result.json` | your referee | the per-task summary — one row per task: conditions, terminal reason, score. Always present. |
| `/data/trace.jsonl` | `self.trace(event)` on the toolkit's `Referee` | a per-step event stream, one JSON object per line, when the container plays a single game. |
| `/data/history/` | your referee, one file per task | full per-task records when one referee container runs many tasks, so the natural unit is a file rather than a line. |
| the player sandbox's stdout | your player image | one line per API call the referee made — timestamp, call, latency, status — which is how a miner sees their own timing. |

What separates a record worth having from dead weight:

- **Record what replays, not what has to be re-derived.** Store the state needed to reconstruct the run directly — positions, board states, the outputs you actually scored. Re-running your simulator from a stored action list depends on bit-exact reproduction and drifts silently away from what was scored.
- **The record can never change or break the score.** Writes are best-effort: catch, log to stderr, continue. A failed artifact write must not turn a scored round into a referee failure, and a recorded evaluation must return byte-identical numbers to an unrecorded one.
- **Bound its cost.** Write each task's record as that task ends and drop the buffer, so peak memory is one task rather than the whole suite. Give yourself a stride or sampling knob plus a round-config switch, keep the terminal event whichever way the stride falls, and put the per-round size in your handoff — this is the one output that grows with the evaluation.
- **It gets revealed, so it carries conditions, not generator inputs.** Record what the task *was*; never the round seed or a per-task seed that narrows it, and nothing that lets a miner derive a later round's tasks (`reference/security-checklist.md` §1 and §3). The conditions are what the miner is owed, not what produced them.
- **Version the format and ship a reader.** Put a `format: "<name>/<major>"` field in every record, bump the major when a reader can no longer ignore a change, and provide a tool in your repo that reads both downloaded artifacts and local runs — one format, one reader, or miners won't use what you produce.
- **Assert it in CI**, or it will quietly stop working: one record per task, the numbers inside them equal to the ones in `result.json` metadata, and an unwritable artifact path leaving the score unchanged.

### 7. Make each round test something the last one didn't

A round-based competition only earns its structure if the rounds differ. If every round draws the same tasks under the same conditions, rounds are a clock rather than an experiment: the leaderboard stops measuring whether a solution works and starts measuring how thoroughly it has been fitted to one frozen set. A production competition shipped its first version this way — the same obstacle course and the same 24 friction coefficients every round — so the top submission was the one best tuned to those 24 numbers, and nothing in the score said whether the policy was robust.

Rounds are the instrument that makes solutions generalize. Design the variation before the tasks:

- **Name the axes your success statement (§1) implies.** The conditions a deployed solution would actually face and have to survive — layout, physical constants, input distribution, traffic or workload mix, noise level, opponent style, difficulty. Those are what a round varies. If you can't name an axis along which a winner should still win, you have a benchmark, not a competition.
- **Rotate conditions, not just instances.** Fresh draws from one narrow distribution are still the same test. Resample the conditions themselves each round, and derive every one of them from the master seed — `generate_round` gets `round_number` alongside `generator_args.seed`, so make the round's conditions a reproducible function of both rather than a constant baked into your image.
- **Hold difficulty stationary while conditions move.** The 1% takeover rule compares a new score against a top score earned on a *different* round's tasks, so a round that lands easier hands out an unearned lead and a harder one punishes honest miners. Keep the mix fixed — the same proportions of easy/hard strata, the same instance count — and rotate the draws inside it. Verify with your baseline: its score should be flat across rounds, and a flat baseline is also what makes the sizing measurement in §8 mean anything.
- **Keep part of the space unseen.** Reserve regions of the condition space that no launch round draws from. They are how you find out later whether the leader generalized or memorized, and they cost nothing to hold back.
- **Prove the rotation bites.** Score your baseline and a deliberately over-fitted reference (tuned hard to one round's conditions) across several rounds' conditions. If the over-fitted reference keeps pace everywhere, your rounds aren't varying anything that matters — go back to the axes.

### 8. Size the evaluation for statistical significance

If scores jump around when a submission sees new data, miners will resubmit identical solutions fishing for a lucky draw. Two defenses, use both:

- **Fix all randomness per round.** All tasks derive from one master seed per round — the platform injects `SEED` into your referee, and your optional `generate_round` entrypoint runs once per round, not per submission. Identical resubmissions then score identically — seed-fishing yields nothing. Fixed *within* a round, rotated *between* rounds along the axes from §7.
- **Evaluate enough independent task instances** that the standard error of the mean is well below the 1% takeover threshold. As a rule of thumb: **100–400 instances per evaluation** for CPU tasks, and on the order of **150 samples from a large held-out pool** for GPU/LLM tasks.

Full sizing procedure, wall-time guidance, and the variance-vs-cost trade-off: `reference/evaluation-design.md`.

Then check the size you chose against the clock, because N is bounded by the timeouts as hard as it is by variance — see the next step.

### 9. Fit the evaluation inside the timeouts before you commit to N

Two hard kill-timers bound every evaluation: `evaluate.timeout_s` for the player sandbox and `referee.timeout_s` for your scorer. You set both in the spec (the schema caps them at 7200 s; the practical ceiling is what Macrocosmos agrees at onboarding, and the wall-time target is a 1–10 minute median with 20 minutes as the hard ceiling). At the limit the sandbox is killed **without grace** — no `result.json`, no partial credit, nothing to attribute. A referee timeout is a **referee failure charged to you, not the submission**: the evaluation is unscored, the round's pipeline stalls behind it, and repeats are an incident.

So budget the worst case, not the median, and do the arithmetic before you fix N:

- **The worst case is chosen by miners, not by your baseline.** A submission that stalls every call until the deadline is legal, cheap, and will exist. Your true upper bound is `startup/readiness + N × calls_per_task × deadline_ms + your scoring work + record writes`, and `referee.timeout_s` has to cover all of it with margin. If that number doesn't fit, the fix is a tighter `deadline_ms` or a smaller N — not a bigger timeout.
- **Size the two timers against different things.** `evaluate.timeout_s` covers the player's whole lifetime including startup; `referee.timeout_s` covers the match *plus* your scoring and artifact writing. Sizing the referee from the player's budget is how designers get killed mid-scoring, with the work done and no result written.
- **Leave headroom for a slower host.** Evaluation runs on shared compute that can be throttled, so a run that fits in 95% of the budget on your laptop will not fit somewhere. Aim for the measured worst case at roughly half the timeout.
- **If it doesn't fit, say so — loudly and early.** Some tasks genuinely need more time than the envelope allows. That is a negotiation with Macrocosmos before activation, not something to discover as a stalled round: put the numbers in `HANDOFF.md` §3 (the timeout row) and §4, and state it in the onboarding issue's evaluation-time-budget field. An unflagged evaluation that doesn't fit fails as *your* referee, silently, on every submission.

### 10. Set the operating parameters deliberately

Round length, reveal delay, and submission fee are behavior knobs, not paperwork — they shape what miners do as much as the metric does. The first two travel in your spec's `defaults` (`round_length_in_days`, `submission_reveal_days`); the fee and incentive weight are platform-side and negotiated at onboarding:

- **Round length** (production: 1–2 days): shorter = faster miner turnaround and fresh seeds, but thinner competition per round; longer = deeper contests on identical tasks, but a lucky leader holds on longer.
- **Reveal delay** (production: 1 day typical, 4–7 where solutions carry real IP): shorter = ideas propagate and the field improves fast, but breakthroughs are copied within a day so miners may withhold their best work; longer = deep R&D pays, but everyone iterates against a black-box leader.
- **Submission fee** (production: ≈$1, every active competition charges one): smaller = more participants and exploration, but spam, noise, and unbounded eval spend; larger = deliberate submissions and bounded cost, but a thinner field.

Pick the corner that matches your success statement (§1). Defaults, production evidence, and the full trade-off analysis: `reference/evaluation-design.md` § Operating parameters.

### 11. Budget resources like they're your money

`resources` in the spec sets per-sandbox `cpu_limit`, `mem_limit`, `gpu_count`, capped by per-environment ceilings (stage: 2 CPU / 2Gi; prod: 4 CPU / 4Gi; memory floor 256Mi). Most competitions ship near 1 CPU / 1.5Gi. Justify every increase. GPUs are platform-gated (`gpu_count` must be 0 unless `process_type: gpu` is approved) and belong on the scoring side, almost never in the player sandbox — only 1 of 9 production competitions ever needed GPU. Tight per-move deadlines (`deadline_ms` in the gym_v1 `act` call, 0.5–5 s in production) are a feature: they force miners to submit optimized solutions and keep total evaluation time bounded. Details: `reference/evaluation-design.md`.

### 12. Walk the exploit checklist

Miners are adversarial, well-resourced, and patient. Before finalizing the design, go through `reference/security-checklist.md` end to end. The headline rules:

- **Nothing that enters the player sandbox is secret.** The round input, seeds, file paths, environment — assume the miner reads all of it. Never send a seed that can regenerate hidden data, an answer key, or validation criteria into the player sandbox. Ground truth lives only in your referee (and screen) images.
- **Reveal generously, but only after the round ends.** Per-task breakdowns, logs, and artifacts are hidden while a round is active and exposed once it completes. Rich post-round diagnostics make miners iterate faster (good for you); just never include anything that stays secret across rounds.
- **Everything a player sends the referee is untrusted input.** Validate it at the boundary and score the failure (§5); a submission must never be able to reach a high score, a default credit, or a referee crash by what it returns.
- **No internet, no persistence, no shared state.** Sandboxes get no egress (enforced by the platform regardless of your spec), per-job isolated mounts, and files deleted after eval. Players talk only to the referee, never to each other or the outside world.

## The runtime contract (what your images must implement)

Full contracts with docstrings live in the toolkit (`src/apex_sdk/gym_v1/`, `docs/authoring.md`); the essentials:

**Getting the toolkit into your images — vendor it; do NOT build FROM the base images.** The `Player`/`Referee`/`GameResult`/`PlayerClient` classes below ship in the toolkit. There is one pattern you should use today and one you must avoid:

- ✅ **Vendor (do this).** Copy the toolkit's `src/apex_sdk/gym_v1/` into your competition repo, build on `FROM python:3.12-slim`, and import the top-level package — `from gym_v1.player import Player, serve`, `from gym_v1.referee import Referee, GameResult`, `from gym_v1.client import PlayerClient`. This is what every shipped competition does and the only pattern that builds in your own repo's release CI. The [hello-world example repo](https://github.com/macrocosm-os/apex-competition-hello-world) does exactly this — copy its `player/`, `referee/`, and `.github/workflows/release.yml` layout.
- ❌ **Do NOT use `FROM apex-player-base` / `apex-referee-base` (and their `apex_sdk.gym_v1` import root) in your competition.** Those base images are **not published to any registry**, so the build only resolves on a machine that has `docker build`-ed the base locally — it will **fail in your release CI**. Build-FROM-base is the *intended* future once the bases are published; it is not usable now.

Caveat that will mislead you if you copy it blindly: the
[authoring guide](https://github.com/macrocosm-os/apex-competitions-builder/blob/main/docs/authoring.md)'s
snippets use the `apex_sdk.gym_v1` import root because that's the package name **inside the toolkit
repo**. In *your* competition repo the vendored package is top-level — drop the `apex_sdk.` prefix.

**Player image** — the platform writes the miner's artifact to `submission.target_path`, then runs `entrypoints.evaluate.command`. Your image must serve the declared `http_api` (`port`, `readiness_path`, `protocol`). For `gym_v1`, subclass the toolkit's `Player` (`reset(match_id, player_index, seed, config)` / `act(observation, deadline_ms)`) and call `serve()` — it exposes `/health`, `/reset`, `/act`. A player that never becomes healthy within the startup budget is a typed failure attributed to the submission.

**Referee image** — runs at `/app/referee.py` by convention; the platform injects `MATCH_ID`, `SEED`, `CONFIG_JSON`, `PLAYER_URLS`, `NUM_PLAYERS` and reads `/data/result.json`. For `gym_v1`, subclass the toolkit's `Referee` and implement `play_game(ctx, players) -> GameResult` (`raw_scores`, `winner`, `terminal_reason`, `steps`, plus metadata). Contract rules that matter operationally:

- **A referee crash (or missing/invalid `result.json`) is scored as a referee failure, not the submission's** — never write a zeroed result to paper over a bug; let it fail so it's attributed correctly.
- **Typed failures, never silent zeros.** An invalid submission should produce a scoreable, explained outcome the miner can act on. A valid submission that simply performs badly gets a low score, not an error. Hostile responses — wrong types, NaN, oversized payloads, deadline overruns — are part of that contract: your referee validates and scores them, and never lets one become an exception path, a dropped instance, or default credit.
- **Leave a record of every load-bearing decision** (§6): per-task rows in `metadata`, plus a per-step event stream via `self.trace(event)` → `/data/trace.jsonl` or one file per task under `/data/history/`. The platform collects both, ships them to S3, and lists them on the submission once the round completes. Write them best-effort — a failed artifact write must never fail a scored game.
- **Deterministic**: same (submission, round input, seed) → same score. Pin model revisions by full SHA, dataset files by content hash, dependency versions exactly, and keep wall-clock time out of every scored term (§4) — a score that moves with host throughput is non-deterministic by construction. Score drift between versions is indistinguishable from cheating and will be treated as an incident.
- Budget `referee.timeout_s` and `evaluate.timeout_s` explicitly against the worst case a miner can force, not your baseline's median (design step 9); the sandbox is killed without grace at the limit, and a referee that runs past it is a referee failure charged to you that stalls the round.

**Custom protocol** — if `http_api.protocol: custom`, your player serves whatever HTTP API your referee speaks (not `/reset`,`/act`) and your referee drives it directly, so you don't use gym_v1's `Player`/`serve`/`PlayerClient`. You still cross the same platform boundary, though: parse the injected env with `RefereeContext.from_env()` and write `/data/result.json` as a `GameResult` — both are protocol-agnostic, so use them instead of hand-rolling the env parsing and result shape.

**Screening** — two layers, neither is partner Python in the platform:

- *Layer 1 (declarative)*: the `screening` block in your spec configures the platform's generic screener — AST bans for `code` (`extra_forbidden_modules`, `extra_forbidden_calls`, …) or the weights validator for `torchscript`/`onnx`, plus `max_size_mb`. It's a tripwire, not the boundary — the sandbox is the actual defense, so it's fine that it's visible in the spec.
- *Layer 2 (optional, bespoke)*: `entrypoints.screen` runs your checks in a separate private image before evaluation; exit 0 = pass. Use it only for behavioural checks that must stay secret.

## Test locally, then ship

Run `apex-dev` from a separate toolkit checkout pinned to the release used by the competition. Do
not run `pip install -e .` in the competition repository and do not guess a package from PyPI.

```bash
apex-dev preflight --spec ./spec.yaml --input fixtures/input.json
apex-dev run --spec ./spec.yaml --input fixtures/input.json \
             --submission ./player/submission.py --dockerfile ./player/Dockerfile
```

`apex-dev preflight` validates your spec against `apex.competition.v1` (including resource ceilings) and your fixture against `input_schema` — a spec that passes preflight is one the platform will accept at sync time. `apex-dev run` validates the run arguments and prints the resolved execution plan; as of now it does **not** yet execute the player+referee pair locally (that harness is a toolkit follow-up), so exercise the full loop by running your two images by hand on a shared Docker network with the injected env vars, and validate on stage before launch. Test the sandboxed leg honestly: `docker run` your player with egress blocked and the spec's resource limits.

## Build checklist

- [ ] Success statement written (what a winning solution should *be*, beyond the score) with 2–3 concrete alignment checks and a plan for reviewing top submissions against it each round.
- [ ] One-sentence task definition: what the miner receives, what they return, what scalar scores it.
- [ ] Kind chosen: `solo` by default; `duel` only with a written case that quality is inherently relative (plus fair-match, tiebreak, and forfeit design).
- [ ] Submission format chosen from the constrained-format ladder above; Layer-2 screening need justified or eliminated.
- [ ] Metric + baselines (`defaults.baseline_raw_score` — 0 unless a higher floor is justified in writing) + anti-Goodhart gates defined. No scored term measured in wall-clock time — speed, if it counts, counted in host-independent units (steps, calls, moves, tokens, operations).
- [ ] Unintended scoring pathways enumerated and closed inside the scoring (design step 5): player responses validated at the boundary, no profitable failure/timeout/crash path, bounded per-instance contributions, missing instances score zero. Adversarial submission set written and scoring at or below the zero floor. None of it named or explained in comments, docstrings, metadata field names, error text, or the miner README — disclosure lives in `HANDOFF.md` §5 only.
- [ ] Every task of an evaluation leaves a record (design step 6): per-task rows in `result.json` metadata plus `/data/trace.jsonl` or `/data/history/` files, carrying conditions, player calls and faults, gates that fired, terminal reason, and the per-task score. Writes best-effort and score-neutral, size budgeted, format versioned, reader tool in the repo, asserted in CI.
- [ ] Round variation designed (design step 7): named axes of variation tied to the success statement, conditions derived per round from the master seed, difficulty distribution stationary, part of the condition space held out, and an over-fitted reference shown not to keep pace with the baseline across rounds.
- [ ] Evaluation sized per `reference/evaluation-design.md` (variance measured with your baseline across ≥20 seeds, each drawing different round conditions).
- [ ] Timeout budget worked out (design step 9): worst-case evaluation time — every call stalled to `deadline_ms` — plus scoring and record writes, fitting `referee.timeout_s` and `evaluate.timeout_s` with roughly 2× headroom. If it doesn't fit, that's stated in `HANDOFF.md` §3–4 and in the onboarding issue, with the numbers.
- [ ] Security checklist passed (`reference/security-checklist.md`).
- [ ] `spec.yaml` written from the toolkit example; `apex-dev preflight` passes; images digest-pinned and cosign-signed.
- [ ] Player + referee images implemented with the toolkit's `gym_v1/` **vendored** into the repo (`FROM python:3.12-slim`, top-level `gym_v1` imports), not `FROM apex-*-base`; full loop exercised (locally by hand, then on stage); baseline submission scores > 0 end to end.
- [ ] Miner README written — everything a miner needs to iterate locally (including how to run your player image against their own submission), nothing that leaks ground truth.
- [ ] Ops parameters proposed with reasons tied to the success statement: `round_length_in_days` (production runs 1–2), `submission_reveal_days` (1–7), submission fee in USD (≈$1 in production), incentive weight (negotiated with Macrocosmos; active competitions run 0.02–0.05), and for duels `players_per_match` / `num_games_default` / `swap_sides`. Trade-offs: `reference/evaluation-design.md` § Operating parameters.

## Onboarding with Macrocosmos

Your repo and images can be **public or private** — your choice, per artifact (most production competitions run fully private). The platform verifies and mirrors your images **by digest** and can pull private packages, so visibility is a transparency decision, not a technical gate. The registry that activates them is always private (it's the control plane), so you don't PR it directly:

1. Build + sign your image(s) with keyless cosign; push by digest; tag a release of your repo.
2. **Request review by opening a [Competition onboarding issue](https://github.com/macrocosm-os/apex-competitions-builder/issues/new?template=competition-onboarding.yml)** on the toolkit repo (`macrocosm-os/apex-competitions-builder`). This is the only way in — the registry is private, so there is nothing to PR. The form asks for a description of the competition and your success statement, your filled `HANDOFF.md` (the manifest in this skill: goal statement, ops proposal, round-variation and evaluation-sizing evidence, threat-model questionnaire), your evaluation time budget against the timeouts (design step 9 — say so plainly if it doesn't fit), your repo URL, released tag, and image refs + digests.
3. A Macrocosmos maintainer reviews (digest pinning, cosign identity, resource ceilings, the security checklist against your questionnaire answers), copies your `spec.yaml` verbatim into the private registry, and activates it on **stage first** — your baseline runs a staging round — then prod. Expect one round-trip of feedback on evaluation sizing and the reveal policy — those are the two things designers most often get wrong on the first pass.

Updating a live competition is the same loop: bump `version` in your repo (the `(id, version)` pair is immutable once synced), re-sign, and request activation of the new version.

## Reference files

- `reference/evaluation-design.md` — statistical sizing, seeds, timeouts, resource budgeting, operating guidance.
- `reference/security-checklist.md` — the full anti-exploit checklist with rationale.
- `HANDOFF.md` — the fillable onboarding manifest (deliverables, ops proposal, sizing justification, threat-model questionnaire).
- This repo (authoritative for all mechanics):
  [authoring guide](https://github.com/macrocosm-os/apex-competitions-builder/blob/main/docs/authoring.md),
  [spec schema](https://github.com/macrocosm-os/apex-competitions-builder/blob/main/src/apex_sdk/schema/apex.competition.v1.json),
  and [gym_v1](https://github.com/macrocosm-os/apex-competitions-builder/tree/main/src/apex_sdk/gym_v1) — the package you vendor.
- [apex-competition-hello-world](https://github.com/macrocosm-os/apex-competition-hello-world) — the worked example repo to fork.
