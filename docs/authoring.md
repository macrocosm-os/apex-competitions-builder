# Authoring an Apex competition

This walks through building a competition from scratch and getting it live.

## 1. Choose a shape

Every competition runs the miner submission in an isolated **player** sandbox and scores it
from a separate, competition-owned **referee** sandbox — the submission and your scoring logic
never share a sandbox, so a submission can't read/patch the scorer or fabricate its result.
You always author two images: a player and a referee.

**Solo** — miners are scored independently against round input (a **1-player duel**). Use this
when quality can be measured without another player (compression, prediction, optimization,
single-agent RL). One player sandbox + one referee — or, via `solo.player_sandboxes`, several
isolated sandboxes running the same submission so its phases can't share state (still one referee).

**Duel** — submissions play against each other. N player sandboxes + one referee that holds the
rules. Use this for games and any head-to-head evaluation.

## 2. Write the spec

Copy `examples/hello-world/spec.yaml` and edit it. The full contract is in
`src/apex_sdk/schema/apex.competition.v1.json`; the fields the platform cares about most:

- `id` / `version` — `(id, version)` is immutable once synced. Bump `version` for any change.
- `kind` — `solo` or `duel`.
- `solo` (optional, solo only) — `player_sandboxes` to run the SAME submission in N mutually-isolated
  sandboxes (own memory + filesystem) instead of the default 1. The referee receives that many
  `PLAYER_URLS`. Use it when distinct phases of one submission must not pass state to each other
  (e.g. a compressor sandbox and a separate decompressor sandbox). Omit for the usual 1 sandbox.
- `resources` — per-sandbox `cpu_limit`, `mem_limit`, `gpu_count`. Must fit the env ceilings
  (stage: 2 CPU / 2Gi; prod: 4 CPU / 4Gi; memory floor 256Mi). GPUs are gated by the platform.
- `image` — your **player** image, **pinned by digest** (tags are forbidden).
- `submission` — `artifact_type` (`code` | `torchscript` | `onnx`), `max_size_mb`, and the
  `target_path` where the platform writes the miner's artifact for your player to load.
- `input_schema` — a JSON Schema (inline or `$ref`) for the round input. Emit it from your
  pydantic model rather than hand-writing it.
- `defaults` — eval/scheduling knobs: baselines, round length, reveal window, `lower_is_better`.
- `entrypoints.evaluate` — how the **player** sandbox runs, including `http_api` (port,
  `readiness_path`, `protocol`) — **required for both solo and duel**. Optional `generate_round`
  and `convert_model` entrypoints.
- `referee` — **required for both solo and duel**: `protocol` (`gym_v1` | `custom`), your
  `image` (digest-pinned, like the player), and `timeout_s`. The referee runs by convention at
  `/app/referee.py`.
- `duel` — required for duels only: `players_per_match`, `num_games_default`, `swap_sides`.
- `signature` — the keyless cosign identity the platform verifies your images against.

## 3. Implement the image(s)

Both solo and duel need a **player** image and a **referee** image (see
`examples/hello-world/player/` and `.../referee/`). Solo is just a 1-player duel.

**How your image gets the SDK — two patterns, and the import root differs:**

- **Vendored (current convention).** Copy the SDK's `gym_v1/` into your competition repo and
  build on a stock base (`FROM python:3.12-slim`); import the top-level package —
  `from gym_v1.player import Player, serve`. This is what shipped competitions do, because the
  base images below are **not published to a registry yet**, so vendoring is what builds in your
  own repo's release CI.
- **Build-FROM-base (intended end-state).** `apex-player-base` / `apex-referee-base` bake the SDK
  in, so you import `apex_sdk.gym_v1` (as the snippets and `examples/hello-world/` do). Until the
  bases are published you must `docker build` them locally first (step 3 setup) — so this path
  does not yet work in an external competition's CI.

The snippets below use the `apex_sdk.gym_v1` root; if you vendor, drop the `apex_sdk.` prefix
(`from gym_v1.player import Player, serve`, `from gym_v1.referee import Referee, GameResult`,
`from gym_v1.client import PlayerClient`).

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
# 1. Validate spec + input fixture. No Docker.
apex-dev preflight --spec ./spec.yaml --input fixtures/input.json

# 2. Resolve + preview the run contract (player + referee, resources, protocol).
apex-dev run --spec ./spec.yaml --input fixtures/input.json \
             --submission ./player/submission.py \
             --dockerfile ./player/Dockerfile          # or: --image my-player:local
```

`apex-dev preflight` validates the spec against `apex.competition.v1` (including the ceilings)
and your input fixture against `input_schema` — a spec that passes preflight is one the platform
will accept at sync time. `apex-dev run` validates the args and prints the resolved plan
(player + referee images, protocol, resources); **referee-driven local execution (spinning up the
player + referee sandboxes on a shared network) is not implemented yet** and exits 3 — run on
stage to execute. A local 2-sandbox harness is a follow-up.

## 5. Ship it

Everything you own is public: your competition repo, your `spec.yaml`, and your
signed image. The `apex-competitions-registry` that drives the platform is **private**
(it's the control plane — it decides which image digests are trusted and which
competitions are live), so you don't open a PR against it directly. Instead you hand
your artifacts to Macrocosmos, who land the registry change and activate it.

1. Build + sign your image(s) with keyless cosign; push by digest.
2. **Request onboarding** — open a [Competition onboarding issue](https://github.com/macrocosm-os/apex-competitions-sdk/issues/new?template=competition-onboarding.yml)
   with your competition repo URL, the released tag, and the image ref + digest. A
   Macrocosmos maintainer copies your `spec.yaml` into the private registry
   (`competitions/<id>/<version>.yaml`), reviews it (digest pinned, cosign identity,
   resource ceilings), and opens the registry PR.
3. A Macrocosmos maintainer activates it via `active/<env>.yaml`. Stage first, then prod.

> Because your `spec.yaml` lives in your public repo, the maintainer copies it verbatim
> — there's nothing to duplicate by hand. Keep it as the source of truth and bump the
> `version` for each release.
