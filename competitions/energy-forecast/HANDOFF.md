# Competition Onboarding Manifest: `energy_forecast`

**Status: design + reference implementation complete; NOT yet ready to
onboard.** This competition requires a platform extension
(`PLATFORM_PROPOSAL.md`) that doesn't exist yet — every item below is filled
honestly against that constraint. Do not open an onboarding issue until
`entrypoints.resolve` / `resolution_delay_days` land, or until we jointly
decide to ship a `mode: backtest`-only v1 in the meantime (see §7).

> What Macrocosmos decides unilaterally: the final incentive weight, the
> submission fee, activation timing, and whether extra screening is required
> after security review. Everything else below is our proposal and will be
> discussed, not silently changed.

## 1. Goal statement & alignment plan

**What success looks like** (one paragraph, domain terms):

> A model that genuinely forecasts next-day electricity demand for a US grid
> Balancing Authority from its own recent history — the kind of forecaster a
> grid operator would actually find useful for day-ahead planning — not a
> model that has memorized the public historical record it's evaluated
> against.

**Alignment checks**:

- The target period must not have existed anywhere on the public record when
  the submission was scored — structural, enforced by the two-phase
  lock → resolve design in `PLATFORM_PROPOSAL.md`, not a policy we have to
  keep re-checking.
- A submission must beat seasonal-naive (skill > 0) to be worth anything;
  submissions scoring ≤ 0 are contributing nothing beyond a trivial rule and
  should never be able to take the lead (they structurally can't, since
  `baseline_raw_score` is set from a real trained baseline, not 0).
- Review cadence & method: every round, sample top submissions' per-BA skill
  breakdowns and check performance isn't concentrated in one BA or one
  weather regime (a model that only works for mild, low-variance BAs is
  gaming the round mean, not forecasting well). Non-ranking diagnostics
  watched for divergence: per-BA skill spread, MAE-vs-naive ratio
  distribution, and step-function score jumps across many miners in one
  round (usually a data leak or metric hole, not a breakthrough).

## 2. Deliverables

| Item | Where | Done |
|---|---|---|
| Competition repo (public) + released tag | not yet created — this is currently a subdirectory of apex-competitions-sdk for design review | ☐ |
| `spec.yaml` (`apex.competition.v2`, PROPOSED) — fails `apex-dev preflight` against v1 only for the 2 new fields + placeholder digests (verified) | `spec.yaml` | ☑ (pending v2 schema) |
| Player image | `player/Dockerfile`, `player/launch.py` written; not yet built/pushed/signed | ☐ |
| Referee image | `referee/Dockerfile`, `referee/referee.py` written and tested locally (real player+referee HTTP loop); not yet built/pushed/signed | ☑ (code) / ☐ (image) |
| Resolver image (proposed `entrypoints.resolve`) | `resolver/resolve.py` written and tested via `tools/simulate_two_phase.py`; not yet built/pushed/signed; needs the platform extension to run for real | ☑ (code) / ☐ (image, extension) |
| Layer-2 screen image — or written justification | n/a — ONNX artifact with a closed interface ([1,1008]→[1,24], float32, ≤25 MB); structural validation in the public player loader + Layer-1 weights validator. No code enters the sandbox. | ☑ |
| Round-generation entrypoint (`generate_round`) — or "platform seed is enough" | Platform seed is enough: the referee derives all instances deterministically from `SEED` via `SeedSequence`, same pattern as humanoid-parkour | ☑ |
| Cosign identity + issuer | placeholder in `spec.yaml` `signature` block; real identity pending repo creation | ☐ |
| `input_schema` + input fixtures | `input.schema.json`, `fixtures/input.json` | ☑ |
| Baseline submission (scores > 0 through the full player+referee loop) | `baseline/baseline.onnx` (ridge regression, recipe in `baseline/train_baseline.py`) — raw **0.341** mean over 20 seeds at N=600 backtest instances (§4) | ☑ |
| Miner-facing README | `README.md` | ☑ |
| Evidence of a full end-to-end run | Local two-process run (real player server + real referee over HTTP), both `mode: backtest` and the full `mode: live` → `resolve` loop (`tools/simulate_two_phase.py`), deterministic across repeats | ☑ |
| Daily data-refresh pipeline | `resolver/fetch_ground_truth.py` + `.github/workflows/refresh-ground-truth.yml` written; not yet run against real EIA-930 (needs `EIA_API_KEY` + a real repo to host the cron) | ☐ |

Pins (everything that affects scores):

- dataset: `data/*_history.csv` currently **synthetic placeholder data**
  (`tools/generate_synthetic_history.py`) — MUST be replaced by real,
  content-hashed EIA-930 data via `resolver/fetch_ground_truth.py` before
  any real round runs. Real history will be pinned by content hash per
  release, same as any other competition dataset.
- dependency pins: `numpy==2.3.4`, `onnxruntime==1.28.0` (player);
  `numpy==2.3.4` (referee/resolver) — single-threaded ORT session for
  determinism.
- image digests: none yet (no images built).

## 3. Ops parameters (proposal, each with a one-line reason tied to §1)

| Parameter | Where it lives | Proposal | Production norm |
|---|---|---|---|
| `process_type` | spec | cpu — a ≤25 MB linear/small ONNX forecaster, no GPU anywhere in the loop | cpu |
| `kind` | spec | solo — forecast skill is an absolute metric; no adversary needed | solo |
| `defaults.round_length_in_days` | spec | 1 — matches the natural forecast horizon (next-day) and how often fresh confirmed data arrives | 1–2 days |
| `defaults.resolution_delay_days` | spec (PROPOSED field) | 2 — covers EIA-930's ~1–2 day actuals-finalization lag with margin | n/a today — new |
| `defaults.submission_reveal_days` | spec | 5 — trained forecasters are real R&D, similar reasoning to humanoid-parkour's policy weights | 1–7 days |
| `defaults.lower_is_better` | spec | false — skill score, higher is better | — |
| `defaults.baseline_raw_score` | spec | 0.341 — measured: mean over 20 master seeds at N=600 backtest instances with the released ridge baseline (§4) | measured, not guessed |
| `resources` | spec | 1 CPU / 1.5Gi — a linear-model or small-MLP forecast is trivial to run; baseline uses well under 50% | ~1 CPU / 1.5Gi |
| `evaluate.timeout_s` / `referee.timeout_s` | spec | 300 / 300 — measured ~0.9s at N=600 backtest instances; generous margin for larger submitted models | median eval 1–10 min |
| Per-`/act` deadline (`deadline_ms`) | round input | 2000 ms — a forecast is one feed-forward pass; generous vs. typical <10ms inference, tolerates larger models | 0.5–5 s |
| Submission fee | platform | ≈$1 — standard anti-spam | ≈$1 |
| Incentive weight | platform | 0.02–0.03 (low end while `mode: live` is unproven) — Macrocosmos decides | 0.02–0.05 |

## 4. Evaluation-sizing justification (required paragraph — measured, not guessed)

- Instances per evaluation (N): tested 180 and 600 (600 = `input.schema.json`
  max). Backtest mode only (live mode's N is capped at the tracked-BA count,
  ~20, per round — see §5 threat model item 2 for why, and the discussion
  below).
- Measured σ_round across 20 master seeds with the trained ridge baseline
  (raw ≈ 0.34): **σ_round = 0.0106 at N=600** (0.0215 at N=180). Raw
  per-seed range at N=600: 0.271–0.363.
- Typical top score and the resulting 1% takeover margin: baseline-era top
  ≈ 0.34 → margin ≈ 0.0034 → required σ_round ≤ margin/4 ≈ 0.00085.
- Check: σ_round ≤ ¼ × margin? **No — 0.0106 ≫ 0.00085 at N=600, the
  evaluation-shape cap.** Raising N further would require ~150× more
  instances (σ ∝ 1/√N) — not reachable within the wall-time envelope, and
  not reachable in `mode: live` at all (N is bounded by the number of real
  BAs, not a knob). We report this honestly rather than tune to pass, for
  reasons we'd like to discuss at review (echoing humanoid-parkour's
  precedent for the same honest-fail pattern):
  (a) within a round, every submission scores on the *identical* instances
  (same master seed) and the evaluation is deterministic — repeat runs
  produce identical raw scores — so σ_round never blurs a same-round
  ranking decision;
  (b) σ_round only manifests as cross-round drift of a frozen leader's score
  when a new round's seed rolls — bounded by the 1-day round length, so an
  undeserved hold lasts at most a day;
  (c) `mode: live`'s real constraint is different from a simulator's: N is
  bounded by how many real-world grid entities exist to forecast, not by
  wall-time. Scaling `BALANCING_AUTHORITIES` beyond the ~20 in this reference
  (EIA-930 covers ~70 respondents) is the lever to raise N, and is worth
  doing before launch — tracked as an open item, not resolved here.
- Reference solutions rank consistently across all seeds? **Yes — 20/20**
  for the baseline vs. a random-weight `tools/make_test_policy.py` forecaster
  (which scores near/below 0 by construction, no overlap on any seed).
- Total evaluation wall time at N=600: **~0.9s measured** — far under the
  300s `timeout_s`; margin covers much larger submitted models.

## 5. Threat-model questionnaire

1. **Miner-visible surface.** Round input: `num_instances`, `deadline_ms`,
   `mode` — public knobs, no leverage. Observation stream: the input BA's own
   168-hour history + calendar features, exactly what a deployed forecaster
   would use. In `mode: live`, the target period is never sent to the player
   at all (it doesn't exist yet); in `mode: backtest`, it's used only inside
   the referee for scoring, never sent to the player.
2. **Seed leverage.** The master round SEED selects which historical windows
   `mode: backtest` samples; it never regenerates or reveals `mode: live`
   targets (those come from real-world data via the ground-truth feed, not
   from the seed). Per PLATFORM_PROPOSAL.md, the ground-truth feed is
   produced independently of any round/seed.
3. **Degenerate submissions.** A constant/near-constant forecast is caught by
   `instance_skill_score`'s `MIN_OUTPUT_STD_RATIO` gate (score 0); NaN/Inf or
   wrong-shape output is a typed `invalid_output` (score 0). Near-empty
   graphs are rejected by Layer-1 (`min_weight_bytes: 10000`).
4. **Baseline resubmission.** Scores exactly the baseline raw score
   (deterministic per round) — below the current top by construction, short
   of the 1.01× takeover threshold.
5. **Metric gaming.** Probed so far: predicting the input window's own mean
   (flat output) → degenerate-output gate; predicting yesterday's values
   verbatim (i.e. reproducing seasonal-naive) → skill ≈ 0, never takes the
   lead; extreme single-instance blowups → `SKILL_CLIP` bounds per-instance
   contribution both directions. **Remaining pre-launch task**: an
   adversarial day specifically probing whether any BA's demand series is
   regular enough that a lookup-table-style memorized model (trained purely
   on public history, ignoring the actual input window) could still score
   competitively in `mode: backtest` — this is exactly the failure mode
   `mode: live` exists to close, so this check matters most for confirming
   backtest-only interim operation (§7) doesn't ship with a false sense of
   security.
6. **Copy-plus-epsilon.** After the 5-day reveal, a copied model scores
   identically (deterministic eval); a trivial weight perturbation scores the
   same or worse and can't clear the 1% takeover bar.
7. **Cross-round leakage.** `mode: live`: each round's target is a genuinely
   new, previously-nonexistent period — zero transfer by construction.
   `mode: backtest`: instances are resampled from the historical pool each
   round (fresh seed), but the *pool itself* is public and static — this is
   precisely why `mode: backtest` is NOT the production mode (see §1, §7).
8. **Error-message hygiene.** Player-visible failures are typed
   (`invalid_output` from the loader's shape/dtype checks) — no thresholds or
   scoring internals beyond what's in the public `env/scoring.py`.
9. **Referee state.** Stateless across games: instances rebuilt from the
   injected seed + pinned/live data each run, no caches or temp files, nothing
   keyed on submission-controlled values.
10. **Code execution.** n/a — `artifact_type: onnx`. No code enters the player
    sandbox.
11. **Public-image hygiene.** Player image contains only `launch.py` (ONNX
    serving + validation) — no historical data, no ground truth, no scoring.
    `env/`, `data/`, and `resolver/` are deliberately public (the training
    kit and the data pipeline); the resolver's ground-truth feed is signed
    but not secret — there's no hidden information to protect, only its
    integrity to verify.
12. **Diagnostics payload.** `result.json` metadata: per-instance BA, skill,
    MAE vs. naive, gate reason. All of it describes the miner's own
    predictions on expired (live) or already-public (backtest) instances;
    none of it reveals anything about a future round's targets.

## 6. GPU justification

n/a — `process_type: cpu`. A ≤25 MB linear/small-MLP ONNX forecaster runs a
single feed-forward pass on 1008 floats; the reference baseline measures
sub-millisecond inference.

## 7. Open items before this can onboard

1. **`PLATFORM_PROPOSAL.md` needs a decision.** Either the two-phase
   extension is scheduled, or we agree to launch a `mode: backtest`-only v1
   as an interim step — which would need its own honest write-up of the
   memorization risk in §5 item 5 and probably a *higher* reveal delay or
   rotating-pool mitigation, since it does NOT have the genuine
   exploit-resistance property this competition is designed around.
2. **Replace synthetic data with real EIA-930 data** (`EIA_API_KEY`,
   `resolver/fetch_ground_truth.py` run for real) before any baseline number
   here is trustworthy for launch — the 0.341 baseline score above is on
   synthetic placeholder series, not real grid data, and will change.
3. **Confirm the `BALANCING_AUTHORITIES` roster** against EIA-930's actual
   respondent list, and decide whether to expand it (raises live-mode N,
   §4).
4. Repo creation, image builds, cosign signing — none of the deliverables
   requiring a real released repo are done (§2).

## 8. What happens next (once §7 is resolved)

1. Macrocosmos reviews this HANDOFF + `PLATFORM_PROPOSAL.md` together.
2. If the platform extension is accepted: schema/scheduler work lands, we
   build + sign real images, activate on stage running `mode: live` for
   real, one round-trip of feedback, then prod.
3. If backtest-only interim is chosen instead: re-review §5 item 5 and §1
   with that constraint explicit, then the same stage → prod path.
