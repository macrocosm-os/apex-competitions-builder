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

Copy [`spec.yaml` from the hello-world example repo](https://github.com/macrocosm-os/apex-competition-hello-world/blob/main/spec.yaml)
and edit it. The full contract is in
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
- `submission` — `artifact_type` (`json` | `csv` | `onnx` | `wasm` | `torchscript` | `code` |
  `archive`), `max_size_mb`, and the `target_path` where the platform writes the miner's artifact
  for your player to load. `archive` also needs a `submission.archive` block. See
  [Submission artifact types](#submission-artifact-types) below.
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

### Submission artifact types

`submission.artifact_type` declares what the miner uploads and how the platform hands it to your
player. Pick the **most constrained type that can express a winning solution** — the list is in
increasing order of attack surface, and every step down costs you screening you'd rather not own.

| `artifact_type` | What the miner uploads | Written to `target_path` as | Layer-1 screening |
|---|---|---|---|
| `json` | A UTF-8 JSON document — a policy table, parameter vector, strategy spec | the file | parse validity, `max_rows`, `max_json_depth` |
| `csv` | A UTF-8 CSV with a header row — a lookup table, schedule, ranking | the file | parse validity, `max_rows`, `max_columns`, `required_columns` |
| `onnx` | An ONNX graph | the file | weights validator (`min_weight_bytes`, `max_code_weight_ratio`) |
| `wasm` | A WebAssembly module (`\0asm` magic) | the file | module header, `wasm_allowed_imports`, `wasm_max_memory_pages` |
| `torchscript` | A TorchScript `.pt` archive | the file | weights validator |
| `code` | One source file | the file | ASTGuard (`extra_forbidden_*`, `block_dynamic_getattr`) |
| `archive` | A `tar.gz` / `tar` / `zip` bundle — a multi-module Python package | an **extracted directory** | ASTGuard per Python member, `allowed_member_extensions`, extraction bounds |

`json` and `csv` are the closed-grammar formats to reach for first: there is no code to screen, and
your player validates structurally with typed errors. `wasm` is the middle ground when the
submission genuinely has to *compute* — a wasm module has no ambient authority, so it can only call
host functions you explicitly import (declare the allowlist in `screening.wasm_allowed_imports`;
the default is none at all).

**Multiple files / tarballs.** `artifact_type: archive` is the "several Python modules" case. Its
`target_path` is the **directory** the bundle is extracted into, and it requires a
`submission.archive` block that bounds extraction:

```yaml
submission:
  artifact_type: archive
  max_size_mb: 2                    # bounds the COMPRESSED upload
  target_path: /app/submission      # a directory; extracted here
  archive:
    format: tar.gz                  # tar.gz | tar | zip
    entry_file: main.py             # what your player imports, relative to the extraction root
    max_uncompressed_mb: 16         # the decompression-bomb bound; must be >= max_size_mb
    max_files: 200

screening:
  allowed_member_extensions: [".py"]   # anything else in the bundle fails screening
  extra_forbidden_modules: [socket, subprocess]
```

Members that are absolute, contain a `..` component, or are symlinks are **rejected** — the
submission fails, nothing is sanitised. Do set `allowed_member_extensions`: without it a bundle can
carry any file type, and a `[".py"]`-only bundle is the whole reason to prefer `archive` over an
opaque blob.

## 3. Implement the image(s)

Both solo and duel need a **player** image and a **referee** image. The
[hello-world example repo](https://github.com/macrocosm-os/apex-competition-hello-world) is a
complete, buildable pair (`player/`, `referee/`) — read it alongside this section. Solo is just a
1-player duel.

**How your image gets the toolkit — vendor it; do NOT build FROM the base images.**

- ✅ **Vendor (do this).** Copy this repo's `src/apex_sdk/gym_v1/` into your competition repo and
  build on a stock base (`FROM python:3.12-slim`); import the top-level package — `from
  gym_v1.player import Player, serve`, `from gym_v1.referee import Referee, GameResult`, `from
  gym_v1.client import PlayerClient`. This is what every shipped competition does and the only
  pattern that builds in your own repo's release CI. hello-world's
  [`player/Dockerfile`](https://github.com/macrocosm-os/apex-competition-hello-world/blob/main/player/Dockerfile)
  and its README's re-vendoring snippet show the whole mechanic.
- ❌ **Do NOT use `FROM apex-player-base` / `apex-referee-base`.** They bake the toolkit in (so you'd
  import `apex_sdk.gym_v1`), but they are **not published to any registry**, so the build only
  resolves on a machine that has `docker build`-ed the base locally — it will **fail in your release
  CI**. This is the intended future once the bases are published; it is not usable now.

The snippets below use the `apex_sdk.gym_v1` import root because that's how the package is named
**inside this repo**. In your competition repo the vendored package is top-level, so drop the
`apex_sdk.` prefix (`from gym_v1.player import Player, serve`). The classes and signatures are
identical either way.

**Player** — wrap the submission in a `Player` and serve it:

```python
from apex_sdk.gym_v1 import Player, serve      # vendored: from gym_v1.player import Player, serve

class MyPlayer(Player):
    def reset(self, match_id, player_index, seed, config): ...
    def act(self, observation, deadline_ms): return chosen_action

serve(MyPlayer(), port=8000)   # exposes /health /reset /act
```

**Referee** — implement the rules and let the harness handle env + result.json:

```python
from apex_sdk.gym_v1 import Referee, GameResult, PlayerClient   # vendored: from gym_v1.referee / gym_v1.client

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
# 1. Validate spec + input fixture + a sample submission. No Docker.
apex-dev preflight --spec ./spec.yaml --input fixtures/input.json \
                   --submission ./fixtures/reference_solution.json

# 2. Resolve + preview the run contract (player + referee, resources, protocol).
apex-dev run --spec ./spec.yaml --input fixtures/input.json \
             --submission ./player/submission.py \
             --dockerfile ./player/Dockerfile          # or: --image my-player:local
```

`apex-dev preflight` validates the spec against `apex.competition.v1` (including the ceilings)
and your input fixture against `input_schema` — a spec that passes preflight is one the platform
will accept at sync time. `--submission` additionally checks a sample artifact against the declared
`artifact_type` (JSON/CSV parse validity, wasm magic bytes, archive extraction bounds and member
safety, size ceilings) so your reference solution fails locally with a readable reason instead of
being rejected by the platform's screener after upload. For `artifact_type: archive` you can pass a
**directory** and it is validated as the tree that would be bundled. Preflight also prints `⚠`
advisories for the mistakes the platform tolerates silently — a `target_path` extension that
disagrees with the artifact type, or a `screening` knob that doesn't apply to it (and so is
ignored). `apex-dev run` validates the args and prints the resolved plan
(player + referee images, protocol, resources); **referee-driven local execution (spinning up the
player + referee sandboxes on a shared network) is not implemented yet** and exits 3 — run on
stage to execute. A local 2-sandbox harness is a follow-up.

## 5. Ship it

You choose the visibility of everything you own — repo, `spec.yaml`, and images can
each be **public or private**, independently. Visibility is a transparency choice, not
a technical requirement: the platform verifies and mirrors your images **by digest**
and has read access to pull private packages, so a fully private competition works end
to end (most production competitions run this way). What security depends on is the
signed digest, not who can see the source. The `apex-competitions-registry` that drives
the platform is always **private** (it's the control plane — it decides which image
digests are trusted and which competitions are live), so you don't open a PR against it
directly. Instead you hand your artifacts to Macrocosmos, who land the registry change
and activate it.

Whatever visibility you pick, treat anything in the **player image and repo as
potentially exposed** — keep ground truth, datasets, and scoring in the referee image
(and secret behavioural checks in the optional Layer-2 screen image); those stay private
regardless.

1. Build + sign your image(s) with keyless cosign; push by digest.
2. **Request onboarding** — open a [Competition onboarding issue](https://github.com/macrocosm-os/apex-competitions-builder/issues/new?template=competition-onboarding.yml)
   with your competition repo URL, the released tag, and the image ref + digest. A
   Macrocosmos maintainer copies your `spec.yaml` into the private registry
   (`competitions/<id>/<version>.yaml`), reviews it (digest pinned, cosign identity,
   resource ceilings), and opens the registry PR.
3. A Macrocosmos maintainer activates it via `active/<env>.yaml`. Stage first, then prod.

> The maintainer copies your `spec.yaml` verbatim from your repo (or the issue) — there's
> nothing to duplicate by hand. Keep it as the source of truth and bump the `version` for
> each release.
