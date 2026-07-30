# Competition Onboarding Manifest: `otto_product_classification`

> **Read §5 Q1 first.** The placeholder dataset's test labels are publicly available, so this
> competition cannot be run at a real incentive weight as configured. It is submitted as the
> reference implementation and integration exercise for a NEW competition shape — a fixed
> dataset with private, platform-mounted ground truth and CSV submissions — which is the actual
> deliverable. Every other part of it transfers verbatim to a customer dataset whose labels were
> never published.
>
> **Blocking platform dependencies:** this spec uses two schema features that do not yet have
> platform implementations (`submission.artifact_type: csv` needs a Layer-1 CSV screener;
> `private_data` needs an R2 fetch + verify + read-only-mount stage in the worker). See §7.

---

## 1. Goal statement & alignment plan

**What we actually want:** a *calibrated* multiclass classifier we would deploy on a real
product-categorisation feed — one whose probabilities are trustworthy, not just whose argmax is
often right.

**Why log loss and not accuracy:** accuracy rewards confident guessing; log loss punishes it.
A model that says "70% Class_6" and is right 70% of the time scores better than one that says
"99% Class_6" and is right 70% of the time. That is the property we want to buy.

**Alignment checks, and their review cadence:**

| Check | How | Cadence |
|---|---|---|
| Calibration, not just ranking | log loss is the metric, so this is structural | every round |
| No degenerate/one-hot gaming | inspect the top submissions' probability distributions for the near-one-hot signature that indicates lookup rather than modelling | every 3 rounds |
| Structural safety | the submission is data, not code: it cannot probe the sandbox, allocate, or execute | by construction |
| Ground truth integrity | sha256 pin verified by the platform before every job, and again by `env/labels.py` | every job |

---

## 2. Deliverables

| Item | Status |
|---|---|
| Repo + tag | `competitions/otto-product-classification/` (staged in-tree; standalone repo + `v0.1.0` tag pending) |
| `spec.yaml` passes `apex-dev preflight` | ✅ **exit 0** — but only against the *extended* schema in this PR (see §7) |
| Player image digest | ⏳ PLACEHOLDER — images not built/signed yet |
| Referee image digest | ⏳ PLACEHOLDER — images not built/signed yet |
| `input.schema.json` + `fixtures/input.json` | ✅ validated by preflight |
| Baseline submission | ✅ `baseline/submission.csv` + `baseline/PROVENANCE.md` — **measured log loss 0.473552** on the real Otto split |
| Miner README | ✅ `README.md` |
| Local two-process run evidence | ✅ `tools/local_eval.py` drives the real player subprocess + real referee over HTTP; uniform submission scores exactly `2.1972245773362196` |
| Competition tests | ✅ 51 tests under `tests/`, run by the repo-root `pytest -q`, **zero new dev dependencies** |
| Layer-2 `entrypoints.screen` | **n/a** — the artifact is a CSV with a closed grammar. It is structurally validated in the public player loader and then fully re-validated in the referee; there is no behaviour to screen because there is no code to run. |
| `entrypoints.generate_round` | **n/a** — the test set is fixed and arrives via `private_data`. There is nothing per-round to generate. |
| Private ground-truth object | ⏳ **hand-over required.** `private/test_labels.csv` must be uploaded to R2 by a Macrocosmos maintainer, who returns the sha256 to paste into `spec.yaml` and `env/labels.py`. |

### Pins

Parkour pinned one asset hash. A dataset competition has more surface, so all of these are
pinned, and `data/MANIFEST.sha256` is the committed record:

| What | Where pinned |
|---|---|
| Upstream Kaggle `train.csv` sha256 | `data/MANIFEST.sha256` |
| `data/train.csv` sha256 | `data/MANIFEST.sha256` |
| `data/test_features.csv` sha256 | `data/MANIFEST.sha256` |
| `private/test_labels.csv` sha256 | `data/MANIFEST.sha256`, `spec.yaml` `private_data[0].sha256`, `env/labels.py` `TEST_LABELS_SHA256` |
| `baseline/submission.csv` sha256 | `baseline/PROVENANCE.md` |
| Split identity | `env/split.py`: `SPLIT_SALT = "otto_product_classification/v1"`, `TEST_NUM/TEST_DEN = 3/10` |
| Dependency versions | **none — neither image installs anything.** Both are `FROM apex-{player,referee}-base` plus two `COPY` lines. |

That last row is the strongest statement in this table and it is deliberate: `env/metric.py` is
`math.log` + `math.fsum`, so there is no numpy (or any other) version that could silently drift
a score between rounds.

All pins describe the real Otto dataset. `data/MANIFEST.sha256`:

```
11d3618a9d2dba32356c7c5f71ea2c790dcf1bd1ac1f0270f5f520b14329a3b4  upstream/train.csv       rows=61878  bytes=12433387
36c92dc7392bed20e7082c84c51dbba8c76feebce0ab7c240af10e8b7fc7c314  data/train.csv           rows=43319  bytes=8704457
d255627100c5f40fb521efb0709b4bebf59289f456d3e777bdcc2765c1341434  data/test_features.csv   rows=18559  bytes=3581196
87d85cf421180391e9f5224445bb23dd38ab0be000c35995d40e4ebe5c59912b  private/test_labels.csv  rows=18559  bytes=256506
```

`baseline/submission.csv` = `b1ddff52aaca6c20b49a23919755c733f9ff36c2cabd9dcb80e6b083f05a9730`.
`python tools/prepare_data.py --check` re-verifies all three derived files; the writer is
byte-deterministic, so an independent regeneration reproduces these hashes exactly.

---

## 3. Ops parameters

| Parameter | Value | Reason |
|---|---|---|
| `kind` | `solo` | one submission scored against fixed ground truth; no head-to-head |
| `process_type` | `cpu` | parsing a CSV and computing 18.5k logarithms |
| `resources` | 1 CPU / 512Mi / 0 GPU | measured need is ~8 MB resident in the player, less in the referee. Right-sized rather than copied from parkour's 1.5Gi. |
| `timeout_s` | 300 / 300 | measured end-to-end eval is well under 5 s; ~60× margin |
| `batch_size` | 4096 (5 `/act` calls) | bounds peak JSON at ~420 KB/batch instead of ~2 MB in one shot, and leaves headroom for a 10× larger customer test set without a spec version bump |
| `deadline_ms` | 5000 | ~50× the real per-batch cost, absorbing cold-start and CPU-throttle jitter |
| `round_length_in_days` | 2 | matches the platform norm. Stated honestly: with a fixed test set a round boundary is *purely* a leaderboard refresh — nothing rotates, and each boundary costs a baseline re-score. |
| `submission_reveal_days` | 3650 | "effectively never" — see Q6. The schema has no "never", so this is a stopgap pending `reveal_artifact: false`. |
| `lower_is_better` | `true` | log loss |
| `baseline_raw_score` | **0.473552** | measured through `tools/local_eval.py` on the real split. Takeover therefore needs ≤ 0.468816. |
| Submission fee | ~$1 (platform default) | anti-spam; also the only cost on resubmission-fishing, which matters more here than usual because the test set never rotates |
| **Incentive weight** | **0 (stage only)** | Q1 |

---

## 4. Evaluation-sizing justification

**N = the entire test set, every round: 18,559 rows.** There is no sampling and no per-round
variation to size.

**σ_round = 0.000000, exactly.** No seed enters the evaluation: the score is a pure function of
(submission bytes, mounted labels, batch_size). `tools/measure_precision.py` verifies this by
scoring twice and requiring bit-identical results. This is the good half of a fixed test set —
seed-fishing is not merely defended against, it is structurally impossible, and an identical
resubmission scores identically forever.

Parkour's across-seed σ therefore has **no analogue here**, and re-running its
`measure_variance.py` would print `σ = 0, PASS`: true and uninformative. The real question is
whether N rows resolve a genuine 1% quality difference. Two statistics, and the distinction is
the entire argument:

**Unpaired SE of the mean** — the naive analogue. Measured at the baseline (0.473552): per-row
loss sd 0.9489, bootstrap SE (B=2000) **0.006897**, versus a 1% margin of 0.004736 and a
`margin/4` requirement of 0.001184. **FAIL, by ~5.8×.** And N cannot be raised: the same
arithmetic wants ~630,000 rows and Otto has 61,878 in total. We report this rather than tune
around it, exactly as parkour's §4 reports its own failure.

**Paired SE of the difference** — the correct decision statistic, and why the above is not
disqualifying. Every submission is scored on *exactly the same 18,559 rows*, so ranking is
governed by `SE(mean(loss_A − loss_B))`, not `SE(mean(loss_A))`. Measured against the
`gbm-small` reference (0.537174): **ρ(per-row) = 0.904**, `SE(paired Δ)` = **0.003051** — a 2.3×
improvement on the unpaired figure, and it is the figure that governs every ranking decision the
platform actually makes. Combined with σ_round = 0, comparing the same two submissions twice
gives bit-identical numbers, so no decision is ever re-drawn.

`SE_paired` (0.003051) still exceeds `margin/4` (0.001184) by 2.6×, and we state that plainly.
The argument for accepting it: `margin/4` is a heuristic derived from the *rotating-round* case,
where a leader's score is re-drawn every round and σ_round shows up directly as rank churn. Here
there is no re-draw at all. Two submissions 1% apart in true quality are separated by a paired
comparison whose noise is a property of the *sample of rows*, not of the evaluation — and that
sample is frozen and shared, so the comparison is exactly reproducible. The residual risk is that
a frozen 18,559-row sample may not represent the population; that is a generalisation concern
about the leaderboard's meaning, not an evaluation-precision concern about its stability.

**Separability:** the baseline ranks better than the `gbm-small` reference in **2000/2000**
bootstrap resamples — the `evaluation-design.md` step-4 check, adapted from "across 20 seeds" to
"across bootstrap resamples", the only meaningful version when there is one seed.

**Measured score ladder** (same split, same harness — the gradient a miner climbs):

| Submission | Log loss |
|---|---|
| `uniform` (1/9) | 2.1972245773362196 (exactly ln 9) |
| `prior` | 1.950259 |
| `gbm-small` (50 iters) | 0.537174 |
| **`gbm` — the baseline** | **0.473552** |
| Kaggle top-100 (2015, full test set) | ≈0.44 |
| `onehot_answer` (the leak) | 8.0e-07 |

**Wall time:** measured well under 5 s end-to-end against `timeout_s: 300`. Baseline *training*
takes 44.6 s, but that is author-side and not on the eval path.

---

## 5. Threat-model questionnaire

**Q1. What is the strongest exploit you know of, and why is it acceptable?**

**The placeholder dataset's labels are public, and no amount of privacy on our side fixes it.**
Our test rows are rows of Kaggle's `train.csv`, which anyone can download *with* labels. A miner
does not even need our split code: the 93 integer count features are near-unique per row, so an
inner join of `data/test_features.csv` against Kaggle's `train.csv` on the feature vector
recovers `target` for essentially every test id. Submitting the resulting answer key scores
log loss ≈ 0.

Measured, not asserted: `tools/make_test_submission.py --variant onehot_answer` builds exactly
that submission and it scores **8.0e-07** through the real player+referee loop, against a
baseline of 1.388.

Hiding `env/split.py`, salting the split, renumbering ids, or switching the artifact to ONNX
(a nearest-neighbour lookup table is a perfect model) all fail to close it, because the join
never touches our split.

**Accepted, with mitigation by configuration:** stage only, **incentive weight 0**, treated as
the integration exercise for the CSV/private-data shape. Do not activate on prod. For a real
launch the dataset must be one whose scored labels were never published — which is precisely
the customer-brought-dataset case this template exists to serve.

**Q2. What does the round SEED control?** Nothing. Stated in the referee docstring, the input
schema description, and §4. It is passed to `player.reset` because the protocol has the field,
and recorded in metadata for audit. Its absence is a design decision, not an oversight.

**Q3. Can a miner discover the test labels from the eval itself?** No. The referee returns one
aggregate log loss plus a gate histogram. **Per-row losses are never in metadata** — a per-row
correctness oracle is a partial answer key, and `tests/test_referee.py` asserts metadata
contains no per-row lists. A miner can still binary-search labels across *rounds* by submitting
probe CSVs, but each probe costs a fee and yields ~1 aggregate number, so the information rate
is ~1 float per $1.

**Q4. Can the submission execute anything?** No. It is a CSV. The player parses it with
`csv.reader` into floats; there is no eval, no pickle, no deserialisation of code. This is why
`artifact_type: csv` belongs at the top of the constrained-format ladder.

**Q5. Can a malformed submission take down the referee?** No, and this is enforced twice. The
player rejects file-level violations at startup (process exits, readiness never succeeds). The
referee independently re-checks every `screening` knob and charges row-level violations, because
Layer 1 may not exist yet and the referee must never trust the CSV. Every failure mode maps to a
typed `terminal_reason` with a result written — see the table in `referee/referee.py`.

**Q6. What does revealing submissions leak?** **The answer key.** On a fixed test set the
winner's CSV *is* ground truth for every scored row. Worse than a straight copy (which scores
identically and so cannot clear the 1% bar, and is therefore harmless): a **blend** of two
revealed CSVs reliably beats both on log loss with zero modelling work, and several revealed
CSVs at ≈0.45 collectively pin down most true labels. This is a property of "the submission is
the predictions", so it will be true for every customer dataset too. Mitigation:
`submission_reveal_days: 3650` as a stopgap, plus the platform ask in §7 for a proper
`reveal_artifact: false`. Aggregate metadata is still revealed generously.

**Q7. Can a miner fish for a better seed by resubmitting?** No — there is no seed. Identical
resubmissions score identically forever. The residual risk is *leaderboard overfitting*: since
the test set never rotates, every scored submission is one bit of information about it. For a
real launch, hold back a slice of the test set that is scored but never reported.

**Q8. What happens if the ground truth is missing or wrong?** `env/labels.py` raises, the
referee lets it propagate, no `result.json` is written, and the platform attributes the failure
to the **referee** — not to the submission. It never fetches, never falls back to a bundled
copy, and never scores without truth. Covered by three tests (absent / hash mismatch / wrong row
count).

**Q9. Is the ground truth reachable from the miner's sandbox?** No, by two independent
mechanisms. `private_data` is referee-only by schema contract and by platform implementation,
and the SDK loader rejects a `mount_path` that collides with `submission.target_path`. The
player image contains no labels and the player process is never given the mount.

**Q10. What is in each image?** Base + `env/` + one entrypoint file. **No pip installs, no
dataset, no labels.** `env/` holds code, the split salt, and the sha256 of an object the public
spec already publishes.

**Q11. Where does test data live, and who can read it?** `data/train.csv` and
`data/test_features.csv` are public and not committed (Kaggle T&Cs) — miners regenerate them.
`private/test_labels.csv` exists only in private R2 and, per job, as a read-only mount in the
referee sandbox. It is in no image, no git history, and no player. `data/test_features.csv` is
needed by **nobody** in the eval path: the player serves a precomputed CSV and the referee needs
only ids + labels (the id list being a projection of the labels file). It exists solely so
miners can predict.

**Q12. Is there an anti-Goodhart gate in the referee?** Not beyond the validity gates, and we
would rather say so than invent one. On a hidden-label log-loss metric there is essentially
nothing to game: log loss already punishes overconfidence, and the only real lever is the
dataset leakage in Q1 — a *dataset* problem, not a metric hole. The gates exist to make invalid
submissions typed and correctly attributed, not to stop cleverness.

---

## 6. GPU justification

**n/a** — `process_type: cpu`, `gpu_count: 0`. The referee's entire numeric workload is ~167k
float parses and ~18.5k logarithms.

---

## 7. What happens next

**Blocking platform work.** Neither schema feature this spec uses has a platform implementation.
Nothing can be activated on stage until items 1–3 land.

1. **Layer-1 CSV screener.** An `artifact_type == "csv"` branch in the generic screener reading
   `screening.{max_size_mb, required_columns, expected_rows, id_column, value_min, value_max,
   row_sum, row_sum_tol, allow_nan}`. Must enforce the size cap *before* parsing, stream-parse
   with a hard row cap so a crafted CSV cannot OOM the screener, and return typed
   miner-actionable reasons ("row 42: sum 0.87 ≠ 1.0 ± 1e-3"). Until it exists, every malformed
   CSV becomes a *referee*-attributed failure, which silently poisons this competition's health
   metrics.
2. **Worker `private_data` stage.** Per job: resolve `r2://`, download, sha256-verify, and
   bind-mount read-only into the **referee container only** (worth an explicit test that the
   player never receives it); delete after. A fetch failure or digest mismatch is a PLATFORM
   error, never a submission failure. A content-addressed cache keyed by sha256 matters here
   (immutable object, many submissions per round) but must still verify on cache hit.
3. **Spec syncer.** Pick up the extended SDK schema; at *activation* time verify the R2 object
   exists and its digest matches (fail the activation, not the round's first job); assert the
   prefix is not publicly readable; run `check_private_data` server-side too.
4. **Ops/IAM.** Private prefix `apex-private/otto_product_classification/`, write access limited
   to Macrocosmos maintainers — competition designers hand the file over and never get write
   access. Worker R2 credentials must never be injected into any sandbox environment.
5. **`apex submit`.** Confirm the miner client accepts a `.csv` artifact, with a client-side size
   check so miners get a fast local error instead of a queue round-trip.
6. **`reveal_artifact: false`.** The Q6 design hole. Needs deciding before any CSV competition
   goes live; it may be a non-additive schema change, so decide now rather than after activation.
7. **`lower_is_better: true` end-to-end** through the ×0.99 takeover rule — worth an explicit
   platform test, since few live competitions are lower-is-better.
8. **`winner` semantics for solo.** We use `0` = a real score exists, `-1` = submission failure.
   (Parkour's `0 if raw > 0` inverts meaninglessly under lower-is-better.) Confirm the platform
   reads `raw_scores[0]` and does not interpret `winner` for solo.

**Blocking competition work.**

9. ✅ **Done.** Real Otto data downloaded and split; every pin, `defaults.baseline_raw_score`,
   the baseline, and §4's sizing numbers are measured on the real dataset.
10. Build, cosign-sign, and digest-pin both images; fill the three digest placeholders; record
    measured peak RSS in `spec.yaml`'s resources comment.
11. Hand `private/test_labels.csv` (sha256 `87d85cf4…c59912b`, 256,506 bytes) to a maintainer for
    R2 upload at `r2://apex-private/otto_product_classification/test_labels.csv`. The digest is
    already pinned in `spec.yaml` and `env/labels.py`, so the upload must reproduce it exactly.
12. Move the directory to its own public repo and tag `v0.1.0`.
