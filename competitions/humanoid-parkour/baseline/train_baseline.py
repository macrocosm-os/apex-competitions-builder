"""Train the PPO baseline and export it to the competition's ONNX contract.

This is both the official baseline (seeds the leaderboard; must score > 0 end
to end) and the reference training recipe miners start from. Any training
algorithm works — only the exported ONNX policy is submitted.

    pip install stable-baselines3 torch
    python baseline/train_baseline.py --steps 20000000 --out baseline.onnx

Expect humanoid locomotion to need on the order of 1e7-2e7 PPO steps for a
policy that runs and clears low hurdles (hours on a multicore CPU box).
Verify with:  python tools/local_eval.py --onnx baseline.onnx --seed 0
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from env.gym_env import HumanoidParkourEnv  # noqa: E402
from env.sim import ACT_DIM, CTRL_RANGE, OBS_DIM  # noqa: E402


def embed_external_data(path: str) -> None:
    """Repack an ONNX file so all weights live inline in the single .onnx file.

    Newer torch exporters write initializers to a sidecar `<path>.data` file.
    The platform writes exactly ONE artifact file to `submission.target_path`,
    so a submission that references external data will fail to load — always
    run the export through this before submitting.
    """
    import onnx

    model = onnx.load(path)  # pulls any external data into raw_data
    for tensor in model.graph.initializer:
        if tensor.data_location == onnx.TensorProto.EXTERNAL:
            tensor.ClearField("external_data")
            tensor.data_location = onnx.TensorProto.DEFAULT
    onnx.save(model, path)
    Path(path + ".data").unlink(missing_ok=True)


class ExportablePolicy(torch.nn.Module):
    """Deterministic SB3 PPO policy with VecNormalize baked into the graph.

    The submission must be self-contained: evaluation feeds raw observations,
    so the normalization statistics have to live inside the ONNX graph.
    """

    def __init__(self, model, obs_rms, clip_obs: float = 10.0):
        super().__init__()
        self.policy_net = model.policy.mlp_extractor.policy_net
        self.action_net = model.policy.action_net
        self.register_buffer("obs_mean", torch.as_tensor(obs_rms.mean, dtype=torch.float32))
        self.register_buffer("obs_std", torch.as_tensor(np.sqrt(obs_rms.var + 1e-8), dtype=torch.float32))
        self.clip_obs = clip_obs

    def forward(self, obs: torch.Tensor) -> torch.Tensor:
        obs = torch.clamp((obs - self.obs_mean) / self.obs_std, -self.clip_obs, self.clip_obs)
        action = self.action_net(self.policy_net(obs))
        return torch.clamp(action, -CTRL_RANGE, CTRL_RANGE)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=20_000_000)
    parser.add_argument("--n-envs", type=int, default=8)
    parser.add_argument("--out", default="baseline.onnx")
    parser.add_argument("--checkpoint-dir", default="checkpoints")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import CheckpointCallback
    from stable_baselines3.common.vec_env import SubprocVecEnv, VecNormalize

    venv = VecNormalize(
        SubprocVecEnv([HumanoidParkourEnv] * args.n_envs),
        norm_obs=True,
        norm_reward=True,
    )
    model = PPO(
        "MlpPolicy",
        venv,
        n_steps=2048,
        batch_size=4096,
        learning_rate=3e-4,
        gamma=0.99,
        gae_lambda=0.95,
        ent_coef=0.0,
        policy_kwargs=dict(net_arch=dict(pi=[256, 256], vf=[256, 256])),
        seed=args.seed,
        verbose=1,
    )
    checkpoint = CheckpointCallback(
        save_freq=max(1_000_000 // args.n_envs, 1),
        save_path=args.checkpoint_dir,
        name_prefix="baseline",
        save_vecnormalize=True,
    )
    model.learn(total_timesteps=args.steps, progress_bar=True, callback=checkpoint)
    model.save(Path(args.out).with_suffix(".zip"))
    venv.save(str(Path(args.out).with_suffix(".vecnorm.pkl")))

    exportable = ExportablePolicy(model, venv.obs_rms).eval()
    torch.onnx.export(
        exportable,
        torch.zeros(1, OBS_DIM),
        args.out,
        input_names=["obs"],
        output_names=["action"],
        opset_version=17,
    )
    embed_external_data(args.out)
    print(f"exported {args.out} (obs [1,{OBS_DIM}] -> action [1,{ACT_DIM}], weights embedded)")


if __name__ == "__main__":
    main()
