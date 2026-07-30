"""Sizing analysis for a FIXED test set — the replacement for parkour's measure_variance.py.

    python tools/measure_precision.py --submission baseline/submission.csv \\
           --reference build/prior.csv --bootstrap 2000

Parkour measures sigma_round across master seeds. Here that quantity is IDENTICALLY ZERO: no
seed enters the evaluation, so re-running gives a bit-identical score. Printing "sigma = 0,
PASS" would be true and useless. The real question is whether N test rows resolve a genuine 1%
quality difference, and there are two answers:

  * UNPAIRED SE of the mean — the naive analogue of sigma_round. Bootstrap the per-row losses.
    Reported for completeness; it is NOT the decision statistic and it will typically fail the
    sigma <= margin/4 bar, because the spread of per-row log loss is large.

  * PAIRED SE of the difference — the correct statistic. Every submission is scored on exactly
    the same rows, so what governs ranking is SE(mean(loss_A - loss_B)), not SE(mean(loss_A)).
    Per-row losses of two similar models are strongly correlated, so this is much smaller. And
    because sigma_round is 0, comparing the same two submissions twice gives bit-identical
    numbers — every ranking decision the platform makes is exact.

Stdlib only (random + math + statistics), so this runs with no extra dependencies.
"""

from __future__ import annotations

import argparse
import math
import random
import statistics
import sys
from pathlib import Path

COMP_DIR = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(COMP_DIR)]

from env.labels import load_test_labels  # noqa: E402
from env.metric import MAX_ROW_LOSS, row_gate, row_loss  # noqa: E402
from env.submission_io import read_submission  # noqa: E402

TAKEOVER_MARGIN = 0.01  # the platform's 1% rule


def per_row_losses(submission_path: Path, ids: list[int], true_index: list[int]) -> list[float]:
    rows = read_submission(submission_path)
    out = []
    for row_id, ti in zip(ids, true_index, strict=True):
        row = rows.get(row_id)
        out.append(MAX_ROW_LOSS if row is None or row_gate(row) else row_loss(row, ti))
    return out


def _bootstrap_se(values: list[float], draws: int, rng: random.Random) -> float:
    n = len(values)
    means = []
    for _ in range(draws):
        means.append(math.fsum(values[rng.randrange(n)] for _ in range(n)) / n)
    return statistics.stdev(means)


def _pearson(xs: list[float], ys: list[float]) -> float:
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    num = math.fsum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    dx = math.sqrt(math.fsum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(math.fsum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx and dy else 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--submission", required=True, help="the submission under test (usually the baseline)")
    ap.add_argument("--reference", help="a deliberately weaker submission, for the separability check")
    ap.add_argument("--labels", default=str(COMP_DIR / "private" / "test_labels.csv"))
    ap.add_argument("--bootstrap", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    verify = set(__import__("env.labels", fromlist=["x"]).TEST_LABELS_SHA256) != {"0"}
    ids, true_index = load_test_labels(args.labels, verify=verify)
    rng = random.Random(args.seed)

    a = per_row_losses(Path(args.submission), ids, true_index)
    a2 = per_row_losses(Path(args.submission), ids, true_index)
    mean_a = math.fsum(a) / len(a)
    determinism_ok = a == a2

    print(f"determinism      : run 1 = {math.fsum(a) / len(a):.6f}, run 2 = {math.fsum(a2) / len(a2):.6f}")
    print(f"                   sigma_round = {0.0:.6f}  {'PASS' if determinism_ok else 'FAIL'}")
    print(f"n rows           : {len(a)}")
    print(f"mean logloss     : {mean_a:.6f}   ({Path(args.submission).name})")
    print(f"per-row loss sd  : {statistics.stdev(a):.4f}")

    se_unpaired = _bootstrap_se(a, args.bootstrap, rng)
    margin = mean_a * TAKEOVER_MARGIN
    print(f"SE(mean), boot   : {se_unpaired:.6f}   [unpaired — reported for completeness, not the decision statistic]")
    print(f"1% margin @ {mean_a:.3f}: {margin:.6f}   (margin/4 = {margin / 4:.6f})")
    print(f"  unpaired SE <= margin/4 : {'PASS' if se_unpaired <= margin / 4 else 'FAIL'}")

    if not args.reference:
        print("\n(pass --reference <weaker submission.csv> for the paired + separability analysis)")
        return

    b = per_row_losses(Path(args.reference), ids, true_index)
    mean_b = math.fsum(b) / len(b)
    deltas = [x - y for x, y in zip(a, b, strict=True)]
    se_paired = _bootstrap_se(deltas, args.bootstrap, rng)
    rho = _pearson(a, b)

    print(f"\nreference        : {mean_b:.6f}   ({Path(args.reference).name})")
    print(f"paired delta     : {mean_a - mean_b:+.6f}")
    print(f"rho(per-row)     : {rho:.3f}")
    print(f"SE(paired delta) : {se_paired:.6f}")
    print(f"  SE_paired <= margin/4 : {'PASS' if se_paired <= margin / 4 else 'FAIL'}")

    # Separability: reference/evaluation-design.md step 4, adapted from "across 20 seeds" to
    # "across bootstrap resamples" — the only meaningful version when there is one seed.
    n = len(deltas)
    wins = 0
    for _ in range(args.bootstrap):
        resample = math.fsum(deltas[rng.randrange(n)] for _ in range(n)) / n
        wins += resample < 0  # lower_is_better: the submission under test should be lower
    verdict = "PASS" if wins == args.bootstrap else f"FAIL ({wins}/{args.bootstrap})"
    print(f"ranking          : submission ranks better in {wins}/{args.bootstrap} bootstrap resamples  {verdict}")


if __name__ == "__main__":
    main()
