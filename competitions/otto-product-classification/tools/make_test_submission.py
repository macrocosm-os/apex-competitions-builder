"""Generate valid and deliberately-invalid submission CSVs — the adversarial probe kit.

    python tools/make_test_submission.py --variant uniform --out build/uniform.csv
    for v in uniform prior onehot_random missing_row extra_row nan out_of_range \\
             bad_row_sum bad_header dup_id empty; do ...; done

One variant per validity gate, so every gate can be shown to actually fire end to end through
tools/local_eval.py. `uniform` is also the integration assertion: it must score exactly
ln(9) = 2.1972245773362196. `onehot_answer` is the leakage demonstration — it needs the private
labels and scores ~0, which is the measured evidence for HANDOFF.md §5 Q1.

Stdlib only. Fixed seed, so output is byte-identical on any machine.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

COMP_DIR = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(COMP_DIR)]

from env.metric import CLASS_INDEX, CLASSES, NUM_CLASSES  # noqa: E402
from env.submission_io import EXPECTED_HEADER  # noqa: E402

# Otto's real class proportions, used by the `prior` variant.
CLASS_WEIGHTS = (1929, 16122, 8004, 2691, 2739, 14135, 2839, 8464, 4955)
VARIANTS = (
    "uniform",
    "prior",
    "onehot_random",
    "onehot_answer",
    "missing_row",
    "extra_row",
    "nan",
    "out_of_range",
    "bad_row_sum",
    "bad_header",
    "dup_id",
    "empty",
    "wrong_width",
)


def _read_ids(labels_path: Path) -> list[int]:
    with labels_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        next(reader)
        return sorted(int(r[0]) for r in reader if r)


def _read_labels(labels_path: Path) -> dict[int, int]:
    with labels_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        next(reader)
        return {int(r[0]): CLASS_INDEX[r[1].strip()] for r in reader if r}


def _fmt(values: list[float]) -> list[str]:
    # Clip away exact zeros before formatting: see the README warning — a wrong one-hot row
    # costs -ln(1e-15) = 34.54 on that row alone.
    return [f"{max(v, 1e-7):.7f}" for v in values]


def build(variant: str, labels_path: Path, seed: int = 0) -> tuple[list[str], list[list[str]]]:
    rng = random.Random(seed)
    ids = _read_ids(labels_path)
    header = list(EXPECTED_HEADER)
    uniform = [1.0 / NUM_CLASSES] * NUM_CLASSES
    total = sum(CLASS_WEIGHTS)
    prior = [w / total for w in CLASS_WEIGHTS]

    rows: list[list[str]] = []
    if variant == "empty":
        return header, []
    if variant == "bad_header":
        return ["id", *(c.lower() for c in CLASSES)], [[str(i), *_fmt(uniform)] for i in ids]

    for i in ids:
        if variant == "uniform":
            rows.append([str(i), *_fmt(uniform)])
        elif variant == "prior":
            rows.append([str(i), *_fmt(prior)])
        elif variant == "onehot_random":
            v = [0.0] * NUM_CLASSES
            v[rng.randrange(NUM_CLASSES)] = 1.0
            rows.append([str(i), *_fmt(v)])
        elif variant == "onehot_answer":
            v = [0.0] * NUM_CLASSES
            v[_read_labels(labels_path)[i]] = 1.0
            rows.append([str(i), *_fmt(v)])
        else:
            rows.append([str(i), *_fmt(uniform)])

    if variant == "missing_row":
        rows.pop(len(rows) // 2)
    elif variant == "extra_row":
        rows.append([str(max(ids) + 1), *_fmt(uniform)])
    elif variant == "dup_id":
        rows.append(list(rows[0]))
    elif variant == "nan":
        rows[0] = [rows[0][0], "nan", *_fmt(uniform)[1:]]
    elif variant == "out_of_range":
        rows[0] = [rows[0][0], "-0.5", "1.5", *_fmt(uniform)[2:]]
    elif variant == "bad_row_sum":
        rows[0] = [rows[0][0], *_fmt([v * 2 for v in uniform])]
    elif variant == "wrong_width":
        rows[0] = rows[0][:-1]

    return header, rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", required=True, choices=VARIANTS)
    ap.add_argument("--out", help="output path (default build/<variant>.csv)")
    ap.add_argument("--labels", default=str(COMP_DIR / "private" / "test_labels.csv"))
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    labels_path = Path(args.labels)
    if not labels_path.is_file():
        raise SystemExit(f"✗ labels not found: {labels_path}\n  run `python tools/prepare_data.py` first.")

    header, rows = build(args.variant, labels_path, args.seed)
    out = Path(args.out) if args.out else COMP_DIR / "build" / f"{args.variant}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    print(f"✓ wrote {out} ({args.variant}, {len(rows)} rows)")


if __name__ == "__main__":
    main()
