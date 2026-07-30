"""One-off local sizing check (mirrors referee.py's math, no Docker/gym_v1 needed).

Run from the competition root: python3 tools/sizing_check.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "baseline"))

import numpy as np

import submission as baseline
from env.tasks import TASK_TYPES, build_round, instance_seed, loss, reference_prediction, task_type_for_round

EPS = 1e-9
MAX_RAW = 5.0
N_TRAIN, N_TEST, N_INSTANCES = 500, 200, 20


def score_round(round_seed: int) -> tuple[str, float]:
    task_type = task_type_for_round(round_seed)
    instance_scores = []
    for i in range(N_INSTANCES):
        r = build_round(seed=instance_seed(round_seed, i), n_train=N_TRAIN, n_test=N_TEST, task_type=task_type)
        n_clusters = 3 if r.task_type == "clustering" else None
        model = baseline.fit(
            r.train_X.tolist(), r.train_y.tolist() if r.train_y is not None else None, r.task_type, n_clusters
        )
        preds = baseline.predict(model, r.test_X.tolist())
        sub_loss = loss(r.task_type, r.test_y, preds)
        ref_loss = loss(r.task_type, r.test_y, reference_prediction(r))
        instance_scores.append(min((ref_loss + EPS) / (sub_loss + EPS), MAX_RAW))
    return task_type, float(np.mean(instance_scores))


if __name__ == "__main__":
    by_task = {}
    for round_seed in range(len(TASK_TYPES) * 5):  # 5 full rotations = 30 rounds
        task_type, raw = score_round(round_seed)
        by_task.setdefault(task_type, []).append(raw)

    print(f"{'task_type':22s} {'n':>3s} {'mean':>8s} {'std':>8s}")
    for t in TASK_TYPES:
        vals = by_task.get(t, [])
        print(f"{t:22s} {len(vals):3d} {np.mean(vals):8.4f} {np.std(vals):8.4f}")

    all_vals = [v for vs in by_task.values() for v in vs]
    sigma_round = float(np.std(all_vals))
    mean = float(np.mean(all_vals))
    margin = 0.01 * mean  # 1% takeover margin at the baseline's own score
    print(f"\noverall n={len(all_vals)} mean={mean:.4f} sigma_round={sigma_round:.4f}")
    print(f"1% takeover margin at baseline mean: {margin:.5f}")
    print(f"sigma_round <= 1/4 x margin?  {sigma_round:.5f} <= {margin / 4:.5f}  ->  {sigma_round <= margin / 4}")
