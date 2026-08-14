# Evaluation Design: Statistical Significance, Seeds, Timeouts, Resources

The platform's core mechanic — take the lead by beating the top raw score by 1% — only works if your evaluation is precise enough that a 1% difference means skill, not luck. This file gives the sizing procedure and operating guidance to calibrate against. The concrete numbers are strong priors drawn from operating the platform — but measure your own competition rather than trusting them blindly.

## The seed-fishing exploit, and the two defenses

If evaluation randomness varies per submission, a miner can resubmit the *same* solution repeatedly, and the maximum of N noisy draws will eventually clear the 1% bar. This is the single most common design flaw. Defend in depth:

**Defense 1 — one seed per round, same for everyone.** All randomness derives from one per-round master seed: your `generate_round` entrypoint runs once at round start (not per submission), and the platform injects the same `SEED` into your referee for every evaluation in the round — so every submission is evaluated on exactly the same task instances. Identical resubmissions score identically → resubmitting buys nothing. Rotate the seed every round so solutions can't overfit a frozen instance set — and rotate what the seed *decides*, per the next section. Production evidence: every production competition derives all instances from one per-round master seed. Rounds are short (1–2 days), so overfitting pressure per round is bounded.

**Defense 2 — enough instances that between-round variance is small.** Fixing the seed within a round still leaves round-to-round variance: a leader who got lucky on this round's seed holds the lead unfairly, and honest miners see their score jump when the round rolls. Size N so the score is a stable property of the solution.

## What has to change between rounds

Rotating the seed is necessary but not sufficient. If the seed only reshuffles draws from one narrow, unchanging distribution, every round poses the same question and the leaderboard converges on whichever submission is most thoroughly fitted to it — the failure mode SKILL.md design step 7 opens with (identical course, identical 24 friction coefficients, every round). A round is worth running only if it can disconfirm something the last round asserted.

- **Vary the conditions, hold the difficulty.** Rotate the parameters a deployed solution would face (layout, constants, distribution, workload mix, noise, opponent style); keep the instance count and the easy/hard stratum proportions fixed. Conditions moving makes solutions generalize; difficulty moving makes the cross-round comparison behind the 1% takeover rule meaningless, because a new score is always compared against a top score earned on other tasks.
- **Sample conditions from the master seed.** `generate_round` receives `round_number` with `generator_args.seed`; derive the round's conditions from both so they are reproducible from the round rather than baked into an image you'd have to re-release to change.
- **Hold out part of the space.** Keep regions of the condition space that no live round draws from, and score the leader against them out of band. It's the cheapest available test of whether the winner generalized.
- **Measure the two variances separately.** Baseline score variance *within* fixed conditions is sampling noise and shrinks as √N. Baseline score variance *across* condition sets is difficulty drift and doesn't — no N fixes it, only a stationary stratum mix does. The sizing procedure below conflates them unless you check both: your baseline should be flat across condition sets, and the ≥20 master seeds you measure with should each draw a different one, or σ_round understates what miners actually see when the round rolls.
- **Test with an over-fitted reference.** Tune a reference solution hard to one round's conditions, then score it across several. If it keeps pace with the baseline everywhere, the rounds are not varying anything the metric responds to.

## Sizing procedure

1. Implement your baseline and one or two deliberately different reference solutions.
2. Evaluate each on ≥ 20 different master seeds with your candidate N (instances per evaluation) — each seed drawing the round conditions it would draw live, not one fixed set. Compute the per-seed score's standard deviation σ_round.
3. Require **σ_round ≲ ¼ of the takeover margin**, i.e. `σ_round ≤ 0.0025 × typical_score` (the margin is 1% of the top score). Since σ_round ≈ σ_task / √N, solve for N.
4. Check separability: your reference solutions should rank consistently across all 20 seeds. If two solutions of genuinely different quality swap ranks between seeds, N is too small (or your metric is too coarse).
5. Re-check total evaluation cost: `N × per-instance time` must fit the wall-time envelope below. If it doesn't, reduce variance instead of just raising N: common random numbers (all solutions see identical instances — you already have this from Defense 1), paired comparison against the baseline on the same instances, stratified instance mixes (fixed proportions of easy/hard scenario types), and capping per-instance score contributions to stop single-instance blowups dominating.

Duel competitions size differently: there is no N to raise — variance is handled by the bracket structure (a lucky game win still has to survive every subsequent bracket round), a few games per pairing (`duel.num_games_default`, with `swap_sides: true` to cancel first-mover advantage), and **deterministic tiebreaks**. The sizing question becomes "how many games per match make the better policy win reliably" — measure by playing your baseline against a deliberately weaker reference and checking that the win rate is near-certain at your chosen games-per-match.

## Cost and wall-time envelope

Rules of thumb for where N lands by archetype:

- **Cheap per-instance tasks** (scoring outputs against a dataset metric): drive N high — several hundred instances still fits well under a minute.
- **Expensive simulator instances**: lean on the variance-reduction techniques above rather than raw N — around a hundred instances is often the practical ceiling.
- **Games against a fixed baseline opponent**: game outcomes are high-variance; expect to need the high end (hundreds of games).
- **Interactive episodes** (long sequential evaluations): a handful of episodes with per-episode analytic ceilings, since episode count is bounded by wall time.
- **Head-to-head duels**: a few games per match — variance is handled by the bracket structure and deterministic tiebreaks, not N.
- **Model artifacts scored on a GPU pool**: sample on the order of 100–200 items per round from a held-out pool large enough that cross-round leakage is slow; the per-round seed selects the sample.

Your evaluation cost is multiplied by submission volume for the lifetime of the competition — for example, a 20-minute evaluation at 200 submissions/day is 66 machine-hours/day, forever. Rounds run 1–2 days, and the per-submission fee (set per competition in USD, paid in TAO) does the economic anti-spam work — active miners settle at a few submissions per day in practice.

Budget the evaluation records too (SKILL.md design step 6). They cost almost no wall time — a copy per step — but they are the one output whose size scales with N and with episode length, so estimate the per-round bytes at your chosen N, expose a stride/sampling knob and an off switch in the round config, and write each task's record as it ends rather than buffering the suite.

Wall-time guidance: aim for a **median evaluation of 1–10 minutes**; treat **20 minutes as the hard ceiling**. Miners iterate against your feedback loop — a 2-minute eval gets you an order of magnitude more iteration than a 20-minute one.

## Operating parameters: round length, reveal delay, submission fee

Three knobs sit outside the evaluation itself but shape miner behavior as much as the metric does. Production defaults below are what we actually run, not theory — deviate with a reason, and put that reason in HANDOFF.md.

**Round length — production default 1–2 days.**

- *Shorter* → faster miner turnaround: seeds rotate more often (less per-round overfitting pressure), a lucky or overfit leader is dethroned at the next reset, and miners get fresh instances to learn from sooner. But each round holds fewer competing submissions, so a round can be won thin, and per-round overhead (baseline scoring, fleet spin-up, generation) amortizes over less work.
- *Longer* → a deeper contest per round — more submissions face the exact same tasks, which is the fairest possible comparison. But whoever leads holds the lead longer on a frozen instance set, and the feedback rhythm slows for everyone.
- 1–2 days is the deliberate middle. Go longer only if round generation is genuinely expensive to amortize; go shorter only if your per-round submission volume can sustain it.

**Reveal delay — production default 1 day; range 1–7.**

The reveal is the platform's engine for compounding improvement: after `submission_reveal_days`, a submission's code/artifact is downloadable by other miners, so everyone restarts from the frontier. The delay prices innovation:

- *Shorter* → ideas propagate fast and the floor rises quickly across the field. But first-mover advantage shrinks — a genuine breakthrough only earns for a day before being copied, so sophisticated miners may withhold their best ideas or under-invest for fear of losing their IP the moment it works.
- *Longer* → deep work pays: an innovator holds an uncopyable lead for the window, which justifies real R&D. But the rest of the field iterates against a black-box leader (disengagement risk), and collective progress steps instead of flows.
- Production practice: 1 day where iteration is cheap and incremental; 4–7 days where a winning solution embodies real IP (trained policies, interactive strategies). Match the delay to how expensive a genuine improvement is to produce — the more R&D a leap costs, the longer it should stay protected.

**Submission fee — production default ≈ $0.70–1.00 (USD-denominated, paid in TAO); every active competition charges one.**

- *Smaller / zero* → maximum participation and shots-on-goal, including the exploratory long tail where surprises come from. But low-effort volume dominates: resubmit-with-noise becomes free, your evaluation bill scales with spam, and median submission quality drops. Experience on the platform: introducing fees traded raw volume for deliberateness — spam and resubmission-fishing dropped sharply, and evaluation spend became predictable.
- *Larger* → every submission carries intent and your compute cost is bounded. But you filter out newcomers, cheap experiments, and small miners — and a thin field defeats the purpose of running an open competition.
- Sizing rule: the fee should be at least roughly your marginal cost of evaluating one submission, and high enough that seed-fishing/resubmission strategies are clearly negative-EV (the fixed per-round seed already makes them useless — the fee makes them costly too). ~$1 has been the workable point in production.

These three interact: short rounds + short reveal + low fee maximizes iteration speed and noise; long rounds + long reveal + higher fee selects for fewer, deeper attempts. Pick the corner that matches what "success" looks like for your competition (SKILL.md design step 1), not a default posture.

## Timeouts

- **Whole-evaluation hard timeouts** (`evaluate.timeout_s` for the player, `referee.timeout_s` for the scorer): startup + N × per-instance budget + buffer. The sandbox is killed without grace at the limit; a player timeout should be a scoreable outcome your referee reports (score 0, or partial credit for completed instances) with a reason the miner can see. If you allow partial credit, check what it pays before shipping it: unfinished instances must score zero and stay in the denominator, or timing out on the hard ones becomes the winning strategy (security-checklist §9).
- **Per-move deadlines** (`deadline_ms` in the gym_v1 `act` call): 0.5–5 s per move/route/call in production. Tight per-call limits are a design tool, not just protection: they force miners to optimize latency, which is usually part of what you actually want, and they bound worst-case evaluation time by construction.
- **Startup budget**: separate from the run budget — the platform polls your player's `readiness_path` before the referee starts driving it. A player that never becomes healthy is a typed failure attributed to the submission, not a hang.
- **Referee budget**: size `referee.timeout_s` for the whole match including your scoring work; a referee that exceeds it is a referee failure attributed to you, not the submissions — and it stalls the round's pipeline while it happens.

## Resources: the minimalism doctrine

Every resource you grant is attack surface plus cost plus an excuse for less-optimized submissions. Your spec's `resources` block sets per-sandbox `cpu_limit` / `mem_limit` / `gpu_count`, capped by per-environment ceilings (stage: 2 CPU / 2Gi; prod: 4 CPU / 4Gi; memory floor 256Mi). The production norm is **~1 CPU, 1.5Gi, no egress, timeouts in the tens of seconds**. Increases that were actually justified in production: memory to a few GB for data-heavy tasks, run timeout to minutes for simulators. Increases that were requested and refused: GPUs in the player sandbox "for flexibility," internet access "to download packages."

Decision guide:

- **Does the miner artifact need a GPU?** Almost certainly not. In production, 8 of 9 competitions are CPU-only end to end; the one GPU competition uses GPUs **only on the scoring side** — the submission itself is a small tensor file. `gpu_count` must be 0 unless `process_type: gpu` is approved by the platform. If inference of the miner's model needs acceleration, prefer constraining the model size until CPU inference fits the per-move deadline; small-model constraints usually improve the deployed usefulness of the winning solution anyway.
- **Internet?** No — egress is blocked by the platform regardless of your spec. If the evaluation genuinely needs external data (big datasets, LLM judges), bake it into the **referee image**, pinned and content-hashed. The player talks only to the referee over the per-job network; the miner's artifact must be self-contained.
- **Dependencies in the player image**: pin exact versions, keep the list minimal. Every extra package is both attack surface and a hidden solution-space constraint you'll have to support forever.
- Set memory/CPU so your **baseline uses ≤ 50%** — headroom is for better solutions, not for waste. Watch recorded per-run metrics (CPU seconds, peak memory, I/O) after launch to spot both abuse and over-provisioning.
