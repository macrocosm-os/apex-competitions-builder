# baseline/submission.csv provenance

Measured against the **real Otto dataset** (upstream `train.csv` sha256
`11d3618a9d2dba32356c7c5f71ea2c790dcf1bd1ac1f0270f5f520b14329a3b4`, 61,878 rows), split
43,319 train / 18,559 test by `env/split.py`.

| Field | Value |
|---|---|
| Variant | `gbm` (`sklearn.ensemble.HistGradientBoostingClassifier`) |
| Command | `python baseline/train_baseline.py --variant gbm --out baseline/submission.csv` |
| **Measured log loss** | **0.473552** (`python tools/local_eval.py --submission baseline/submission.csv`) |
| Declared in spec | `defaults.baseline_raw_score: 0.473552` |
| Rows | 18,559 |
| sha256 | `b1ddff52aaca6c20b49a23919755c733f9ff36c2cabd9dcb80e6b083f05a9730` |
| Bytes | 1,778,409 |
| Fit wall time | 44.6 s (43,319 rows × 93 features, laptop CPU) |
| scikit-learn | 1.9.0 |
| Python | 3.13.1 |
| Backend | `sklearn` (`--backend xgboost` available; typically buys a further 0.02–0.03) |

Recipe: `log1p` on the raw count features, then `HistGradientBoostingClassifier(loss="log_loss",
max_iter=500, learning_rate=0.08, max_leaf_nodes=31, min_samples_leaf=20, l2_regularization=1.0,
early_stopping=True, validation_fraction=0.1, n_iter_no_change=25, random_state=0)`. Output
probabilities are clipped to `[1e-7, 1]`, renormalised, and written at 7 decimals — see the
write-format warning in `README.md`.

## Measured reference points (same split, same harness)

| Submission | Log loss | Note |
|---|---|---|
| `uniform` | 2.1972245773362196 | exactly ln(9); the integration assertion |
| `onehot_random` | 14.369849 | confidently wrong — the cost of writing 0s |
| `prior` | 1.950259 | class prior, no features used |
| `gbm-small` | 0.537174 | 50 boosting iterations; the `--reference` for sizing |
| **`gbm`** | **0.473552** | the declared baseline |
| `onehot_answer` | 8.0e-07 | the leakage exploit — see `HANDOFF.md` §5 Q1 |

For external context, the 2015 Kaggle leaderboard on the full test set: top-100 ≈0.44, winning
ensemble ≈0.38. Our baseline at 0.4736 sits just outside the top-100 band, which is the right
place for a baseline to be — beatable by real work, not by nothing.

## To take the lead

`lower_is_better: true`, so a submission must score **≤ 0.473552 × 0.99 = 0.468816**.

## What is deliberately not committed

The fitted model. It is not needed to reproduce the submission (recipe and seed are pinned above),
and a pickle in a public repo is a hazard. `submission.csv` is model *output*, not Kaggle data, so
it carries no redistribution problem — unlike `data/*.csv`, which are gitignored.
