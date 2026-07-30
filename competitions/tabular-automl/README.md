# tabular_automl

A tabular-data AutoML competition: each round hands you a freshly generated, freely
public synthetic dataset (regression, classification, timeseries, or clustering) and
scores your submission's own training strategy against it -- like a Kaggle competition,
except your code trains fresh every time it's evaluated, on whatever data that round's
seed produced.

## What you submit

A single Python file (`submission.py`, `artifact_type: code`, max 2MB) that defines
three functions:

```python
def fit(train_X: list[list[float]], train_y: list | None, task_type: str, n_clusters: int | None) -> Any:
    """Train and return a model object of your choosing."""

def predict(model: Any, test_X: list[list[float]]) -> list:
    """Return one prediction per row of test_X."""

def complexity(model: Any) -> int:
    """Self-reported model complexity (e.g. total learned parameter count)."""
```

- `task_type` is one of `"regression"`, `"classification"`, `"timeseries"`, `"clustering"`
  (rotates round to round, derived from the platform's per-round seed -- see below).
- `n_clusters` is only set (non-`None`) when `task_type == "clustering"`: it's a public
  problem-specification constant (like knowing there are 2 classes in the classification
  family), not something you need to guess.
- For `classification`, `predict` must return per-row probabilities in `[0, 1]`, not hard
  labels.
- For `clustering`, `train_y` is `None` (unsupervised) and `predict` must return an
  integer cluster id per test row.

See `baseline/submission.py` for a complete, working reference (linear/logistic
regression + KMeans) -- it's exactly what the referee's own scoring reference uses, so
it scores `raw_score == 1.0` by construction. Beat it by fitting better per family.

## How scoring works

1. The referee derives this round's task family from `SEED` alone (`SEED % 4`).
2. It draws `n_instances` **independent** synthetic datasets of that family (same task
   type, different data each time) -- see "why not just one dataset?" below.
3. For each instance: your `fit` is called with that instance's training rows (timed
   against `max_train_time_s`), then your `predict` is called with the held-out test
   rows (timed against `inference_deadline_ms`).
4. Your loss (MSE for regression/timeseries, log-loss for classification, 1 - Adjusted
   Rand Index for clustering) is compared against a simple reference model's loss on the
   *same* instance: `raw_score = reference_loss / your_loss`, averaged across all
   instances, capped at 5.0.

**Three hard gates, not continuous penalties** -- exceeding any one of these on *any*
instance zeros your entire round's `raw_score`, it does not shave points off:

| Gate | Config knob | What happens if you exceed it |
|---|---|---|
| Training time | `max_train_time_s` | Your `fit` call is killed; round scores 0 |
| Inference time | `inference_deadline_ms` | Your `predict` call is killed; round scores 0 |
| Model complexity | `max_complexity` | Your reported `complexity()` exceeds the cap; round scores 0 |

Current fixture defaults: 500 training rows, 200 test rows, 20 instances/round, 5s
train budget, 2s inference budget, complexity cap 5000 -- see `input.schema.json` /
`fixtures/input.json`. These are non-secret operating limits, not the data itself.

## Why not just one dataset per round?

An earlier version of this design scored each round against a single dataset draw.
Running the actual sizing procedure (not just eyeballing it) showed that's exactly the
under-sized-evaluation mistake this SDK's own guidance warns about: cross-round score
variance for a fixed, tied-with-reference submission was far above the 1% takeover
margin. Averaging over `n_instances` independent draws of the same task family per round
brings that down to (measured) zero for a submission that matches the reference
strategy per family -- see `tools/sizing_check.py` and `HANDOFF.md` Sec 4.

## What's NOT in scope yet

The original brief asked for six task families. Two are deliberately deferred, not
shipped silently broken -- both design flaws were caught by running the numbers, not by
inspection:

- **anomaly_detection** -- as first specced, it handed real anomaly labels to the
  submission (`train_y`), making it rare-class classification, not anomaly detection,
  and let a supervised submission beat the (correctly unsupervised) reference by ~4-5x.
  Needs a real semi-supervised/unsupervised design before it rejoins the rotation.
- **symbolic_regression** -- the generator produced a linear ground-truth function, so a
  plain linear-regression reference already achieves ~zero loss, leaving no nonlinear
  structure for a submission to discover. Needs a real nonlinear expression generator.

## Local dev loop

```bash
pip install -e .        # the SDK, from the repo root
apex-dev preflight --spec ./spec.yaml --input fixtures/input.json
```

`apex-dev run` does not yet execute the player+referee pair locally end to end (see
this SDK's top-level docs); exercise the full loop by running the two images by hand on
a shared Docker network with the platform's env vars (`MATCH_ID`, `SEED`, `CONFIG_JSON`,
`PLAYER_URLS`, `NUM_PLAYERS`), or run `python tools/sizing_check.py` for a pure-Python
sanity check of the scoring math against the baseline (no Docker needed).
