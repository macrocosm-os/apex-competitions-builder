# Humanoid Parkour

Train a control policy that gets a MuJoCo humanoid through a hurdle course —
fast, on its feet, legs only. You submit a single **ONNX policy network**;
each round it is evaluated on a fresh set of procedurally generated courses,
and the fastest, most reliable policy leads the board.

## The task

- Straight 20 m track along +x with 3–6 box hurdles across it (heights
  0.05–0.35 m, harder tiers = taller and denser). Difficulty tiers: easy /
  medium / hard, evaluated in equal parts.
- Physics: the standard Gymnasium humanoid (vendored in
  [`env/assets_humanoid.xml`](env/assets_humanoid.xml)), 17 torque actuators,
  control at ~66 Hz (frame skip 5 × 3 ms).
- An episode ends on: **completed** (crossed x = 20), **fell** (torso below
  1.0 m, or any body part except the feet touching the floor — no crawling),
  **out_of_bounds** (|y| > 2 — you can't run around the hurdles),
  **physics_glitch** (NaN/exploding state — scores 0, don't surf solver bugs),
  or **timeout** (900 control steps = 13.5 s; you need to average ≥ 1.5 m/s
  to finish).

## Scoring

Per course instance (higher is better):

| Outcome | Instance score |
|---|---|
| Completed | `1 + (max_steps - steps) / max_steps` → (1.0, 2.0] |
| Fell / timeout / out of bounds | fraction of course covered → [0, 1) |
| Physics glitch / invalid action / player error | 0 |

Any completion beats any non-completion; among completions, faster is better;
partial progress still pays, so early policies have a gradient to climb.
**raw_score = mean over all 120 course instances** (40 per difficulty). A new
submission takes the lead by beating the top raw score by ≥ 1%.

The released baseline (`baseline/baseline.onnx`, PPO, ~110M steps — see
`baseline/PROVENANCE.md`) scores **0.696**: it runs at ~3.5 m/s, completes
most easy courses in ~5–6 s and some mediums, but clears no hard courses and
still falls on ~80% of the full mix. Beating it means out-running it or
out-surviving it; a policy that reliably completes all three tiers scores
> 1.3 and laps the field.

Courses are derived from a per-round master seed injected into the referee:
every submission in a round runs the exact same 120 courses, and resubmitting
an identical policy scores identically — seed-fishing buys nothing. Next
round, fresh courses: memorizing layouts doesn't transfer; robust locomotion
does.

## Submission contract (ONNX only — no code)

- Exactly one input: `float32 [1, 56]` (or dynamic batch dim) — one output:
  `float32 [1, 17]`.
- ≤ 25 MB, **single file with weights embedded** — an export that references
  an external `.data` sidecar will fail to load (the platform writes exactly
  one artifact file). `train_baseline.py`'s `embed_external_data()` fixes
  torch exports that split weights out.
- Loaded with onnxruntime (CPU, single-threaded) by the public player image;
  a non-conforming model is rejected at load.
- Actions are clipped to the actuator range ±0.4 by the evaluator. Bake any
  observation normalization into the graph — evaluation feeds raw
  observations (see `ExportablePolicy` in
  [`baseline/train_baseline.py`](baseline/train_baseline.py)).

Observation layout (`env/sim.py` is the source of truth):

| Index | Content |
|---|---|
| 0 | torso y (stay inside ±2) |
| 1 | distance to finish (20 − x) |
| 2:24 | `qpos[2:]` — torso z, orientation quaternion, joint angles |
| 24:47 | `qvel` |
| 47:56 | next 3 hurdles: (Δx, height, depth) each; (50, 0, 0) padding |

## Train locally

Everything used in evaluation is in this repo — same physics, same courses,
same gates:

```bash
pip install mujoco==3.10.0 numpy==2.3.4 gymnasium onnxruntime==1.28.0

# Gymnasium env sampling random courses every episode:
python - <<'PY'
from env.gym_env import HumanoidParkourEnv
env = HumanoidParkourEnv()
obs, info = env.reset(seed=0)
print(obs.shape, info)
PY

# Reference PPO recipe (any algorithm works; only the ONNX artifact matters):
python baseline/train_baseline.py --steps 20000000 --out my_policy.onnx

# Score it through the real player+referee loop, exactly as evaluated:
python tools/local_eval.py --onnx my_policy.onnx --seed 0
```

The shaped reward in `env/gym_env.py` is a starting point, not the metric —
the leaderboard only pays for completion and speed.

## What you see after each round

Per-course breakdowns (difficulty, terminal reason, progress, steps, score)
are revealed when a round completes, along with the round's seed. Submissions
become downloadable by other miners after the 5-day reveal window — a real
improvement is protected for 5 days, then becomes the field's new floor.
