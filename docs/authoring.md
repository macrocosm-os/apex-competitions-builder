# Authoring an Apex competition

This walks through building a competition from scratch and getting it live.

## 1. Choose a shape

Every competition runs the miner submission in an isolated **player** sandbox and scores it
from a separate, competition-owned **referee** sandbox — the submission and your scoring logic
never share a sandbox, so a submission can't read/patch the scorer or fabricate its result.
You always author two images: a player and a referee.

**Solo** — miners are scored independently against round input (a **1-player duel**). Use this
when quality can be measured without another player (compression, prediction, optimization,
single-agent RL). One player sandbox + one referee.

**Duel** — submissions play against each other. N player sandboxes + one referee that holds the
rules. Use this for games and any head-to-head evaluation.

**Prediction / fixed test set (Kaggle-style)** — a solo variant worth calling out. The test
*features* are public and constant; the miner submits a CSV of predictions
(`submission.artifact_type: csv`) and the referee scores it against ground truth only it can
read, supplied by the platform via `private_data` (§2b). The player image is a trivial CSV
server, and there is no code or model to screen. Reference implementation:
`competitions/otto-product-classification/`.

## 2. Write the spec

Copy `examples/hello-world/spec.yaml` and edit it. The full contract is in
`src/apex_sdk/schema/apex.competition.v1.json`; the fields the platform cares about most:

- `id` / `version` — `(id, version)` is immutable once synced. Bump `version` for any change.
- `kind` — `solo` or `duel`.
- `resources` — per-sandbox `cpu_limit`, `mem_limit`, `gpu_count`. Must fit the env ceilings
  (stage: 2 CPU / 2Gi; prod: 4 CPU / 4Gi; memory floor 256Mi). GPUs are gated by the platform.
- `image` — your **player** image, **pinned by digest** (tags are forbidden).
- `submission` — `artifact_type` (`csv` | `onnx` | `torchscript` | `code`, most constrained
  first), `max_size_mb`, and the `target_path` where the platform writes the miner's artifact
  for your player to load.
- `private_data` — optional; see §2b.
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

## 2b. Private ground truth (`private_data`)

Some competitions need scoring data that must not be public and must not sit in a pullable image
layer — test labels, an answer key, a held-out pool. Declare it and the platform handles it:

```yaml
private_data:
  - uri: r2://apex-private/my_competition/test_labels.csv
    mount_path: /private/test_labels.csv
    sha256: "a3f1..."          # of the object's bytes
    read_only: true
```

The contract, in four points:

1. The **platform** resolves `uri` with its own credentials. Your referee never sees them, and
   the object is never public.
2. The bytes are **verified against `sha256` before every job**. A mismatch fails the job as a
   *platform* error, never as a submission failure.
3. It is mounted at `mount_path` **read-only, in the referee only** — never in a player sandbox.
4. Your referee **must not fetch anything**. Sandboxes have no egress, so an unmounted object is
   simply absent, and the right response is to fail loudly rather than score without it.

Changing the bytes means a new `sha256` and a new spec `version`. You hand the object to a
Macrocosmos maintainer at onboarding — designers get no write access to the bucket — and they
return the digest you paste into the spec.

## 2c. A fixed base model (`base_model`) — harness competitions

Some competitions hold the *model* fixed and ask miners for the **scaffolding**: the
retrieval loop, the context management, the verification passes, the budget allocation.
The miner submits `artifact_type: code`, and every submission drives the same frozen model.

```yaml
base_model:
  served_model: "Qwen/Qwen3-8B"
  max_tokens_per_episode: 28000
  temperature: 0
  max_output_tokens: 512

referee:
  allow_internet: true      # required: the referee reaches the endpoint
entrypoints:
  evaluate:
    allow_internet: false   # required: the player must NOT
```

The platform serves the model outside the sandboxes and injects `MODEL_BASE_URL`,
`MODEL_NAME`, `MODEL_TEMPERATURE`, `MODEL_MAX_OUTPUT_TOKENS` and `MODEL_TOKEN_BUDGET` into
the **referee only**.

**Make the model a tool in your referee, not a sidecar for the harness.** The harness asks
the referee for a completion; the referee makes the call. This is the design the block
exists to support, and it is what makes a harness competition well-posed:

- **Metering cannot be gamed** — the party that counts the tokens is the party that spends
  them. A player-side model call would be self-reported, and the token budget is usually
  the scarce resource the whole competition is built around. `apex-dev preflight` rejects
  `base_model` together with player egress for exactly this reason.
- **Sampling is pinned by the spec**, not chosen per submission, so every harness faces an
  identical model and a round is reproducible from its seed.
- **The call log is evidence.** Put `model_calls` and `tokens_spent` in `metadata` and
  "did this submission actually use the model" becomes observed rather than inferred.
- **Inference capacity lives outside the per-sandbox ceilings**, which no sandbox-hosted
  model could fit.

The hardest part of designing one of these is making the model *load-bearing* — otherwise
the winning submission is a hand-written solver that ignores it, and you cannot detect that
reliably. The strongest available answer is structural: never hand the submission the raw
material. In `competitions/research-harness/` the harness can see that a document exists
and can move it into a referee-side context buffer, but only the model ever sees the text,
so the only channel from corpus to submission runs through the model.

`max_tokens_per_episode` is a cost control the platform enforces; your referee may ration
below it but never above it. Treat it as a design lever, not just a limit — scarcity is
what turns "can you be correct" into "how much correctness per token", which is the skill
a harness competition is actually for.

Reference implementation: `competitions/research-harness/`.

## 3. Implement the image(s)

Both solo and duel need a **player** image and a **referee** image (see
`examples/hello-world/player/` and `.../referee/`). Solo is just a 1-player duel.

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

# 3. If your spec declares private_data, supply one local file per entry.
apex-dev run --spec ./spec.yaml --input fixtures/input.json \
             --submission ./submission.csv --image my-player:local \
             --private-data /private/test_labels.csv=./private/test_labels.csv
```

`--private-data` verifies the **same sha256 the platform verifies**, so a stale or wrong local
ground-truth file fails at exit 2 rather than silently scoring against the wrong answers.

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
