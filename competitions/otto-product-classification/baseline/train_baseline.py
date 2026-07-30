"""Produce the declared baseline submission — the score a miner must beat by 1%.

    pip install scikit-learn                     # author-side only; NOT in either image
    python baseline/train_baseline.py --variant gbm --out baseline/submission.csv
    python tools/local_eval.py --submission baseline/submission.csv   # the measured number

Variants, in ascending quality — the `--reference` inputs tools/measure_precision.py needs:
    uniform    1/9 everywhere            -> exactly ln(9) = 2.1972
    prior      the class prior           -> ~2.06 on real Otto
    gbm-small  50 boosting iterations    -> ~0.60-0.65
    gbm        the declared baseline      -> ~0.48-0.55

`uniform` and `prior` are stdlib-only and always runnable; the gbm variants need scikit-learn.
sklearn (and numpy) stay strictly author-side: neither image installs anything, which is why no
dependency version can ever silently drift a score.

WRITE FORMAT — the single most likely self-inflicted wound. Never emit an exact 0: a wrong
one-hot row costs -ln(1e-15) = 34.54 on that row alone. Naive 6-decimal formatting floors any
probability below 5e-7 to "0.000000", silently converting well-calibrated small probabilities
into landmines. Hence clip to [1e-7, 1], renormalize, and write 7 decimals.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
import time
from pathlib import Path

COMP_DIR = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(COMP_DIR)]

from env.metric import CLASS_INDEX, CLASSES, NUM_CLASSES  # noqa: E402
from env.submission_io import EXPECTED_HEADER  # noqa: E402

CLIP_FLOOR = 1e-7
# Otto's real class proportions (61,878 rows), used by --variant prior.
CLASS_WEIGHTS = (1929, 16122, 8004, 2691, 2739, 14135, 2839, 8464, 4955)


def _read_features(path: Path, with_target: bool) -> tuple[list[int], list[list[float]], list[int]]:
    ids: list[int] = []
    x: list[list[float]] = []
    y: list[int] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        next(reader)
        for record in reader:
            if not record:
                continue
            ids.append(int(record[0]))
            feats = record[1:-1] if with_target else record[1:]
            # log1p on right-skewed count features: a small, free win for tree models and a
            # large one for anything linear.
            x.append([math.log1p(float(v)) for v in feats])
            if with_target:
                y.append(CLASS_INDEX[record[-1].strip()])
    return ids, x, y


def _write_submission(out: Path, ids: list[int], probs: list[list[float]]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(EXPECTED_HEADER)
        for row_id, p in zip(ids, probs, strict=True):
            clipped = [max(v, CLIP_FLOOR) for v in p]
            total = math.fsum(clipped)
            w.writerow([str(row_id), *[f"{v / total:.7f}" for v in clipped]])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", default="gbm", choices=["uniform", "prior", "gbm-small", "gbm"])
    ap.add_argument("--out", default=str(COMP_DIR / "baseline" / "submission.csv"))
    ap.add_argument("--train", default=str(COMP_DIR / "data" / "train.csv"))
    ap.add_argument("--test", default=str(COMP_DIR / "data" / "test_features.csv"))
    ap.add_argument("--backend", default="sklearn", choices=["sklearn", "xgboost"])
    args = ap.parse_args()

    test_path = Path(args.test)
    if not test_path.is_file():
        raise SystemExit(f"✗ {test_path} not found — run `python tools/prepare_data.py` first.")
    test_ids, test_x, _ = _read_features(test_path, with_target=False)
    start = time.monotonic()

    if args.variant == "uniform":
        probs = [[1.0 / NUM_CLASSES] * NUM_CLASSES for _ in test_ids]
    elif args.variant == "prior":
        total = sum(CLASS_WEIGHTS)
        prior = [w / total for w in CLASS_WEIGHTS]
        probs = [list(prior) for _ in test_ids]
    else:
        probs = _fit_predict(args, test_x)

    out = Path(args.out)
    _write_submission(out, test_ids, probs)
    print(f"✓ wrote {out} ({args.variant}, {len(test_ids)} rows) in {time.monotonic() - start:.1f}s")
    print(f"  measure it: python tools/local_eval.py --submission {out}")


def _fit_predict(args: argparse.Namespace, test_x: list[list[float]]) -> list[list[float]]:
    train_path = Path(args.train)
    if not train_path.is_file():
        raise SystemExit(f"✗ {train_path} not found — run `python tools/prepare_data.py` first.")
    _, train_x, train_y = _read_features(train_path, with_target=True)
    print(f"• fitting {args.variant} on {len(train_x)} rows x {len(train_x[0])} features ({args.backend})")

    if args.backend == "xgboost":
        # Optional: buys perhaps 0.02-0.03 log loss over the sklearn GBM, for a dependency and
        # a tuning session. Record whichever you used in baseline/PROVENANCE.md.
        try:
            from xgboost import XGBClassifier
        except ImportError:
            raise SystemExit("✗ --backend xgboost needs `pip install xgboost`") from None
        model = XGBClassifier(
            objective="multi:softprob",
            num_class=NUM_CLASSES,
            n_estimators=50 if args.variant == "gbm-small" else 500,
            learning_rate=0.08,
            max_depth=6,
            subsample=0.9,
            colsample_bytree=0.8,
            random_state=0,
            n_jobs=-1,
        )
    else:
        try:
            from sklearn.ensemble import HistGradientBoostingClassifier
        except ImportError:
            raise SystemExit("✗ the gbm variants need `pip install scikit-learn`") from None
        model = HistGradientBoostingClassifier(
            loss="log_loss",
            max_iter=50 if args.variant == "gbm-small" else 500,
            learning_rate=0.08,
            max_leaf_nodes=31,
            min_samples_leaf=20,
            l2_regularization=1.0,
            early_stopping=True,
            validation_fraction=0.1,
            n_iter_no_change=25,
            random_state=0,
        )

    model.fit(train_x, train_y)
    # Guard the column order: predict_proba is ordered by model.classes_, which must line up
    # with Class_1..Class_9. A silent permutation here would look like a bad baseline.
    assert list(model.classes_) == list(range(NUM_CLASSES)), f"unexpected class order {model.classes_}"
    assert len(CLASSES) == NUM_CLASSES
    return [list(map(float, row)) for row in model.predict_proba(test_x)]


if __name__ == "__main__":
    main()
