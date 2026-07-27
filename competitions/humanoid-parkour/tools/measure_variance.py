"""Evaluation-sizing evidence for HANDOFF.md §4.

Evaluates one policy across >= 20 master seeds and reports sigma_round against
the platform's 1% takeover margin (requirement: sigma_round <= margin / 4, see
reference/evaluation-design.md). Run with the trained baseline AND at least
one deliberately different reference policy, and check they rank consistently
across every seed.

    python tools/measure_variance.py --onnx baseline.onnx --seeds 20
"""

from __future__ import annotations

import argparse
import statistics

from local_eval import evaluate_once

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--onnx", required=True)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--courses-per-difficulty", type=int, default=8)
    args = parser.parse_args()

    scores = []
    for seed in range(args.seeds):
        result = evaluate_once(args.onnx, seed, args.courses_per_difficulty)
        scores.append(result.raw_scores[0])
        print(
            f"seed {seed:>3}: raw_score {scores[-1]:.4f} "
            f"({result.metadata['num_completed']}/{result.metadata['num_courses']} completed, "
            f"{result.metadata['eval_time_in_seconds']}s)"
        )

    mean = statistics.mean(scores)
    sigma = statistics.stdev(scores)
    margin = 0.01 * mean  # takeover threshold is 1% of the top raw score
    print(f"\nmean raw_score : {mean:.4f}")
    print(f"sigma_round    : {sigma:.4f}")
    print(f"1% margin      : {margin:.4f} (margin/4 = {margin / 4:.4f})")
    print(f"sigma_round <= margin/4: {'PASS' if sigma <= margin / 4 else 'FAIL — raise N or reduce variance'}")
