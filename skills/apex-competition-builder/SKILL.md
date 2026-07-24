---
name: apex-competition-builder
description: Build a competition for the Apex platform (Bittensor Subnet 1) as an external designer. Use when designing a new Apex competition or authoring its `apex.competition.v1` spec, player image, and referee image for the apex-competitions-sdk flow. Covers submission-format design, anti-exploit hardening, evaluation sizing for statistical significance, and resource/timeout budgeting.
---

# Building an Apex Competition (External Designer Guide)

Apex is a competition platform running as Bittensor Subnet 1. You (the competition designer) define a problem; independent **miners** submit solutions continuously; every submission is evaluated in a locked-down sandbox and ranked on a leaderboard; token emissions flow winner-takes-all to the current top miner. A new submission takes the lead only if it beats the current top **raw score by at least 1%**. That one number should drive most of your design decisions — see `reference/evaluation-design.md`.

Read first (public):

- This repo — schema, base images, `apex-dev` CLI, worked example: start with [docs/authoring.md](../../docs/authoring.md) and [examples/hello-world/](../../examples/hello-world/)
- Full docs index (agent-friendly, one fetch): https://docs.macrocosmos.ai/llms.txt
- Platform overview: https://docs.macrocosmos.ai/subnets/subnet-1-apex
- How live competitions describe their scoring: https://docs.macrocosmos.ai/subnets/subnet-1-apex/subnet-1-current-competitions
- Incentive mechanism (emissions, burn, winner-takes-all): https://docs.macrocosmos.ai/subnets/subnet-1-apex/incentive-mechanism
- Miner-side view (CLI, submission formats, per-competition READMEs and baselines): https://github.com/macrocosm-os/apex

## What you deliver

A competition is a **declarative, versioned, signed spec** (`apex.competition.v1`) plus the container image(s) it references. The platform never imports your code — it validates your spec, verifies and mirrors your signed images by digest, and executes them through generic runners. Nothing you write runs inside a Macrocosmos process.

| # | Deliverable | What it is |
|---|---|---|
| 1 | **`spec.yaml`** | The competition itself: kind (`solo`/`duel`), resources, submission contract, screening config, round defaults, entrypoints, images, cosign identity. Copy `examples/hello-world/spec.yaml` from this repo and edit. |
| 2 | **Player image** | Runs the miner's submission as an isolated HTTP server (`gym_v1` or `custom` protocol) that the referee drives. Build on the SDK's `player-base`; digest-pinned, cosign-signed. |
| 3 | **Referee image** | Competition-owned scorer. Holds ALL domain logic: game rules, datasets, ground truth, scoring. Drives the player(s) over the per-job network and writes `/data/result.json`. Required for both solo and duel. |
| 4 | **Round generator** (optional) | `entrypoints.generate_round` in your spec: an image-driven command that writes the round's tasks to a file at round start. Omit it if the platform-injected per-round seed is enough. |
| 5 | **Layer-2 screen image** (optional) | `entrypoints.screen`: bespoke behavioural checks in their **own** image (exit 0 = pass), so secret checks stay private while your player image can be public. Aim to not need one — see design step 2. |

Plus, alongside those: an `input_schema` (JSON Schema, emitted from a pydantic model) with input fixtures, a **working baseline submission** (must score > 0; it seeds the leaderboard and is your integration test), and a miner-facing README that lets miners iterate locally without leaking ground truth.

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

Off to the side, the control plane: your spec lives in your public competition repo; a Macrocosmos maintainer copies it into the private `apex-competitions-registry`, and a platform spec-syncer validates it, verifies the cosign signature, mirrors your images by digest, and activates the version per environment. Trust = signed digests + admin-merged pointers, both reviewable in git.

## Design order (do these before writing code)

### 1. Write down what success looks like — before any metric

One short paragraph stating what a winning solution should *be*, in domain terms, even if parts of it are vague or not fully understood ("a matching policy we would actually deploy: improves session quality without starving small providers, using resources a real client has"). The score is a proxy; this paragraph is the thing itself, and it is the only instrument that can tell you when the proxy has drifted.

Then make alignment with it checkable:

- Derive 2–3 concrete checks from the goal ("runs within deployment resource limits", "wins aren't concentrated in one scenario type", "the strategy is explainable").
- Each round or so, pull the top submissions and ask: do they embody the goal, or just the metric? Track secondary diagnostics that are **not** used for ranking — divergence between them and the leaderboard is your early-warning signal that miners are winning wrong.
- When score and goal drift apart, treat it as a metric bug: adjust gates or the metric between rounds (bump your spec `version`) and announce the change in the miner README. Every production competition that got surprised by miners "winning wrong" was missing this loop at launch.

The goal statement is a required section of `HANDOFF.md` and drives everything downstream: the submission format (§2), the metric and its anti-Goodhart gates (§4), what you reveal to miners, and the operating parameters (§6).

### 2. Pick the most constrained submission format that can express a winning solution

`submission.artifact_type` supports `onnx`, `torchscript`, and `code`. In order of preference:

1. **`onnx`** — a pure model artifact with a closed grammar. The miner sends no executable code: your player image loads the graph, validates shapes/opsets with typed errors, and serves it. Nothing to screen.
2. **`torchscript`** — still an artifact, but a TorchScript archive contains Python code by design, so it needs structural screening (the generic Layer-1 weights validator: size, magic bytes, code-to-weights ratio). Use it when ONNX can't express the model.
3. **`code`** — the miner's source runs inside the player sandbox. Attack surface is bounded by the sandbox (no egress, resource caps, timeouts) plus Layer-1 AST screening, but you now own the problem of miner code probing your protocol instead of solving your task.

Rule of thumb: if you're tempted to screen submissions for "dangerous code," first ask whether the competition can be reformulated so the submission isn't code at all. A model-artifact competition with a hard-coded architecture is strictly more robust than a "submit any code" competition with screening bolted on — and it pushes miners toward better solutions of the actual problem instead of engineering around your checks. We steer, not enforce: if code is truly required, use it, but treat that as a cost you justified, not a default.

### 3. Choose the competition kind: `solo` unless quality is inherently relative

`solo` — every submission scored independently by your referee against the round input, leadership via the 1% takeover rule — is the default (7 of 9 production competitions). Choose `duel` (head-to-head bracket; the round winner comes from the bracket, **not** the 1% rule) only when no meaningful absolute metric exists — when a solution's quality *is* how it plays against an adversary. Duels buy adversarial realism at a cost: fair mirrored matches (`duel.swap_sides` cancels first-mover advantage across games), deterministic tiebreaks, per-move deadlines, and forfeit handling (catch `PlayerError` in your referee and forfeit, don't crash) are all on you to design. Mechanically both kinds are the same two images — solo is a 1-player duel.

### 4. Define the metric before the task

You need a single scalar `raw_score` where "1% better" is meaningful and monotone in real-world value. Decide:

- Higher-is-better or lower-is-better (both supported; declare `lower_is_better` in the spec's `defaults`).
- The raw range, and the `baseline_raw_score` you declare in `defaults`: run your reference solution; a submission must beat `max(baseline, current_top) × 1.01` to take the lead (or `× 0.99` if lower-is-better).
- **Anti-Goodhart gates**: secondary checks in your referee that zero out degenerate solutions that game the metric without solving the problem (validity/coherence judges, efficiency or minimal-intervention penalties, NaN/Inf guards, output sanity constraints). Derive them from your success statement (§1): every way a submission could score without embodying the goal is a gate you need. Production competitions that skipped these regretted it.

### 5. Size the evaluation for statistical significance

If scores jump around when a submission sees new data, miners will resubmit identical solutions fishing for a lucky draw. Two defenses, use both:

- **Fix all randomness per round.** All tasks derive from one master seed per round — the platform injects `SEED` into your referee, and your optional `generate_round` entrypoint runs once per round, not per submission. Identical resubmissions then score identically — seed-fishing yields nothing.
- **Evaluate enough independent task instances** that the standard error of the mean is well below the 1% takeover threshold. As a rule of thumb: **100–400 instances per evaluation** for CPU tasks, and on the order of **150 samples from a large held-out pool** for GPU/LLM tasks.

Full sizing procedure, wall-time guidance, and the variance-vs-cost trade-off: `reference/evaluation-design.md`.

### 6. Set the operating parameters deliberately

Round length, reveal delay, and submission fee are behavior knobs, not paperwork — they shape what miners do as much as the metric does. The first two travel in your spec's `defaults` (`round_length_in_days`, `submission_reveal_days`); the fee and incentive weight are platform-side and negotiated at onboarding:

- **Round length** (production: 1–2 days): shorter = faster miner turnaround and fresh seeds, but thinner competition per round; longer = deeper contests on identical tasks, but a lucky leader holds on longer.
- **Reveal delay** (production: 1 day typical, 4–7 where solutions carry real IP): shorter = ideas propagate and the field improves fast, but breakthroughs are copied within a day so miners may withhold their best work; longer = deep R&D pays, but everyone iterates against a black-box leader.
- **Submission fee** (production: ≈$1, every active competition charges one): smaller = more participants and exploration, but spam, noise, and unbounded eval spend; larger = deliberate submissions and bounded cost, but a thinner field.

Pick the corner that matches your success statement (§1). Defaults, production evidence, and the full trade-off analysis: `reference/evaluation-design.md` § Operating parameters.

### 7. Budget resources like they're your money

`resources` in the spec sets per-sandbox `cpu_limit`, `mem_limit`, `gpu_count`, capped by per-environment ceilings (stage: 2 CPU / 2Gi; prod: 4 CPU / 4Gi; memory floor 256Mi). Most competitions ship near 1 CPU / 1.5Gi. Justify every increase. GPUs are platform-gated (`gpu_count` must be 0 unless `process_type: gpu` is approved) and belong on the scoring side, almost never in the player sandbox — only 1 of 9 production competitions ever needed GPU. Tight per-move deadlines (`deadline_ms` in the gym_v1 `act` call, 0.5–5 s in production) are a feature: they force miners to submit optimized solutions and keep total evaluation time bounded. Details: `reference/evaluation-design.md`.

### 8. Walk the exploit checklist

Miners are adversarial, well-resourced, and patient. Before finalizing the design, go through `reference/security-checklist.md` end to end. The headline rules:

- **Nothing that enters the player sandbox is secret.** The round input, seeds, file paths, environment — assume the miner reads all of it. Never send a seed that can regenerate hidden data, an answer key, or validation criteria into the player sandbox. Ground truth lives only in your referee (and screen) images.
- **Reveal generously, but only after the round ends.** Per-task breakdowns, logs, and artifacts are hidden while a round is active and exposed once it completes. Rich post-round diagnostics make miners iterate faster (good for you); just never include anything that stays secret across rounds.
- **No internet, no persistence, no shared state.** Sandboxes get no egress (enforced by the platform regardless of your spec), per-job isolated mounts, and files deleted after eval. Players talk only to the referee, never to each other or the outside world.

## The runtime contract (what your images must implement)

Full contracts with docstrings live in the SDK (`src/apex_sdk/gym_v1/`, `docs/authoring.md`); the essentials:

**Player image** — the platform writes the miner's artifact to `submission.target_path`, then runs `entrypoints.evaluate.command`. Your image must serve the declared `http_api` (`port`, `readiness_path`, `protocol`). For `gym_v1`, subclass the SDK's `Player` (`reset(match_id, player_index, seed, config)` / `act(observation, deadline_ms)`) and call `serve()` — it exposes `/health`, `/reset`, `/act`. A player that never becomes healthy within the startup budget is a typed failure attributed to the submission.

**Referee image** — runs at `/app/referee.py` by convention; the platform injects `MATCH_ID`, `SEED`, `CONFIG_JSON`, `PLAYER_URLS`, `NUM_PLAYERS` and reads `/data/result.json`. For `gym_v1`, subclass the SDK's `Referee` and implement `play_game(ctx, players) -> GameResult` (`raw_scores`, `winner`, `terminal_reason`, `steps`, plus metadata). Contract rules that matter operationally:

- **A referee crash (or missing/invalid `result.json`) is scored as a referee failure, not the submission's** — never write a zeroed result to paper over a bug; let it fail so it's attributed correctly.
- **Typed failures, never silent zeros.** An invalid submission should produce a scoreable, explained outcome the miner can act on. A valid submission that simply performs badly gets a low score, not an error.
- **Deterministic**: same (submission, round input, seed) → same score. Pin model revisions by full SHA, dataset files by content hash, dependency versions exactly. Score drift between versions is indistinguishable from cheating and will be treated as an incident.
- Budget `referee.timeout_s` and `evaluate.timeout_s` explicitly; the sandbox is killed without grace at the limit.

**Custom protocol** — if `http_api.protocol: custom`, your player serves whatever HTTP API your referee speaks (not `/reset`,`/act`) and your referee drives it directly, so you don't use gym_v1's `Player`/`serve`/`PlayerClient`. You still cross the same platform boundary, though: parse the injected env with `RefereeContext.from_env()` and write `/data/result.json` as a `GameResult` — both are protocol-agnostic, so use them instead of hand-rolling the env parsing and result shape.

**Screening** — two layers, neither is partner Python in the platform:

- *Layer 1 (declarative)*: the `screening` block in your spec configures the platform's generic screener — AST bans for `code` (`extra_forbidden_modules`, `extra_forbidden_calls`, …) or the weights validator for `torchscript`/`onnx`, plus `max_size_mb`. It's a tripwire, not the boundary — the sandbox is the actual defense, so it's fine that it's visible in the spec.
- *Layer 2 (optional, bespoke)*: `entrypoints.screen` runs your checks in a separate private image before evaluation; exit 0 = pass. Use it only for behavioural checks that must stay secret.

## Test locally, then ship

```bash
pip install -e .        # the SDK
apex-dev preflight --spec ./spec.yaml --input fixtures/input.json
apex-dev run --spec ./spec.yaml --input fixtures/input.json \
             --submission ./player/submission.py --dockerfile ./player/Dockerfile
```

`apex-dev preflight` validates your spec against `apex.competition.v1` (including resource ceilings) and your fixture against `input_schema` — a spec that passes preflight is one the platform will accept at sync time. `apex-dev run` validates the run arguments and prints the resolved execution plan; as of now it does **not** yet execute the player+referee pair locally (that harness is an SDK follow-up), so exercise the full loop by running your two images by hand on a shared Docker network with the injected env vars, and validate on stage before launch. Test the sandboxed leg honestly: `docker run` your player with egress blocked and the spec's resource limits.

## Build checklist

- [ ] Success statement written (what a winning solution should *be*, beyond the score) with 2–3 concrete alignment checks and a plan for reviewing top submissions against it each round.
- [ ] One-sentence task definition: what the miner receives, what they return, what scalar scores it.
- [ ] Kind chosen: `solo` by default; `duel` only with a written case that quality is inherently relative (plus fair-match, tiebreak, and forfeit design).
- [ ] Submission format chosen from the constrained-format ladder above; Layer-2 screening need justified or eliminated.
- [ ] Metric + baselines (`defaults.baseline_raw_score`) + anti-Goodhart gates defined.
- [ ] Evaluation sized per `reference/evaluation-design.md` (variance measured with your baseline across ≥20 seeds).
- [ ] Security checklist passed (`reference/security-checklist.md`).
- [ ] `spec.yaml` written from the SDK example; `apex-dev preflight` passes; images digest-pinned and cosign-signed.
- [ ] Player + referee images implemented on the SDK bases; full loop exercised (locally by hand, then on stage); baseline submission scores > 0 end to end.
- [ ] Miner README written — everything a miner needs to iterate locally (including how to run your public player image against their own submission), nothing that leaks ground truth.
- [ ] Ops parameters proposed with reasons tied to the success statement: `round_length_in_days` (production runs 1–2), `submission_reveal_days` (1–7), submission fee in USD (≈$1 in production), incentive weight (negotiated with Macrocosmos; active competitions run 0.02–0.05), and for duels `players_per_match` / `num_games_default` / `swap_sides`. Trade-offs: `reference/evaluation-design.md` § Operating parameters.

## Onboarding with Macrocosmos

Your competition repo, `spec.yaml`, and signed player image are public; the registry that activates them is private (it's the control plane), so you don't PR it directly:

1. Build + sign your image(s) with keyless cosign; push by digest; tag a release of your repo.
2. Open a **Competition onboarding issue** on this repo with your repo URL, released tag, and image refs + digests, and attach `HANDOFF.md` — the manifest in this skill: goal statement, ops proposal, evaluation-sizing evidence, and the threat-model questionnaire.
3. A Macrocosmos maintainer reviews (digest pinning, cosign identity, resource ceilings, the security checklist against your questionnaire answers), copies your `spec.yaml` verbatim into the private registry, and activates it on **stage first** — your baseline runs a staging round — then prod. Expect one round-trip of feedback on evaluation sizing and the reveal policy — those are the two things designers most often get wrong on the first pass.

Updating a live competition is the same loop: bump `version` in your public repo (the `(id, version)` pair is immutable once synced), re-sign, and request activation of the new version.

## Reference files

- `reference/evaluation-design.md` — statistical sizing, seeds, timeouts, resource budgeting, operating guidance.
- `reference/security-checklist.md` — the full anti-exploit checklist with rationale.
- `HANDOFF.md` — the fillable onboarding manifest (deliverables, ops proposal, sizing justification, threat-model questionnaire).
- This repo (authoritative for all mechanics): [docs/authoring.md](../../docs/authoring.md), [examples/hello-world/](../../examples/hello-world/), [the spec schema](../../src/apex_sdk/schema/apex.competition.v1.json), [src/apex_sdk/gym_v1/](../../src/apex_sdk/gym_v1/).
