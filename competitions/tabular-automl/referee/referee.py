"""tabular_automl gym_v1 REFEREE.

Design (see HANDOFF.md for the full rationale): the miner does NOT submit a
pre-trained model. It submits CODE that, given this round's freshly generated
training data, fits a model and predicts on the held-out test rows -- exactly
like a Kaggle competition. That means:

  - No train-then-submit round cadence is needed: training happens inline,
    every time the submission is evaluated, on whatever data this round's SEED
    produced. The platform's existing "submit anytime, evaluated against the
    current round's seed" model is sufficient.
  - No round-scoping problem: the same submission stays coherent across
    rounds because it's a training *strategy*, not a model fit to one round's
    distribution.
  - Task type (regression / classification / timeseries / clustering /
    anomaly_detection / symbolic_regression) rotates per round without
    invalidating `defaults.baseline_raw_score`: raw_score is always a
    normalized, lower-is-better loss ratio against a reference model fit on
    the SAME round's data, so it's comparable across task types (see
    env/tasks.py `loss`).

Reward = one continuous term (normalized loss ratio) + three HARD binary
gates (train time, inference time, complexity) per the design brief. A gate
failure zeroes raw_score outright; it is not blended into a continuous
penalty.
"""

from __future__ import annotations

import time

from apex_sdk.gym_v1 import GameResult, Referee, RefereeContext
from apex_sdk.gym_v1.client import PlayerClient, PlayerError

from env.tasks import N_CLUSTERS, build_round, instance_seed, loss, reference_prediction, task_type_for_round

EPS = 1e-9
MAX_RAW_SCORE = 5.0  # clip: a submission 5x better than the reference is scored the same as 5.01x
GATE_GRACE_S = 5.0  # HTTP/serialization overhead on top of the hard wall-clock cap


class TabularAutoMLReferee(Referee):
    def play_game(self, ctx: RefereeContext, players: list[PlayerClient]) -> GameResult:
        cfg = ctx.config
        n_train, n_test = cfg["n_train"], cfg["n_test"]
        n_instances = cfg["n_instances"]
        max_train_time_s = cfg["max_train_time_s"]
        inference_deadline_ms = cfg["inference_deadline_ms"]
        max_complexity = cfg["max_complexity"]

        task_type = task_type_for_round(ctx.seed)
        player = players[0]

        # A round scores `n_instances` independent dataset draws of the SAME task family and
        # averages raw_score across them -- one draw per round is exactly the under-sized-
        # evaluation mistake this repo's own evaluation-design guidance warns about (see
        # reference/evaluation-design.md and HANDOFF.md Sec 4 for the measured justification).
        instance_scores = []
        for i in range(n_instances):
            round_ = build_round(
                seed=instance_seed(ctx.seed, i), n_train=n_train, n_test=n_test, task_type=task_type
            )

            train_start = time.monotonic()
            try:
                player.reset(
                    match_id=f"{ctx.match_id}-{i}",
                    player_index=0,
                    seed=instance_seed(ctx.seed, i),
                    config={
                        "task_type": round_.task_type,
                        "train_X": round_.train_X.tolist(),
                        "train_y": round_.train_y.tolist() if round_.train_y is not None else None,
                        "max_complexity": max_complexity,
                        # Public problem specification, not ground truth (like n_classes=2 for
                        # classification): "how many groups to find" for clustering rounds.
                        "n_clusters": N_CLUSTERS if round_.task_type == "clustering" else None,
                    },
                    timeout_s=max_train_time_s + GATE_GRACE_S,
                )
            except PlayerError as e:
                return _gated_result(task_type, "train_timeout_or_error", f"instance {i}: {e}", n_instances)
            train_time_s = time.monotonic() - train_start
            if train_time_s > max_train_time_s:
                return _gated_result(
                    task_type, "train_timeout", f"instance {i}: {train_time_s:.2f}s > {max_train_time_s}s", n_instances
                )

            try:
                action = player.act(observation=round_.test_X.tolist(), deadline_ms=inference_deadline_ms)
            except PlayerError as e:
                return _gated_result(task_type, "inference_timeout_or_error", f"instance {i}: {e}", n_instances)

            if not isinstance(action, dict) or "predictions" not in action:
                return _gated_result(
                    task_type, "malformed_action", f"instance {i}: expected " "{'predictions', 'complexity'}", n_instances
                )

            complexity = action.get("complexity")
            if complexity is None or complexity > max_complexity:
                return _gated_result(
                    task_type, "complexity_exceeded", f"instance {i}: {complexity} > {max_complexity}", n_instances
                )

            try:
                submission_loss = loss(round_.task_type, round_.test_y, action["predictions"])
            except (ValueError, TypeError) as e:
                return _gated_result(task_type, "invalid_predictions", f"instance {i}: {e}", n_instances)

            reference_loss = loss(round_.task_type, round_.test_y, reference_prediction(round_))
            # EPS on both sides: if the task is solved to near-zero loss by both models (e.g. a
            # noiseless symbolic-regression instance), flooring only the denominator would
            # collapse the ratio toward 0 instead of the correct ~1 (tie with the reference).
            instance_scores.append(min((reference_loss + EPS) / (submission_loss + EPS), MAX_RAW_SCORE))

        raw = sum(instance_scores) / len(instance_scores)
        return GameResult(
            raw_scores=[raw],
            winner=0,
            terminal_reason="scored",
            steps=n_instances,
            metadata={
                "task_type": task_type,
                "n_instances": n_instances,
                "instance_scores": instance_scores,
            },
        )


def _gated_result(task_type: str, reason: str, detail: str, n_instances: int) -> GameResult:
    """A hard-gate failure on ANY instance zeros the whole round's raw_score (fail-closed) --
    a submission cannot bank on being fast/small most of the time and cheating once."""
    return GameResult(
        raw_scores=[0.0],
        winner=-1,
        terminal_reason=reason,
        steps=0,
        metadata={"task_type": task_type, "detail": detail, "n_instances": n_instances},
    )


if __name__ == "__main__":
    TabularAutoMLReferee().run()
