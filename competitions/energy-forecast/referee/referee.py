"""energy_forecast gym_v1 REFEREE (the scorer sandbox, run at /app/referee.py).

Two modes, selected by the round input's `mode` (see input.schema.json):

- "backtest": every instance's target is already known (drawn from pinned
  history at a window the player has never been scored on). This is what
  today's synchronous single-shot referee contract supports end to end, and
  is enough for local dev, baseline training, and sigma_round sizing.
- "live": production mode. Instances are the freshest confirmed window per
  tracked BA with a target that has NOT happened yet at lock time -- this is
  the genuinely exploit-resistant "can't look up the future" mode the
  competition is designed around (see PLATFORM_PROPOSAL.md). Today's SDK has
  no delayed-scoring primitive, so this referee does the only thing it CAN do
  under the current single-shot contract: record each locked prediction into
  metadata and write a placeholder result (terminal_reason
  "pending_resolution", raw_score 0.0 -- NOT a real score). The proposed
  `entrypoints.resolve` (resolver/resolve.py) is what turns this into a real
  score once resolver/fetch_ground_truth.py publishes the outcome.

The player sandbox only ever sees the flattened (demand, calendar-feature)
observation vector for its own history window -- never the target, never
which other instances exist, never anything about future rounds.
"""

from __future__ import annotations

import time

from apex_sdk.gym_v1 import GameResult, Referee, RefereeContext
from apex_sdk.gym_v1.client import PlayerClient, PlayerError

from env import build_observation, instance_skill_score, sample_instances
from env.features import denormalize

DEFAULT_NUM_INSTANCES = 180
DEFAULT_DEADLINE_MS = 2000


class ForecastReferee(Referee):
    def play_game(self, ctx: RefereeContext, players: list[PlayerClient]) -> GameResult:
        start = time.monotonic()
        cfg = ctx.config or {}
        mode = cfg.get("mode", "backtest")
        num_instances = int(cfg.get("num_instances", DEFAULT_NUM_INSTANCES))
        deadline_ms = int(cfg.get("deadline_ms", DEFAULT_DEADLINE_MS))
        holdout_hours = int(cfg.get("holdout_hours", 0))  # dev/testing only, see env/data.py
        player = players[0]

        # All instances derive from the per-round master seed: every submission
        # in the round runs the exact same instances, so identical resubmissions
        # score identically -- no seed-fishing.
        instances = sample_instances(ctx.seed, num_instances, mode=mode, holdout_hours=holdout_hours)

        records = []
        for i, inst in enumerate(instances):
            player.reset(match_id=f"{ctx.match_id}:{i}", player_index=0, seed=ctx.seed, config={})
            obs = build_observation(inst.history, inst.history_timestamps)
            try:
                raw_pred = player.act(observation=obs.tolist(), deadline_ms=deadline_ms)
                prediction = denormalize(raw_pred, inst.history)
            except PlayerError:
                records.append({"instance_id": inst.instance_id, "ba": inst.ba, "gate": "player_error", "skill": 0.0})
                continue

            if mode == "live":
                # Target genuinely unknown yet: record the locked prediction
                # for resolve.py, do not score now.
                records.append(
                    {
                        "instance_id": inst.instance_id,
                        "ba": inst.ba,
                        "lock_timestamp": inst.lock_timestamp,
                        "target_timestamps": inst.target_timestamps,
                        "history": inst.history,
                        "locked_prediction": prediction.tolist(),
                    }
                )
                continue

            skill, diag = instance_skill_score(prediction, inst.target, inst.history)
            records.append({"instance_id": inst.instance_id, "ba": inst.ba, "skill": skill, **diag})

        if mode == "live":
            return GameResult(
                raw_scores=[0.0],  # placeholder -- see module docstring; not a real score
                winner=-1,
                terminal_reason="pending_resolution",
                steps=len(instances),
                metadata={
                    "mode": "live",
                    "locked_predictions": records,
                    "resolution_required": True,
                    "eval_time_in_seconds": round(time.monotonic() - start, 1),
                },
            )

        raw = sum(r["skill"] for r in records) / len(records)
        return GameResult(
            raw_scores=[raw],
            winner=0 if raw > 0 else -1,
            terminal_reason="scored",
            steps=len(instances),
            metadata={
                "mode": "backtest",
                "instances": records,
                "num_instances": len(records),
                "eval_time_in_seconds": round(time.monotonic() - start, 1),
            },
        )


if __name__ == "__main__":
    ForecastReferee().run()
