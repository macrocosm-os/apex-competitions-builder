# apex-competition-sdk

The public SDK for building [Apex](https://macrocosmos.ai) competitions (Bittensor Subnet 1).

An Apex competition is a **declarative, versioned, signed spec** (`apex.competition.v1`) plus the
container images that run it. The platform never imports your code — it validates your spec,
verifies and mirrors your signed images by digest, and executes them through generic runners.
Nothing you write runs inside a Macrocosmos process.

**This repo is the toolkit, not the competition.** Your competition lives in its own repo. Here
you get the schema, the wire protocol, a validation CLI, and the design skill.

---

## Start here

**If you are an agent (or using one), read [AGENTS.md](AGENTS.md) first.**

### → I want to build a competition

Two things, in order:

1. **Load the skill: [`skills/apex-competition-builder/SKILL.md`](skills/apex-competition-builder/SKILL.md).**
   Read it fully before designing anything. If your harness supports skills, invoke
   `apex-competition-builder`. It carries the doctrine you will otherwise get wrong: the 1%
   takeover rule that should drive most design decisions, the constrained-submission-format
   ladder (`onnx` > `torchscript` > `code`), anti-Goodhart gates, and evaluation sizing.

   | File | What it is |
   |------|-----------|
   | [`skills/apex-competition-builder/SKILL.md`](skills/apex-competition-builder/SKILL.md) | The guide. Start here. |
   | [`skills/apex-competition-builder/reference/evaluation-design.md`](skills/apex-competition-builder/reference/evaluation-design.md) | Statistical sizing, seeds, timeouts, resource budgeting, operating parameters. |
   | [`skills/apex-competition-builder/reference/security-checklist.md`](skills/apex-competition-builder/reference/security-checklist.md) | The full anti-exploit checklist with rationale. |
   | [`skills/apex-competition-builder/HANDOFF.md`](skills/apex-competition-builder/HANDOFF.md) | The onboarding manifest you fill in and submit. |

2. **Fork the worked example: [macrocosm-os/apex-competition-hello-world](https://github.com/macrocosm-os/apex-competition-hello-world).**
   A complete, buildable solo competition — spec, input schema, fixture, player image, referee
   image, baseline submission, and a signing release workflow — laid out exactly like the repo you
   are about to write. It is also the reference for the vendoring pattern below.

Then read [`docs/authoring.md`](docs/authoring.md) for the full mechanics.

### → I want to change the SDK itself

See [AGENTS.md](AGENTS.md) for the repo map, test/lint commands, and the constraints that aren't
obvious from the source.

---

## What's in here

| Path | What it is |
|------|-----------|
| [`skills/apex-competition-builder/`](skills/apex-competition-builder/) | **The design guide + agent skill.** Submission-format doctrine, evaluation sizing, anti-exploit checklist, onboarding manifest. |
| [`src/apex_sdk/schema/apex.competition.v1.json`](src/apex_sdk/schema/apex.competition.v1.json) | The spec JSON Schema. The platform validates against this exact file. |
| [`src/apex_sdk/gym_v1/`](src/apex_sdk/gym_v1/) | The wire protocol: `Player`/`serve`, `Referee`/`GameResult`/`RefereeContext`, `PlayerClient`. **This is the directory you vendor.** Stdlib-only. |
| [`src/apex_sdk/spec.py`](src/apex_sdk/spec.py) | `load_spec`, `validate_dict`, `load_schema`, `check_resource_ceilings`. |
| [`src/apex_sdk/dev/cli.py`](src/apex_sdk/dev/cli.py) | `apex-dev` — `preflight` and `run`. |
| [`docs/authoring.md`](docs/authoring.md) | The authoring flow, end to end. Authoritative for mechanics. |
| [`images/`](images/) | Base image Dockerfiles. **Unpublished — do not build FROM these**, see below. |
| `tests/fixtures/solo/` | A test fixture spec. Not an example to copy. |
| The example competition | Its own repo: [apex-competition-hello-world](https://github.com/macrocosm-os/apex-competition-hello-world). |

## How your images get the SDK: vendor it

**✅ Vendor.** Copy this repo's `src/apex_sdk/gym_v1/` into your competition repo, build
`FROM python:3.12-slim`, and import the **top-level** package:

```dockerfile
FROM python:3.12-slim
COPY player/gym_v1/ /app/gym_v1/
COPY player/launch.py /app/launch.py
```
```python
from gym_v1.player import Player, serve                     # not apex_sdk.gym_v1
from gym_v1.referee import Referee, GameResult, RefereeContext
from gym_v1.client import PlayerClient, PlayerError
```

**❌ Do not build `FROM apex-player-base` / `apex-referee-base`.** Those bases ship the SDK as
`apex_sdk.gym_v1`, but they are **not published to any registry** — the build only resolves on a
machine that ran `docker build` on the base locally, and **fails in your release CI**.
Build-FROM-base is the intended future once the bases are published; vendoring is what works today
and what every shipped competition does.

`gym_v1` is stdlib-only precisely so vendoring costs you no dependencies. See
[hello-world's `player/Dockerfile`](https://github.com/macrocosm-os/apex-competition-hello-world/blob/main/player/Dockerfile)
and its README's re-vendoring snippet.

## Install and validate

```bash
pip install -e .          # or: uv pip install -e .
apex-dev --help
```

```bash
git clone https://github.com/macrocosm-os/apex-competition-hello-world
cd apex-competition-hello-world

# Validate spec + input fixture against apex.competition.v1. No Docker.
apex-dev preflight --spec ./spec.yaml --input fixtures/input.json

# Resolve and print the execution plan (images, protocol, resources, timeouts).
apex-dev run --spec ./spec.yaml --input fixtures/input.json \
             --submission ./player/submission.py \
             --dockerfile ./player/Dockerfile
```

A spec that passes `preflight` is one the platform will accept at sync time — it checks the schema,
the resource ceilings (stage: 2 CPU / 2Gi; prod: 4 CPU / 4Gi), and your fixture against
`input_schema`.

`apex-dev run` prints the plan and **exits 3**: referee-driven local execution (both sandboxes on a
shared network) is not implemented yet. Until it is, run the pair by hand — the
[hello-world README](https://github.com/macrocosm-os/apex-competition-hello-world#validate-and-run-locally)
gives the exact `docker run` commands. Exit codes: `2` bad args, `3` execution not implemented,
`4` no Docker, `5` timeout, `6` bad or missing `result.json`.

## The architecture

```
Miner ──apex submit──▶ Apex orchestrator ──▶ queue ──▶ Apex worker
                                                          │  spawns one per-job network
                     ┌────────────────────────────────────┤
                     ▼                                    ▼
          PLAYER sandbox(es)  ◀────HTTP (gym_v1)────  REFEREE sandbox
          your player image;                          your referee image;
          submission written to                       game rules, datasets,
          submission.target_path,                     ground truth, scoring;
          served as /health /reset /act               writes /data/result.json
```

The submission and your scoring logic **never share a sandbox** — a submission can't read or patch
the scorer, and the scorer's data never enters the miner-reachable container. You always author
**both** images.

- **solo** (`kind: solo`) — a 1-player duel. Your referee scores each submission independently
  against the round input; leadership goes to whoever beats the standing best by ≥1%. The default:
  7 of 9 production competitions. Can request several isolated sandboxes of the *same* submission
  via `solo.player_sandboxes`.
- **duel** (`kind: duel`) — N player sandboxes playing head-to-head; the round winner comes from a
  bracket, not the 1% rule. Only when quality is inherently relative.

Result contract: the referee writes `/data/result.json` =
`{raw_scores, winner, terminal_reason, steps, metadata}`. A referee crash or a missing/invalid
`result.json` is attributed to the **referee**, not the submission — never write a zeroed result to
paper over a bug.

## How a competition ships

Your repo and images can each be **public or private** — the platform verifies and mirrors images
**by digest** and can pull private packages, so visibility is a transparency choice, not a
technical gate.

1. Design with the skill; implement your player and referee images (vendored).
2. `apex-dev preflight` passes; exercise the full loop locally, then on stage.
3. Build + keyless-cosign-sign your images, push by digest, tag a release.
4. Open a [Competition onboarding issue](https://github.com/macrocosm-os/apex-competitions-sdk/issues/new?template=competition-onboarding.yml)
   with your repo URL, released tag, image refs + digests, and your filled `HANDOFF.md`.
5. A Macrocosmos maintainer reviews, copies your `spec.yaml` verbatim into the private
   `apex-competitions-registry`, and activates it on **stage first**, then prod.

The registry is always private — it's the control plane that decides which digests are trusted — so
you don't PR it directly. Updating a live competition is the same loop: bump `version` (the
`(id, version)` pair is immutable once synced), re-sign, request activation.

> Activation is admin-gated. Trust comes from signed digests plus admin-merged pointers, both
> reviewable in git — not from repo visibility.

## More

- Full docs index (agent-friendly, one fetch): https://docs.macrocosmos.ai/llms.txt
- Platform overview: https://docs.macrocosmos.ai/subnets/subnet-1-apex
- Incentive mechanism: https://docs.macrocosmos.ai/subnets/subnet-1-apex/incentive-mechanism
- Miner-side view: https://github.com/macrocosm-os/apex
