# Otto Product Classification

Classify products into 9 categories from 93 anonymised count features. Submit a CSV of class
probabilities; the lowest multiclass log loss leads. This is a Kaggle-shaped Apex competition:
one fixed dataset, split into a public train set and a test set whose labels are private.

> **Status: stage-only, incentive weight 0.** The placeholder dataset's labels are publicly
> available, so this competition is an integration exercise for the CSV/private-data
> competition shape, not a live incentive. See `HANDOFF.md` §5 Q1.

## The task

Our own deterministic stratified 70/30 split of Kaggle's Otto `train.csv`:

- **`data/train.csv`** — 43,319 rows with labels. Yours to train on however you like.
- **`data/test_features.csv`** — 18,559 rows, features only. What you predict.
- test labels — **private**, never published, mounted only into the scorer sandbox.

The test set is **fixed and identical in every round**. Nothing is resampled, no seed enters
the evaluation, and the same submission scores exactly the same number forever.

Classes are imbalanced (Otto's real proportions):

| Class | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|
| Rows | 1,929 | 16,122 | 8,004 | 2,691 | 2,739 | 14,135 | 2,839 | 8,464 | 4,955 |

## Scoring

Kaggle's multiclass log loss, lower is better:

```
logloss = -(1/N) * sum_i sum_j y_ij * log(p_ij)
```

Each row is **rescaled to sum to 1 first**, then clipped to `[1e-15, 1 - 1e-15]`. Only your
probability for the true class matters, so this reduces to `-mean(log(clip(p_true / row_sum)))`.

All measured on this exact split (see `baseline/PROVENANCE.md`):

| Submission | Log loss |
|---|---|
| Uniform (1/9 everywhere) | 2.1972 |
| Class prior, no features | 1.9503 |
| Small GBM (50 iterations) | 0.5372 |
| **Declared baseline** | **0.4736** |
| Kaggle top-100 (2015, full test set) | ≈0.44 |
| Kaggle winning ensemble | ≈0.38 |

To take the lead you must beat the current best by 1% — i.e. score `≤ best × 0.99`. Against the
launch baseline that means **≤ 0.468816**.

For scale: a submission of confident-but-random one-hot guesses scores **14.37** — nearly 7×
worse than doing nothing. Calibration is most of the game.

**Invalid rows are charged `-ln(1e-15) = 34.5388`**, the worst score any *valid* submission
could reach. That is deliberate: under lower-is-better a failure must rank at or below every
honest attempt, and charging `ln(9)` instead would pay you more for failing than for a bad
honest guess. One bad row out of 18,559 costs 0.00186 — graduated, not fatal.

Row gates that earn it: `wrong_width`, `non_finite` (NaN/Inf), `out_of_range` (outside
`[0,1]`), `row_sum` (off by more than 1e-3), `missing_row` (an asked-for id absent from your
CSV), `bad_row_type`.

## Submission contract

A single CSV at `/app/submission.csv`, at most 8 MB:

```
id,Class_1,Class_2,Class_3,Class_4,Class_5,Class_6,Class_7,Class_8,Class_9
1,0.0100000,0.0200000,0.0100000,0.0100000,0.0100000,0.6100000,0.1000000,0.1800000,0.0100000
```

- header **exactly** as above
- one row per test id, every id present, no duplicates, no extras
- 9 finite values in `[0,1]` summing to 1 ± 1e-3

File-level violations (bad header, duplicate ids, wrong width, non-numeric) fail at startup and
your submission is rejected before scoring. Row-level violations are charged per row.

### Never write an exact `0`

This is the most common self-inflicted wound. A one-hot row that is **wrong** costs 34.54 on
that row alone — 0.19% of your whole score from a single row. And naive 6-decimal formatting
silently floors any probability below 5e-7 to `0.000000`, converting well-calibrated small
probabilities into landmines. Clip to `[1e-7, 1]`, renormalise, and write 7 decimals:

```python
clipped = [max(v, 1e-7) for v in probs]
total = sum(clipped)
row = [f"{v / total:.7f}" for v in clipped]
```

## Get the data

```bash
python tools/prepare_data.py
```

Needs a Kaggle API token at `~/.kaggle/kaggle.json` **and** a one-time acceptance of the
competition rules at
<https://www.kaggle.com/c/otto-group-product-classification-challenge/rules> — without it
Kaggle returns HTTP 403 and the script tells you so.

The CSVs are **not committed**: Otto is a Kaggle *competition* dataset under competition rules
rather than an open licence, so republishing it (or a slice of it) here would likely violate
the T&Cs. `data/MANIFEST.sha256` **is** committed and is the reproducibility contract — the
writer is byte-deterministic, so `--check` will confirm your regeneration matches ours exactly.

No Kaggle access? `python tools/make_synthetic_source.py` produces a same-shaped synthetic
stand-in so you can exercise the whole pipeline, then
`python tools/prepare_data.py --from-file build/synthetic_train.csv`.

## Train and evaluate locally

```bash
pip install scikit-learn                                   # author-side only
python baseline/train_baseline.py --variant gbm --out my_submission.csv
python tools/local_eval.py --submission my_submission.csv  # full player+referee loop, no Docker
```

**You do not hold the test labels**, so `local_eval.py` cannot tell you your real score — it
needs a labels file. Hold out a slice of `data/train.csv` and score against that instead. The
gap between your holdout and the leaderboard is the whole game.

`python tools/make_test_submission.py --variant <v>` generates one deliberately-broken CSV per
gate, so you can see exactly how each violation is reported before you submit.

## What you see after each round

`logloss`, `num_rows`, `num_invalid_rows`, a gate histogram, and eval time.

You will **never** see per-row losses — a per-row correctness oracle is a partial answer key.
And **submissions are not revealed** (`submission_reveal_days: 3650`): on a fixed test set a
winning CSV *is* the answer key, and a blend of two revealed CSVs beats both with zero
modelling work.
