# apex-competition-sdk

The public SDK for building [Apex](https://macrocosmos.ai) competitions.

An Apex competition is a **declarative, versioned, signed spec** (`apex.competition.v1`) plus
the container image(s) that run it. The platform never imports competition code — it reads
your spec, mirrors your signed image, and executes it through generic runners. This SDK gives
you everything you need to author a spec the platform will accept and run it locally exactly
as the platform would.

## What's in here

| Path | What it is |
|------|-----------|
| `src/apex_sdk/schema/apex.competition.v1.json` | The spec JSON Schema. The platform validates against this exact file. |
| `src/apex_sdk/spec.py` | Load + validate a spec, resolve its `input_schema`, enforce resource ceilings. |
| `src/apex_sdk/gym_v1/` | The duel wire protocol: player server base, referee harness, referee→player client. |
| `src/apex_sdk/dev/cli.py` | `apex-dev` — `preflight` and `run` your spec locally. |
| `examples/hello-world/` | A minimal solo competition: spec, input schema, fixture, reference submission. |
| `images/` | Base image Dockerfiles (`player-base`, `referee-base`). |
| `skills/apex-competition-builder/` | Design guide + agent skill for authoring a competition end-to-end: submission-format doctrine, evaluation sizing, anti-exploit checklist, onboarding manifest. |

## Install

```bash
pip install -e .          # or: uv pip install -e .
apex-dev --help
```

## Quickstart

```bash
# Validate a spec and an input fixture — no Docker. Run this before opening a registry PR.
apex-dev preflight --spec examples/hello-world/spec.yaml \
                   --input examples/hello-world/fixtures/input.json

# Run the solo eval locally in Docker, exactly like the platform. apex-dev builds the
# player image from the Dockerfile (or pass --image <local-tag> to reuse a prebuilt one),
# writes the submission to submission.target_path, and validates /data/result.json.
apex-dev run --spec examples/hello-world/spec.yaml \
             --input examples/hello-world/fixtures/input.json \
             --submission examples/hello-world/player/submission.py \
             --dockerfile examples/hello-world/player/Dockerfile
```

## The competition shapes

Both shapes are referee-driven and both write the same result: a solo eval is a 1-player duel.
The miner submission never shares a sandbox with the scorer.

- **solo** (`kind: solo`) — one player sandbox speaking `gym_v1`, plus the competition-owned
  referee that scores it.
- **duel** (`kind: duel`) — N player sandboxes, plus a referee that runs the match between them.

Either way the referee writes `/data/result.json` =
`{raw_scores, winner, terminal_reason, steps, metadata}` (see `apex_sdk.gym_v1.GameResult`).

A common solo variant is the **fixed-dataset prediction** competition: the test features are
public and constant, the miner submits a CSV of predictions (`submission.artifact_type: csv`),
and the referee scores it against ground truth supplied via `private_data` — a private object
the platform mounts read-only into the referee only. See
`competitions/otto-product-classification/`.

Another solo variant is the **harness** competition: the *model* is held fixed and the miner
submits the scaffolding around it (`submission.artifact_type: code`). Declare the frozen
model with `base_model` and the platform serves it, metered, reachable from the referee
only — so the referee makes every call on the harness's behalf and the token budget cannot
be gamed. See `docs/authoring.md` §2c and `competitions/research-harness/`.

See `docs/authoring.md` for the full authoring flow and `src/apex_sdk/gym_v1/` for the
protocol contracts (with docstrings).

## How a competition ships

1. Fork the example competition repo; implement your player and referee images.
2. `apex-dev preflight` and `apex-dev run` until it passes locally.
3. Build + sign your image(s) (keyless cosign) and push to your registry.
4. Open a PR to `apex-competitions-registry` adding `competitions/<id>/<version>.yaml`.
5. A Macrocosmos admin activates it by merging an `active/<env>.yaml` change.

> Activation is admin-gated. Designers self-serve their competition folder; going live is
> platform-controlled.
