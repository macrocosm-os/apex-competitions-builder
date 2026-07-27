# Competition Onboarding Manifest: `humanoid_parkour`

Fill this document completely and attach it to your **Competition onboarding
issue** on this repo (together with your repo URL, released tag,
and image refs + digests). Macrocosmos reviews it, copies your `spec.yaml`
into the private registry, and activates it on stage — where your baseline
runs a staging round — before going live. Incomplete sections are the most
common cause of a delayed launch.

> What Macrocosmos decides unilaterally: the final incentive weight, the
> submission fee, activation timing, and whether extra screening is required
> after security review. Everything else below is your proposal and will be
> discussed, not silently changed.

## 1. Goal statement & alignment plan

**What success looks like** (one paragraph, domain terms — what a winning
solution should *be*, not what score it gets; vague is acceptable, absent is
not):

> Humanoid robot completing an obstacle course (simulated MuJoCo environment) in the least amount of time without falling down.

**Alignment checks** (2–3 concrete, checkable properties derived from the
goal) and **review plan** (what you will inspect in top submissions each
round, and which non-ranking diagnostics you will watch for score/goal
divergence):

- The only part of the robot that is used for locomotion is the legs —
  enforced by the fall gate (torso z < 1.0 m or any non-foot geom contacting
  the floor ends the episode); hurdle-touch behaviour of top submissions is
  reviewed manually (see cadence below).
- No modifications to the robot or obstacle course is allowed — structural:
  the submission is a pure ONNX policy graph; the referee owns the MJCF and
  physics, and the player sandbox never receives them.
- No glitches in the physics simulation are allowed — NaN/Inf state or
  |qvel| > 100 terminates the instance with score 0 (`physics_glitch`).
- Review cadence & method: every 3 rounds, replay the top 10 submissions'
  trajectories and check they embody the goal (upright legged running, not
  hurdle-vaulting on hands, bound-hugging, or solver abuse). Non-ranking
  diagnostics watched for divergence: distribution of terminal reasons,
  per-difficulty completion rates, mean |y| (bound-hugging), and step-function
  raw-score jumps across many miners in one round.

## 2. Deliverables

| Item | Where | Done |
|---|---|---|
| Competition repo (public) + released tag | `competitions/humanoid-parkour/` in this repo — to graduate to its own public repo (e.g. `macrocosm-os/apex-competition-humanoid-parkour`) before onboarding | ☐ |
| `spec.yaml` (`apex.competition.v1`) — `apex-dev preflight` passes | `competitions/humanoid-parkour/spec.yaml` (preflight ✓ 2026-07-27) | ☑ |
| Player image | `ghcr.io/macrocosm-os/apex-competition-humanoid-parkour-player@sha256:<digest>` — Dockerfile ready, build/sign/push pending | ☐ |
| Referee image | `ghcr.io/macrocosm-os/apex-competition-humanoid-parkour-referee@sha256:<digest>` — Dockerfile ready, build/sign/push pending | ☐ |
| Layer-2 screen image — or written justification for why none is needed (§5) | n/a — ONNX artifact with a closed interface ([1,56]→[1,17], float32, ≤25 MB); structural validation in the public player loader + Layer-1 weights validator. No code enters the sandbox, so no behavioural screen is required. | ☑ |
| Round-generation entrypoint (`generate_round`) — or "platform seed is enough" | Platform seed is enough: the referee derives all 24 courses deterministically from `SEED` via `SeedSequence` | ☑ |
| Cosign identity + issuer (as declared in the spec `signature` block) | `<release workflow of the graduated repo>` — placeholder in spec | ☐ |
| `input_schema` + input fixtures | `input.schema.json`, `fixtures/input.json` | ☑ |
| Baseline submission (scores > 0 through the full player+referee loop) | `baseline/train_baseline.py` (PPO → ONNX recipe); training run pending. Loop itself verified end to end with a random-policy ONNX (raw 0.0039 > 0, all gates typed) | ☐ |
| Miner-facing README | `competitions/humanoid-parkour/README.md` | ☑ |
| Evidence of a full end-to-end run (local two-image run or stage round) | Local two-process run (real player server + real referee over HTTP, no Docker) ✓; two-image Docker run pending image builds | ◐ |

Everything that affects scores must be pinned: image digests (`@sha256:`),
model revisions (full 40-char SHA), dataset content hashes, dependency
versions. List every pin here:

- model revision: n/a (no pretrained models in the eval path)
- dataset hash(es): vendored `env/assets_humanoid.xml` (Gymnasium humanoid MJCF)
  sha256 `85816f372c826d2094b4a598918233bd9c5843b2439119eece2733bdc2e0d073`
- dependency pins: `mujoco==3.10.0`, `numpy==2.3.4` (referee);
  `onnxruntime==1.28.0`, `numpy==2.3.4` (player) — single-threaded ORT session
  for determinism

## 3. Ops parameters (your proposal — each with a one-line reason tied to §1)

Spec-carried values must match your `spec.yaml`; the rest are negotiated at
onboarding.

| Parameter | Where it lives | Proposal | Production norm |
|---|---|---|---|
| `process_type` | spec | cpu — MuJoCo + small ONNX policy, no GPU anywhere in the loop | cpu (gpu needs §6 justification and is platform-gated) |
| `kind` | spec | solo — completion time is an absolute metric; no adversary needed | solo (7 of 9; duel needs a written case) |
| `duel` block (duels only) | spec | n/a | 2 players, swap_sides: true |
| `defaults.round_length_in_days` | spec | 2 — deeper contest per round on identical courses; RL policies take real time to train, so 1-day rounds would thin out | 1–2 days |
| `defaults.submission_reveal_days` | spec | 5 — a trained locomotion policy is genuine R&D (docs guidance: 4–7 where solutions carry real IP); protects a breakthrough long enough to pay for it | 1–7 days |
| `defaults.lower_is_better` | spec | false — score rewards completion + speed (see §1 metric); pure lower-is-better time gives no gradient before anyone completes | — |
| `defaults.baseline_raw_score` / `baseline_score` | spec | **PLACEHOLDER 0.05 / 0.0 — must be measured with the trained PPO baseline via `tools/measure_variance.py` before onboarding** | measured, not guessed |
| `resources` (per sandbox) | spec | 1 CPU / 1.5Gi — measured sim cost 0.39 ms per control step; baseline uses well under 50% | ~1 CPU / 1.5Gi (ceilings: stage 2 CPU / 2Gi, prod 4 CPU / 4Gi) |
| `evaluate.timeout_s` / `referee.timeout_s` | spec | 900 / 900 — measured worst case (24 courses × 1200 steps, sim+HTTP+inference) ≈ 1–2 min for an MLP, ≈ 6 min headroom for a slow 25 MB policy | median eval 1–10 min |
| Per-move deadline (`deadline_ms`, gym_v1) | referee config (round input) | 500 ms — typical policy inference is ~1 ms; 500 ms tolerates jitter while forcing CPU-fast policies | 0.5–5 s |
| Submission fee | platform | ≈$1 — standard anti-spam; eval cost is low so no higher fee needed | ≈$1 (the anti-spam mechanism; final: Macrocosmos) |
| Incentive weight | platform | 0.03 (mid-range; Macrocosmos decides) | 0.02–0.05 (final: Macrocosmos) |

## 4. Evaluation-sizing justification (required paragraph)

Written evidence, not intent — run the procedure in
`reference/evaluation-design.md` and report:

- Instances per evaluation (N): 24 (8 easy / 8 medium / 8 hard, stratified so
  no tier dominates the round-to-round variance)
- Measured σ_round across ≥20 master seeds with the baseline: **TBD — run
  `tools/measure_variance.py --onnx baseline.onnx --seeds 20` after the
  baseline trains** (attach the numbers)
- Typical top score and the resulting takeover margin (1%): TBD (expected
  ~1.3–1.6 once policies complete most courses → margin ~0.013–0.016)
- Check: σ_round ≤ ¼ × margin? TBD + arithmetic. Mitigations already in
  place: within-round score is fully deterministic (fixed seed, deterministic
  MuJoCo, single-threaded ORT — verified bit-identical across repeat runs),
  common random numbers (every submission sees identical courses), stratified
  difficulty mix, per-instance score capped at 2.0. If σ_round fails the
  check, raise `courses_per_difficulty` (wall-time headroom is ~10×).
- Reference solutions rank consistently across all seeds? TBD — compare the
  trained baseline vs. a half-trained checkpoint across the same 20 seeds.
- Total evaluation wall time at N: measured ≈ 100–130 s worst case for an MLP
  policy (0.39 ms sim + ~1.1 ms HTTP/inference per control step, 28.8k steps
  max); early-falling policies finish in seconds (fits `timeout_s: 900`)

## 5. Threat-model questionnaire (all answers required, "n/a" must say why)

1. **Miner-visible surface.** Round input: `courses_per_difficulty`,
   `max_steps_per_episode`, `deadline_ms` (eval shape only — public knobs, no
   leverage). Observation stream: proprioception (qpos/qvel), torso y,
   distance-to-finish, and the geometry of the next 3 hurdles — exactly what a
   deployed controller would sense; the courses being observed are this
   round's only, and they expire with the round. `reset` passes the per-course
   seed to the player, which is safe because course generation happens in the
   referee — the seed alone regenerates nothing without being fed to the
   generator, and the generator's input (course layout) is observable through
   the observation stream anyway. Env/config: nothing else enters the player
   sandbox.
2. **Seed leverage.** The master round SEED is injected only into the referee.
   Per-course seeds visible to the player derive from it via
   `SeedSequence([seed, difficulty_index])` — one-way; they cannot be inverted
   to the master seed nor extrapolated to future rounds (fresh master seed per
   round). The course generator is deliberately public (miners must train on
   the distribution); knowing it plus all of this round's courses predicts
   nothing about next round's draws.
3. **Degenerate submissions.** Constant/zero/random policies: the humanoid
   falls within ~15 control steps → progress ≈ 0.004, raw ≈ 0.004 (measured
   with a random-weight MLP). They score near-zero naturally, never place, and
   a policy producing NaN or wrong shapes is a typed `invalid_action` → 0.
   Near-empty graphs are rejected by Layer-1 (`min_weight_bytes: 10000`).
4. **Baseline resubmission.** Scores exactly the baseline raw score
   (evaluation is deterministic per round) — below the current top by
   construction and short of the 1.01× takeover threshold; it can never take
   or hold the lead.
5. **Metric gaming.** Probed so far, each with a closing gate: run around the
   hurdles → `out_of_bounds` (|y| > 2, hurdles overhang the bounds so corners
   can't be clipped); crawl/knee-slide under the fall threshold → non-foot
   floor-contact gate; dive across the line → progress requires torso x, and a
   fall ends the episode at that x (a 20 m dive is not achievable at these
   torques); glitch-surfing (solver explosions launching the body) →
   `physics_glitch` zero at |qvel| > 100 or NaN; stand still to farm the
   timeout → timeout pays progress only, ≈ 0. **Remaining pre-launch task: a
   full adversarial day on the trained baseline (e.g. hurdle-clipping at
   contact margins, tanh-saturation exploits), per security-checklist §8.**
6. **Copy-plus-epsilon.** After the 5-day reveal a copied policy scores
   identically to the original (deterministic eval) — a trivial perturbation
   of weights scores the same or worse and cannot clear the 1% takeover bar.
   Beating the leader requires genuinely better locomotion, which is exactly
   the R&D the reveal window prices.
7. **Cross-round leakage.** A full round reveals: 24 course layouts (expired),
   the referee's query cadence (fixed: one `/act` per control step — nothing
   to learn), and per-course diagnostics. Courses never repeat across rounds
   (fresh master seed, ~2^128 SeedSequence space); hard-coding this round's
   answers has zero transfer. The durable thing miners extract is a better
   general policy — that's the point.
8. **Error-message hygiene.** Player-visible failures are typed terminal
   reasons only (`fell`, `out_of_bounds`, `physics_glitch`, `invalid_action`,
   `player_error`, `timeout`). The ONNX loader's rejection messages state the
   violated interface constraint (shape/dtype/count) — all of it documented in
   the public README anyway. No thresholds or internals beyond what is public.
9. **Referee state.** Stateless across games and matches: courses are rebuilt
   from the injected seed each run, `MjData` is reset per instance, no caches
   or temp files; nothing keyed on submission-controlled values (the referee
   never touches submission bytes at all — only observation/action vectors
   cross the boundary).
10. **Code execution.** n/a — `artifact_type: onnx`. No code enters the player
    sandbox; ONNX cannot smuggle executable code the way TorchScript can.
    Structural checks: Layer-1 weights validator (25 MB cap, min weight bytes,
    code-to-weights ratio) plus the player loader's typed interface validation
    (single float32 [·,56] input, single [·,17] output, CPU EP only).
11. **Public-image hygiene.** Player image contains only `launch.py` (ONNX
    serving + validation) — no course generator, no seeds, no scoring. The
    repo's `env/` (physics, generator, scoring) is deliberately public as the
    training kit; there is no held-out ground truth in this competition — the
    per-round secret is only the master seed, which lives exclusively in the
    referee's injected env.
12. **Diagnostics payload.** `result.json` metadata: per-course difficulty,
    terminal reason, progress, steps, sim time, score, plus totals and eval
    wall time. All of it describes the miner's own trajectories on expired
    courses; none of it correlates with any future round's data.

## 6. GPU justification (only if `process_type: gpu`)

n/a — `process_type: cpu`. Player runs a ≤25 MB ONNX policy single-threaded on
CPU (~1 ms/inference); referee runs MuJoCo humanoid at 0.39 ms per control
step on 1 CPU. Miners may train on GPUs at home; the evaluation path never
needs one.

## 7. What happens next

1. Macrocosmos security review (re-walks `reference/security-checklist.md`
   against §5 answers; checks digest pinning, cosign identity, resource
   ceilings).
2. Your `spec.yaml` is copied verbatim into the private registry and
   activated on stage; your baseline runs a staging round.
3. One feedback round-trip — most often on evaluation sizing (§4) and the
   reveal policy.
4. Prod activation with the agreed incentive weight and fee. Updates later
   follow the same loop: bump `version`, re-sign, request activation.
