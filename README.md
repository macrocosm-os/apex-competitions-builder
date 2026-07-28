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
| `images/` | Base image Dockerfiles (`player-base`, `referee-base`). Not published to a registry — see the vendoring note below. |
| `skills/apex-competition-builder/` | Design guide + agent skill for authoring a competition end-to-end: submission-format doctrine, evaluation sizing, anti-exploit checklist, onboarding manifest. |

## The worked example

The example competition lives in its own repo, laid out exactly like a real competition:

**[macrocosm-os/apex-competition-hello-world](https://github.com/macrocosm-os/apex-competition-hello-world)** — a minimal solo competition (spec, input schema, fixture, player image, referee image, baseline submission, release workflow). **Fork it to start your own.**

It is also the reference for how your images get the SDK: **vendor** this repo's
`src/apex_sdk/gym_v1/` into your competition repo and build `FROM python:3.12-slim`, importing
the top-level `gym_v1`. Do **not** build `FROM apex-player-base` / `apex-referee-base` — those
bases aren't published to any registry, so they only resolve on a machine that built them
locally and will fail in your release CI. See `docs/authoring.md` § "How your image gets the SDK".

## Install

```bash
pip install -e .          # or: uv pip install -e .
apex-dev --help
```

## Quickstart

```bash
git clone https://github.com/macrocosm-os/apex-competition-hello-world
cd apex-competition-hello-world

# Validate a spec and an input fixture — no Docker. Run this before requesting onboarding.
apex-dev preflight --spec ./spec.yaml --input fixtures/input.json

# Resolve and preview the execution plan (player + referee images, protocol, resources).
apex-dev run --spec ./spec.yaml --input fixtures/input.json \
             --submission ./player/submission.py \
             --dockerfile ./player/Dockerfile
```

`apex-dev run` prints the plan and exits 3 — referee-driven local execution (both sandboxes on a
shared network) is a follow-up. The hello-world README shows how to run the pair by hand
meanwhile.

## The two competition shapes

- **solo** (`kind: solo`) — one player sandbox. The platform writes the submission to
  `submission.target_path`, runs `entrypoints.evaluate.command`, and reads
  `/data/result.json` = `{raw_score, eval_time_in_seconds, metadata}`.
- **duel** (`kind: duel`) — N player sandboxes speaking the `gym_v1` HTTP API, plus a
  competition-owned **referee** image that holds the game logic, drives the match, and
  writes `/data/result.json` = `{raw_scores, winner, terminal_reason, steps, metadata}`.

See `docs/authoring.md` for the full authoring flow and `src/apex_sdk/gym_v1/` for the
protocol contracts (with docstrings).

## How a competition ships

1. Fork [apex-competition-hello-world](https://github.com/macrocosm-os/apex-competition-hello-world); implement your player and referee images.
2. `apex-dev preflight` and `apex-dev run` until it passes locally.
3. Build + sign your image(s) (keyless cosign) and push to your registry.
4. Open a PR to `apex-competitions-registry` adding `competitions/<id>/<version>.yaml`.
5. A Macrocosmos admin activates it by merging an `active/<env>.yaml` change.

> Activation is admin-gated. Designers self-serve their competition folder; going live is
> platform-controlled.
