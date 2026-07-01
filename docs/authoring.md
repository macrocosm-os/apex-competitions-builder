# Authoring an Apex competition

This walks through building a competition from scratch and getting it live.

## 1. Choose a shape

**Solo** — miners are scored independently against round input. One sandbox per submission.
Use this when a submission's quality can be measured without another player (compression,
prediction, optimization, single-agent RL).

**Duel** — submissions play against each other. N player sandboxes speak the `gym_v1` HTTP
protocol; a referee image you own holds the rules and reports the result. Use this for
games and any head-to-head evaluation.

## 2. Write the spec

Copy `examples/hello-world/spec.yaml` and edit it. The full contract is in
`src/apex_sdk/schema/apex.competition.v1.json`; the fields the platform cares about most:

- `id` / `version` — `(id, version)` is immutable once synced. Bump `version` for any change.
- `kind` — `solo` or `duel`.
- `resources` — per-sandbox `cpu_limit`, `mem_limit`, `gpu_count`. Must fit the env ceilings
  (stage: 2 CPU / 2Gi; prod: 4 CPU / 4Gi; memory floor 256Mi). GPUs are gated by the platform.
- `image` — your player image, **pinned by digest** (tags are forbidden).
- `submission` — `artifact_type` (`code` | `torchscript` | `onnx`), `max_size_mb`, and the
  `target_path` where the platform writes the miner's artifact for your entrypoint to load.
- `input_schema` — a JSON Schema (inline or `$ref`) for the round input. Emit it from your
  pydantic model rather than hand-writing it.
- `defaults` — eval/scheduling knobs: baselines, round length, reveal window, `lower_is_better`.
- `entrypoints.evaluate` — how the player sandbox runs. For duels, add `http_api` (port,
  readiness_path, `protocol: gym_v1`). Optional `generate_round` and `convert_model` entrypoints.
- `duel` — required for duels: `players_per_match`, `num_games_default`, `swap_sides`, and your
  `referee_image` (also digest-pinned) + `referee_timeout_s`.
- `signature` — the keyless cosign identity the platform verifies your image against.

## 3. Implement the image(s)

### Solo
Your image writes nothing special — its `evaluate` command loads the submission from
`target_path`, reads the round input, and writes `/data/result.json`:

```json
{ "raw_score": 0.87, "eval_time_in_seconds": 12.3, "metadata": {} }
```

See `examples/hello-world/player/evaluate.py`.

### Duel (gym_v1)
**Player** — wrap the submission in a `Player` and serve it:

```python
from apex_sdk.gym_v1 import Player, serve

class MyPlayer(Player):
    def reset(self, match_id, player_index, seed, config): ...
    def act(self, observation, deadline_ms): return chosen_action

serve(MyPlayer(), port=8000)   # exposes /health /reset /act
```

**Referee** — implement the rules and let the harness handle env + result.json:

```python
from apex_sdk.gym_v1 import Referee, GameResult, PlayerClient

class MyReferee(Referee):
    def play_game(self, ctx, players: list[PlayerClient]) -> GameResult:
        # drive the game via players[i].act(...); catch PlayerError to forfeit
        return GameResult(raw_scores=[1.0, 0.0], winner=0, terminal_reason="checkmate", steps=42)

if __name__ == "__main__":
    MyReferee().run()
```

The platform injects `MATCH_ID`, `SEED`, `CONFIG_JSON`, `PLAYER_URLS`, `NUM_PLAYERS` and
reads `/data/result.json`. A referee crash (or missing/invalid result.json) is scored as a
failed game attributed to the **referee**, not the submissions — so never write a zeroed
result to cover up a bug; let it fail.

## 4. Test locally

```bash
apex-dev preflight --spec ./spec.yaml --input fixtures/input.json   # schema + fixture, no Docker
apex-dev run       --spec ./spec.yaml --input fixtures/input.json   # full Docker run (parity with platform)
```

If it passes locally it will pass the platform's sync-time validation.

## 5. Ship it

1. Build + sign your image(s) with keyless cosign; push by digest.
2. Open a PR to `apex-competitions-registry`: `competitions/<id>/<version>.yaml`.
3. A Macrocosmos admin activates it via `active/<env>.yaml`. Stage first, then prod.
