# Vibe-Coding Report: `tabular_automl`

**Competition summary:** Miners submit `fit`/`predict`/`complexity` training-strategy code
(not a pre-trained model) that retrains fresh every evaluation against a freshly generated
synthetic tabular dataset; task family (regression/classification/timeseries/clustering)
rotates with the platform seed, raw score is a task-normalized loss ratio against a
reference model averaged over 20 instances/round, and training time/inference time/model
complexity are hard pass/fail gates rather than continuous penalties.

Repo: not yet released (scaffold only, this repo's `competitions/tabular-automl/`) ·
Onboarding: not filed · Review PR: n/a

## The numbers

| Metric | Value |
|---|---|
| Claude model | `claude-sonnet-5` (Claude Code CLI, single session) |
| Claude tokens / cost | **not captured** — this session ran tool-call-only (no interactive `/cost`), so no exact token/cost figure is available; run `/cost` in-session for the real number rather than trust an estimate here |
| Code churn (competition scaffold) | **1,042 lines added**, 0 removed (brand new directory, 13 files) |
| — of which Python | **505 LOC** (`env/`, `player/`, `referee/`, `baseline/`, `tools/`) |
| — of which docs/config | 537 LOC (`HANDOFF.md`, `README.md`, `spec.yaml`, `input.schema.json`, `fixtures/input.json`) |
| Idea (copypasta) → structured, objective competition request | conversational, no code |
| Structured request → scaffold passing `apex-dev preflight` | single continuous work session |
| Commits | **0** — nothing has been committed; all files are untracked |
| **SDK source changes required** | **0** |
| Baseline | tied to the referee's own reference model by construction (`raw_score = 1.0` exactly), verified via a standalone Python harness (`tools/sizing_check.py`), not yet run through the real Docker/gym_v1 loop |

## SDK/design changes needed to achieve the goal

**None to the SDK itself** — same headline as every other competition in this repo. The
real work was entirely on the design side, reconciling an ambitious verbal pitch ("miners
submit trained sklearn pipelines, we regularize on complexity, this doubles as an
anonymization product") with what `apex.competition.v1` actually supports:

1. **The original pitch assumed a capability the SDK doesn't have.** "Publish a dataset,
   miners train against it, submit a fitted model by round end" has no home in the
   contract — `entrypoints.evaluate` only runs an already-finished artifact; there's no
   training-phase entrypoint, and a submission is a standing leaderboard entry with no
   concept of "belongs to round N." Confirmed by reading the schema and grepping every
   production `HANDOFF.md` in this repo, not by assumption.
2. **Reframing the submission as training *code*, not a trained model, resolved it for
   free.** `fit()` runs inside `reset()` fresh every evaluation, on whatever data that
   round's `SEED` produced. This fits the platform's existing async "submit anytime,
   scored against the current seed" cadence exactly — zero new capability needed. This
   is the single most important design decision in the whole exercise, and it only
   surfaced from stress-testing the mismatch instead of implementing the literal brief.
3. **Rotating task type (not just data) under one fixed `defaults` block required a
   task-agnostic metric.** `defaults.baseline_raw_score`/`lower_is_better` are fixed per
   spec version, so scoring couldn't switch from RMSE to log-loss to silhouette round to
   round. Fixed by normalizing every family to the same `reference_loss / your_loss`
   ratio shape.
4. **Two real scoring bugs were only caught by actually running the numbers, not by
   inspection.** (a) The clustering reference model was quietly handed the true cluster
   count derived from ground truth while the baseline had to guess — an apples-to-oranges
   comparison masquerading as "task difficulty," found because a baseline-vs-itself
   sanity check should score exactly 1.0 and instead scored ~0.01. (b) The score ratio's
   epsilon-flooring was asymmetric, collapsing near-zero-loss ties toward 0 instead of 1.
   Neither would have been caught without writing a throwaway sizing script and looking
   at the output.
5. **Two of the six originally-requested task families were descoped, not shipped
   broken.** `anomaly_detection` accidentally handed the submission real labels (making
   it classification, not anomaly detection) and beat the intentionally-unsupervised
   reference by ~5x; `symbolic_regression`'s data generator produced only linear ground
   truth, so there was no nonlinear structure for a "compact formula discovery"
   submission to actually discover. Both are documented in `HANDOFF.md` as explicit open
   items rather than silently dropped.

## What a fresh user should know

**Where the SDK is genuinely strong:**

- The same headline as every other competition built against this SDK: a wildly
  different problem shape (tabular AutoML, code-as-submission, multi-instance
  averaging, hard binary gates) still expressed cleanly in `solo` + `gym_v1` +
  `artifact_type: code`, with zero schema changes.
- `apex-dev preflight` caught the spec/fixture shape instantly and correctly on the
  first real run.
- The gym_v1 `reset`/`act` contract is flexible enough to carry an entire *training*
  step through `reset(config)` — not just inference — which the docs don't spell out
  explicitly but the primitives support without a fight.
- The Layer-1 AST screener made "no serialization, no pickle" a one-line spec decision
  (`extra_forbidden_modules`) instead of a bespoke Layer-2 image.

**Where you'll hit friction (in order of pain):**

1. **The SDK has no vocabulary for "submission trains on the fly" vs. "submission is a
   finished artifact."** Both are valid competition shapes and this one leans hard on
   the former, but nothing in the docs distinguishes them — a designer coming from the
   Kaggle-style mental model in the original pitch will naturally reach for the
   *wrong* one (pre-trained artifact) and hit the round-scoping wall described above
   before realizing the fix is a reframing, not a platform feature request.
2. **`n_instances`-per-round averaging is entirely hand-rolled.** The evaluation-sizing
   guidance (100-400 instances) assumes the designer will loop `reset`/`act` cycles
   themselves; there's no SDK helper for "run my player against N independent seeds and
   average," and the naive one-draw-per-round version is exactly the mistake the docs
   warn about but don't structurally prevent.
3. **No local Docker/gym_v1 loop was exercised in this session** (same gap as every
   other competition report here — `apex-dev run` doesn't execute the pair yet). All
   verification here was a pure-Python harness calling `env/tasks.py` and
   `baseline/submission.py` directly, bypassing the real HTTP contract. This is flagged
   as an explicit open item, not glossed over.
4. **Cross-family score comparability is a real, unsolved design question**, not an SDK
   gap: a fixed non-adaptive submission strategy scored 0.07-1.0 raw_score depending on
   which of the four task families it landed on. That's arguably correct incentive
   design (adapt per family, like a real AutoML pipeline) but it was only discovered by
   running a second, non-tautological baseline through the sizing check — the first
   pass (baseline vs. itself) looked perfect and would have shipped a misleading "0
   variance" number.

## Scores (fresh-user POV, 1-10)

| Dimension | Score | One-liner |
|---|---|---|
| **Ease of use** | **6.5** | Preflight and the schema are fast and forgiving; the docs don't warn a Kaggle-shaped idea into the wrong submission model before real design time is sunk into it. |
| **Completeness** | **6** | Full authoring/validation loop works; no runnable local player+referee loop, no built-in multi-instance averaging helper, and the sizing-evidence procedure only catches bugs if you actually run it (nothing forces that). |
| **SDK expressiveness** | **8.5** | A rotating-task-family AutoML competition with code-as-training-strategy, per-instance averaging, and three hard gates fit the existing contract with zero SDK changes — genuinely surprising range for a schema that wasn't designed with this shape in mind. |

**Overall: 7/10** — the SDK's primitives are more expressive than its documentation
suggests (reset() can carry a whole training step, not just inference), but a fresh user
chasing a Kaggle-style pitch will burn real design time discovering that before finding
the reframing that actually works.
