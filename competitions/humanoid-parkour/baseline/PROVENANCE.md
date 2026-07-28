# Baseline provenance

`baseline.onnx` (sha256 `5e615c33c1ad2f9f1f01e96d56af6edf72c4775ae4d2de1d4973100a0d62a6f4`)
is a PPO policy trained in three stages, all on the `train_baseline.py` recipe's
architecture (MlpPolicy 256×256, VecNormalize baked into the export):

1. **Recipe run** — `train_baseline.py`, 15M steps, 12 envs
   (reward: forward 1.25 / alive 1.0 / ctrl 0.1, completion bonus 10×).
2. **Extended run** — warm-start continuation of (1) for ~75M further steps,
   same reward (wandb: `macrocosmos/humanoid-parkour/runs/rmco4ba7`).
3. **Low-LR consolidation** — ~20M steps from the best checkpoint of (2) at a
   fixed learning rate 5e-5, same reward
   (wandb: `macrocosmos/humanoid-parkour/runs/51cly8j7`). The shipped model is
   the best consolidation checkpoint, selected on 24 held-out courses.

Total ≈ 110M environment steps (~8 h on a 14-core laptop). Anything the
recipe's defaults produce is a valid starting point; this file only documents
how the official artifact was made.
