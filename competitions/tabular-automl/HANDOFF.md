# Competition Onboarding Manifest: `tabular_automl`

> Status: v0.1.0 draft scaffold, NOT yet built/signed/onboarded. Image refs in
> `spec.yaml` are placeholders. This manifest exists to carry the design
> rationale and the sizing evidence gathered while building the scaffold, and
> to flag the two open items that must be resolved before an onboarding issue
> is opened.

## 1. Goal statement & alignment plan

**What success looks like:** A miner-submitted training strategy that, given
any of several rotating tabular task families (regression, classification,
timeseries, clustering), fits a model competitive with or better than a
simple reference model, subject to hard limits on training time, inference
time, and model complexity -- rewarding solutions that are both accurate and
minimal, in the spirit of "the most compact model that actually works."
Long-run product angle (deferred, not part of this spec): "drop a file in,
get N models and insights back." Real-dataset anonymization via a
GAN/diffusion-based synthetic-data library is an explicit **later phase**.

**Alignment checks:**

- A submission that ties or beats the reference model in one task family
  should generalize to a *different instance* of the same family (checked
  automatically every round -- `n_instances` independent draws per round; see
  Sec 4).
- Top submissions, when inspected, should show family-appropriate modeling
  (e.g. don't use one fixed model architecture for every family) -- a fixed,
  non-adaptive strategy was measured to score wildly inconsistently across
  families (0.07-1.0 raw_score for the same submission; see Sec 4), which is
  the intended signal that per-family adaptation is required, not noise to
  suppress.
- Complexity self-reports should be spot-checked against the actual returned
  model shape periodically (miners are not scored on honesty of `complexity()`
  directly, only gated by it -- see Sec 5 Q3).

Review cadence & method: every round, pull the top 3 submissions' reported
`task_type`/`complexity`/`train_time_s` from result metadata and confirm they
vary sensibly by task family; watch for a submission scoring near the 5.0 cap
in every family (likely gate-gaming or a metric bug, not real skill).

## 2. Deliverables

| Item | Where | Done |
|---|---|---|
| Competition repo (public) + released tag | (this repo, not yet released) | ☐ |
| `spec.yaml` (`apex.competition.v1`) — `apex-dev preflight` passes | `competitions/tabular-automl/spec.yaml` | ☐ (not yet run against a built image) |
| Player image | `ghcr.io/macrocosm-os/apex-competition-tabular-automl-player` (placeholder digest) | ☐ |
| Referee image | `ghcr.io/macrocosm-os/apex-competition-tabular-automl-referee` (placeholder digest) | ☐ |
| Layer-2 screen image | n/a — Layer-1 AST bans on pickle/dill/marshal/shelve/ctypes + socket/subprocess are judged sufficient; the submission never serializes anything (models live only in memory for one match), so there is no deserialization surface to add bespoke behavioural screening for. | n/a |
| Round-generation entrypoint (`generate_round`) | n/a — like every other competition in this repo, the referee derives the round's dataset deterministically from `SEED` alone (`env/tasks.py`) | n/a |
| Cosign identity + issuer | placeholder in spec `signature` block, pending repo release | ☐ |
| `input_schema` + input fixtures | `input.schema.json`, `fixtures/input.json` | ✅ |
| Baseline submission (scores > 0 through the full player+referee loop) | `baseline/submission.py` — verified via `tools/sizing_check.py` (pure-Python, not yet through the actual Docker/gym_v1 loop) | ☐ (needs Docker-level run) |
| Miner-facing README | `README.md` | ✅ |
| Evidence of a full end-to-end run | not yet done — see open items below | ☐ |

Pins:

- model revision: n/a (no pre-trained model artifact ships with this competition)
- dataset hash(es): n/a (all data is generated deterministically from `SEED`, not pinned files)

## 3. Ops parameters

| Parameter | Where it lives | Proposal | Reason |
|---|---|---|---|
| `process_type` | spec | cpu | All reference models (linear/logistic regression, KMeans) are CPU-trivial |
| `kind` | spec | solo | Every submission scored independently against its own round instances; no adversarial/relative element |
| `defaults.round_length_in_days` | spec | 1 | Matches production norm; nothing in this design needs a longer round |
| `defaults.submission_reveal_days` | spec | 1 | Submitted code is a training *strategy*, not a fitted model with real IP to protect — short reveal favors fast iteration |
| `defaults.lower_is_better` | spec | false | `raw_score` is `reference_loss / your_loss` — higher is better by construction |
| `defaults.baseline_raw_score` / `baseline_score` | spec | 1.0 / 0.0 | The baseline literally IS the reference model per family, so it ties by construction (measured, not guessed — see Sec 4) |
| `resources` | spec | 1 CPU / 1.5Gi / 0 GPU | Reference models are trivial; no justification for more |
| `evaluate.timeout_s` / `referee.timeout_s` | spec | 240 / 240 | `n_instances=20 x (max_train_time_s=5s + inference budget=2s)` = 140s, plus HTTP/serialization overhead margin |
| Per-instance train deadline | referee config | `max_train_time_s=5s` (fixture default) | Reference models fit in well under 1s on 500 rows; 5s gives real submissions headroom without allowing runaway training |
| Per-`act()` deadline | referee config | `inference_deadline_ms=2000` | Predicting 200 rows should never approach this for any reasonable model |
| Submission fee | platform | ≈$1 (production norm) | Not negotiated yet |
| Incentive weight | platform | 0.02-0.05 (production norm) | Not negotiated yet |

## 4. Evaluation-sizing justification

Run via `tools/sizing_check.py` (pure Python, no Docker — mirrors the
referee's exact scoring math). Numbers below are real measured output from
this session, not estimates.

**First pass (1 instance/round, exposed two real bugs):**

- A "baseline vs its own reference" round should score exactly 1.0 with zero
  variance (they're the same model). Instead: `clustering` scored
  mean=0.008, std=0.015 and `symbolic_regression` scored exactly 0.0.
- Root causes found by actually running the numbers, not by inspection:
  1. The clustering **reference** model was given the true cluster count
     (derived from `test_y`, i.e. ground truth), while the **baseline**
     had to guess it via a fixed constant — an apples-to-oranges
     comparison, not real task difficulty. **Fixed**: `n_clusters` is now a
     fixed, public constant (3) known to both, exactly like `n_classes=2`
     is fixed and known for the classification family.
  2. The score-normalization ratio `reference_loss / max(submission_loss, EPS)`
     floored only the denominator. When both losses are near machine
     epsilon (a noiseless instance both models solve exactly), that
     collapsed the ratio toward 0 instead of the correct ~1 (a tie).
     **Fixed**: `(reference_loss + EPS) / (submission_loss + EPS)`.

**After both fixes, with `n_instances=20` (current default):**

```
task_type              n    mean     std
regression             5   1.0000  0.0000
classification         5   1.0000  0.0000
timeseries             5   1.0000  0.0000
clustering             5   1.0000  0.0000

overall n=20  mean=1.0000  sigma_round=0.0000
1% takeover margin at baseline mean: 0.01000
sigma_round <= 1/4 x margin?  0.00000 <= 0.00250  ->  True
```

- Instances per evaluation (N): **20** per round (each a full independent
  fit+predict cycle on a fresh dataset draw of the round's task family).
- Measured σ_round for a submission tied with the reference: **0.0000**
  (exactly, since baseline == reference model by construction after the
  fixes above). Passes the σ_round ≤ ¼×margin check trivially.
- **Caveat, stated plainly**: this is necessarily a tautological best case
  (a model scored against itself). As a second check, a *genuinely
  different* fixed strategy (RandomForest, same architecture across every
  family) was run through the same procedure and produced mean raw_scores
  ranging **0.07 (regression) to 1.0 (clustering)** across families, with an
  aggregate σ well above the margin. This is **not** re-litigated as a bug:
  `regression`/`timeseries`'s ground truth is genuinely linear, so a
  non-adaptive tree-based strategy structurally underperforms there — a real
  competitive submission is expected to adapt its model choice per family
  (exactly the point of an AutoML competition), and once it does, its score
  converges to the reference-tied case above. The number to watch post-launch
  is whether a submission's *own* round-to-round score (for whatever family
  it draws) stays low-variance once it's actually competitive, not whether
  one fixed architecture scores identically everywhere.
- Total evaluation wall time at N=20, measured train times well under 1s per
  instance for all four reference models: comfortably inside the proposed
  240s `timeout_s`.

## 5. Threat-model questionnaire

1. **Miner-visible surface.** Round input to the player (`config` passed to
   `reset()`): `task_type`, `train_X`, `train_y` (or `None` for clustering),
   `max_complexity`, and `n_clusters` (clustering only). All of this is safe
   in an adversary's hands: `train_X`/`train_y` are freshly generated
   synthetic training data with no real-world sensitivity, and
   `max_complexity`/`n_clusters` are declared operating limits / problem
   specification, not derived from held-out ground truth. `test_X` (observed
   in `act()`) is likewise synthetic; `test_y` never leaves the referee.
2. **Seed leverage.** No — `test_y` (ground truth) is generated inside the
   referee from `instance_seed(SEED, i)` and never serialized or sent
   anywhere; regenerating it requires knowing the referee's exact generation
   code (public, in this repo) AND the seed, at which point you'd have the
   full training distribution anyway with no advantage over solving the task
   honestly, since the round's `SEED` is the platform's normal per-round seed
   (not itself secret).
3. **Degenerate submissions.** A constant-prediction submission scores far
   below 1.0 in every family (reference loss stays low, submission loss is
   high, `raw_score → 0`); not separately tested via Docker yet — flagged as
   an open item (Sec "Open items" below). No gate specifically targets
   constant output beyond the ordinary loss ratio, which is expected to
   suffice (a constant is simply a bad model, not an exploit).
4. **Baseline resubmission.** The published baseline ties the reference model
   exactly (raw_score = 1.0 by construction, measured above) and needs
   `1.01x` to take the lead — it cannot take or hold the lead on its own,
   by construction.
5. **Metric gaming.** Found and fixed two real issues by actually running the
   scoring code (Sec 4): the clustering oracle-leak and the EPS-flooring
   asymmetry. Not yet probed: whether a submission can report a false
   (understated) `complexity()` to dodge the gate while returning a more
   complex model — see open item below.
6. **Copy-plus-epsilon.** With a 1-day reveal delay and code (not weights) as
   the submission format, a copied strategy plus a trivial perturbation is
   exactly as good as the original if it doesn't change fit quality — this is
   an accepted tradeoff of the short reveal window (Sec 3), consistent with
   "submitted code carries little standalone IP" reasoning.
7. **Cross-round leakage.** Each round draws fresh, independent synthetic data
   (`instance_seed` derived from the round `SEED`); nothing about one round's
   instances predicts another round's, since the underlying generative
   parameters (feature count, correlations, cluster centers) are redrawn
   from `numpy.random.default_rng(seed)` per instance.
8. **Error-message hygiene.** `_gated_result` metadata includes `task_type`,
   `detail` (an exception message or timing comparison), and `n_instances` —
   no ground-truth values or per-instance data appear in any failure/error
   text.
9. **Referee state.** Stateless: `build_round`/`reference_prediction`/`loss`
   are pure functions of `(seed, n_train, n_test, task_type)`; no caches,
   temp files, or logs keyed on submission-controlled values.
10. **Code execution.** `artifact_type: code` was chosen deliberately (see
    Sec "Design rationale" below) because ONNX/TorchScript can't express an
    arbitrary sklearn-style training *strategy*, only a fixed already-trained
    model. Screening extras beyond the base forbidden set: `pickle`, `dill`,
    `marshal`, `shelve`, `ctypes` banned outright (the submission never needs
    to serialize/deserialize anything — the model lives only in memory for
    one match), plus `eval`/`exec`/`__import__`/`compile` calls banned.
11. **Public-image hygiene.** The player image ships no ground truth (it only
    loads and calls the submission); the referee image (which does hold
    `env/tasks.py`, the reference models, and the loss functions) is intended
    to stay private/unreleased at the image level even though its source is
    in this public repo, per standard practice — no held-out labeled data is
    ever baked into either image since all ground truth is generated at
    referee runtime.
12. **Diagnostics payload.** `result.json` metadata carries `task_type`,
    `n_instances`, and per-instance `raw_score`s (or gate-failure `detail`
    text) — none of it is ground truth or reveals anything beyond what the
    submission could already observe about its own performance.

## 6. GPU justification

Not applicable — `process_type: cpu`.

## Design rationale (why this shape, not the original brief verbatim)

The original request described miners submitting **pre-trained model
pipelines** (sklearn objects, serialized). Investigating this SDK's actual
mechanics surfaced three real conflicts with that framing, and a
significantly better-fitting redesign:

- **No "publish dataset, then miners train, then submit" cadence exists in
  this SDK** — `entrypoints.evaluate` only runs an already-finished artifact;
  there's no training-phase entrypoint.
- **No round-scoping for submissions** — a submission is a standing
  leaderboard entry, re-evaluated indefinitely; a model fit to round N's
  specific dataset would be incoherent once round N+1 rotates to new data.
- **`defaults` (baseline/lower_is_better) is fixed per spec version** — can't
  vary per round, so naively rotating the *metric* (RMSE one round, AUC the
  next) doesn't work.

The fix that resolves all three at once, using only primitives this SDK
already has: **the miner submits training-strategy code, not a trained
model.** `fit()` runs inside `reset()` fresh every time the submission is
evaluated, on whatever data that round's `SEED` produced. This means:
training happens on the platform's existing async "submit anytime, scored
against the current seed" cadence (no new capability needed); the same
submission stays coherent across rounds because it's a *strategy*, not a
fitted model tied to one round's distribution; and the metric stays a fixed,
task-agnostic normalized loss ratio (`reference_loss / your_loss`) so
rotating *task type* (not metric semantics) is safe under one `defaults`
block. No platform changes were required — this is a pure design fix on the
competition side.

## Open items before an onboarding issue can be opened

1. **anomaly_detection and symbolic_regression are deferred, not shipped.**
   Both had real, measured design flaws (see `env/tasks.py` module docstring
   and README "What's NOT in scope yet"): anomaly detection accidentally
   leaked labels, turning it into classification; symbolic regression's
   generator produced only linear ground truth, leaving nothing for a
   "compact formula discovery" submission to actually discover. Re-adding
   them needs, respectively, a genuinely label-blind design and a real
   nonlinear-expression generator — real work, not a config tweak.
2. **The Docker/gym_v1 loop has only been exercised in pure Python**
   (`tools/sizing_check.py` calls `env/tasks.py` and `baseline/submission.py`
   directly, bypassing the actual player/referee HTTP contract). Before
   onboarding, run the two images by hand per `docs/authoring.md`'s
   instructions to confirm the gym_v1 wiring (`reset`/`act` JSON shapes,
   `PlayerClient` timeout behavior for the training-time gate) actually
   behaves as this document assumes.
3. **Degenerate-submission and complexity-dishonesty gates (Sec 5 Q3, Q5)
   are reasoned about but not yet tested against an actual running
   submission** — worth a dedicated adversarial pass before going to stage.
4. **Cross-family score comparability for a competitive (not tied) submission
   has only been checked at N=20 instances for the reference-tied case.**
   Sec 4's caveat about a non-adaptive strategy's high cross-family variance
   should be revisited once a real, better-than-reference miner submission
   exists, to confirm the "adapt per family and variance converges" claim
   holds in practice and not just in theory.
