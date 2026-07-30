"""Generate a synthetic stand-in for Otto's train.csv, for testing the pipeline without Kaggle.

    python tools/make_synthetic_source.py --out build/synthetic_train.csv --rows 6000
    python tools/prepare_data.py --from-file build/synthetic_train.csv

Same header and dtypes as the real source (id, feat_1..feat_93, target in Class_1..Class_9),
same right-skewed integer counts, same class imbalance ratios, and a genuinely learnable
class signal — so the split, the metric, the referee, the player, the baseline, and the
precision tooling can all be exercised end to end before anyone has Kaggle access.

This is NOT the competition dataset and must never be shipped as one: the real
data/MANIFEST.sha256 pins the true Otto file. Stdlib only (random + math), fixed seed, so the
output is byte-identical on any machine.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from pathlib import Path

NUM_FEATURES = 93
CLASSES = tuple(f"Class_{i}" for i in range(1, 10))
# Otto's real class proportions (61,878 rows), so the stand-in has the same imbalance.
CLASS_WEIGHTS = (1929, 16122, 8004, 2691, 2739, 14135, 2839, 8464, 4955)


def generate(rows: int, seed: int = 0, label_noise: float = 0.45) -> list[list[str]]:
    """Rows of (id, 93 counts, class).

    label_noise is the fraction of rows whose *emitted* label is redrawn uniformly at random
    after the features are generated. It sets the Bayes floor: with no noise the classes are
    almost separable and a GBM reaches ~0.002 log loss, which is nothing like a real tabular
    task and makes the precision analysis meaningless. At 0.45 the achievable log loss lands in
    the ~0.5-0.8 band, the same regime as real Otto.
    """
    rng = random.Random(seed)
    # Each class activates a distinct, overlapping subset of features. Overlap plus label noise
    # is what makes the task learnable but not trivial — a perfect classifier should not exist.
    signature = {cls: {(idx * 7 + k * 3) % NUM_FEATURES for k in range(12)} for idx, cls in enumerate(CLASSES)}
    out: list[list[str]] = []
    for row_id in range(1, rows + 1):
        cls = rng.choices(CLASSES, weights=CLASS_WEIGHTS, k=1)[0]
        hot = signature[cls]
        if rng.random() < label_noise:
            cls = rng.choices(CLASSES, weights=CLASS_WEIGHTS, k=1)[0]
        feats = []
        for j in range(NUM_FEATURES):
            # Right-skewed counts: mostly 0, occasional larger values, higher rate if in-signature.
            rate = 0.9 if j in hot else 0.12
            v = 0
            if rng.random() < rate:
                v = 1 + int(-math.log(max(rng.random(), 1e-9)) * (2.5 if j in hot else 1.2))
            feats.append(str(v))
        out.append([str(row_id), *feats, cls])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="build/synthetic_train.csv")
    ap.add_argument("--rows", type=int, default=6000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--label-noise", type=float, default=0.45, help="Bayes floor; see generate()")
    args = ap.parse_args()

    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = ["id", *(f"feat_{i}" for i in range(1, NUM_FEATURES + 1)), "target"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(generate(args.rows, args.seed, args.label_noise))
    print(f"✓ wrote {path} ({args.rows} rows, {NUM_FEATURES} features, {len(CLASSES)} classes)")
    print("⚠ synthetic stand-in — NOT the Otto dataset. For real data: python tools/prepare_data.py")


if __name__ == "__main__":
    main()
