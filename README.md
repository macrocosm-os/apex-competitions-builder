# apex-competitions-builder

The public toolkit for building [Apex](https://macrocosmos.ai) competitions (Bittensor Subnet 1).

A competition is a **declarative, versioned, signed spec** (`apex.competition.v1`) plus the
container images that run it. The platform never imports your code — it validates your spec,
verifies and mirrors your signed images by digest, and runs them through generic runners.

**This repo is the toolkit. Your competition lives in its own repo** — you read from here and write
somewhere else.

## Start here

1. **Give your agent access to
   [`apex-competition-builder`](skills/apex-competition-builder/).** Invoke the installed skill by
   name, or point a compatible agent at this repository.
2. **Ask the agent to start the competition:**

   > Use apex-competition-builder to create a new Apex competition. Start by helping me define its
   > success statement, then build it in a separate repository.

3. **Let the agent drive the workflow.** It creates the separate repository, starts from the
   organization-owned worked example, vendors `gym_v1`, validates the competition, and
   prepares `HANDOFF.md`.

The implementation details stay inside the skill:

| What the agent works through | Covers |
|------|-----------|
| [`SKILL.md`](skills/apex-competition-builder/SKILL.md) | The shape of the competition: submission format, solo vs duel, the metric and its anti-gaming gates. |
| [`reference/evaluation-design.md`](skills/apex-competition-builder/reference/evaluation-design.md) | How many tasks per evaluation, seeds, timeouts, resources, round length and reveal delay. |
| [`reference/security-checklist.md`](skills/apex-competition-builder/reference/security-checklist.md) | Whether miners can game it. Walked end to end before you ship. |
| [`HANDOFF.md`](skills/apex-competition-builder/HANDOFF.md) | The onboarding manifest, filled in and submitted at the end. |

Agents: also read [AGENTS.md](AGENTS.md).

## Install the competition-builder skill

Install the canonical skill for Codex, OpenCode, Cursor, Gemini CLI, or another Agent Skills host:

```bash
npx skills add macrocosm-os/apex-competitions-builder \
  --skill apex-competition-builder -g
```

Target one or more hosts explicitly when needed:

```bash
npx skills add macrocosm-os/apex-competitions-builder -g -a codex
npx skills add macrocosm-os/apex-competitions-builder \
  --skill apex-competition-builder -g -a opencode -y
npx skills add macrocosm-os/apex-competitions-builder -g -a codex -a gemini-cli
```

OpenCode consumes the canonical Agent Skill directly; it does not need a separate plugin manifest.

Claude Code, Codex, and Grok can also install the repository as a native marketplace plugin:

```bash
claude plugin marketplace add macrocosm-os/apex-competitions-builder
claude plugin install apex-competition-builder@apex-competitions-builder

codex plugin marketplace add macrocosm-os/apex-competitions-builder
codex plugin add apex-competition-builder@apex-competitions-builder

grok plugin marketplace add macrocosm-os/apex-competitions-builder
grok plugin install apex-competition-builder --trust
```

Update Agent Skills installs with `npx skills update apex-competition-builder -g`. Claude Code
refreshes this marketplace with
`claude plugin marketplace update apex-competitions-builder`. Codex refreshes it with
`codex plugin marketplace upgrade apex-competitions-builder`; rerun `codex plugin add` to install
the newly published version. Update Grok with `grok plugin update apex-competition-builder`.

Use one installation method per host to avoid loading the same skill twice. These commands make
this repository an installable community marketplace. Listing it in a vendor-operated public
catalog is a separate post-release submission: OpenAI reviews public plugins for its universal
directory, while xAI accepts pinned-source pull requests to `xai-org/plugin-marketplace`.

## What's in here

| Path | What it is |
|------|-----------|
| [`skills/apex-competition-builder/`](skills/apex-competition-builder/) | The design guide + agent skill. |
| [`.claude-plugin/`](.claude-plugin/) | Claude Code plugin and marketplace manifests. |
| [`.codex-plugin/plugin.json`](.codex-plugin/plugin.json) | Codex plugin manifest for the canonical skill. |
| [`.grok-plugin/`](.grok-plugin/) | Grok plugin and marketplace manifests. |
| [`src/apex_sdk/gym_v1/`](src/apex_sdk/gym_v1/) | The wire protocol: `Player`/`serve`, `Referee`/`GameResult`/`RefereeContext`, `PlayerClient`. **The directory you vendor.** Stdlib-only. |
| [`src/apex_sdk/schema/apex.competition.v1.json`](src/apex_sdk/schema/apex.competition.v1.json) | The spec schema. The platform validates against this exact file. |
| [`src/apex_sdk/spec.py`](src/apex_sdk/spec.py) | `load_spec`, `validate_dict`, `load_schema`, `check_resource_ceilings`. |
| [`src/apex_sdk/dev/cli.py`](src/apex_sdk/dev/cli.py) | `apex-dev` — `preflight` and `run`. |
| [`docs/authoring.md`](docs/authoring.md) | The authoring flow. Authoritative for mechanics. |
| [`images/`](images/) | Base image Dockerfiles. **Unpublished — don't build FROM these**, see below. |

## Vendor `gym_v1` into your images

This is the one thing people get wrong. Copy `src/apex_sdk/gym_v1/` into your competition repo,
build `FROM python:3.12-slim`, and import the **top-level** package:

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

**Do not build `FROM apex-player-base` / `apex-referee-base`.** Those bases aren't published to any
registry, so they only resolve on a machine that built them locally and **fail in your release CI**.
Building FROM them is the intended future; vendoring is what works today, and `gym_v1` is
stdlib-only so it costs you no dependencies.

## Validate locally

```bash
pip install -e .          # or: uv pip install -e .

apex-dev preflight --spec ./spec.yaml --input fixtures/input.json \
                   --submission ./fixtures/reference_solution.json
apex-dev run --spec ./spec.yaml --input fixtures/input.json \
             --submission ./player/submission.py --dockerfile ./player/Dockerfile
```

`preflight` checks the schema, the resource ceilings (stage 2 CPU / 2Gi, prod 4 CPU / 4Gi), and
your fixture against `input_schema`. A spec that passes is one the platform will accept at sync
time. No Docker needed. Optional `--submission` also checks a sample artifact against your declared
`submission.artifact_type` — `json`, `csv`, `onnx`, `wasm`, `torchscript`, `code`, or `archive` (a
tarball/zip of several files, extracted into `target_path`); see
[`docs/authoring.md`](docs/authoring.md#submission-artifact-types).

`run` prints the resolved execution plan and **exits 3** — referee-driven local execution isn't
implemented yet. Run the two sandboxes by hand meanwhile; the
[hello-world README](https://github.com/macrocosm-os/apex-competition-hello-world#validate-and-run-locally)
has the exact commands. Other exit codes: `2` bad args, `4` no Docker, `5` timeout, `6` bad or
missing `result.json`.

## The shape of a competition

You always author **two** images. The miner's submission runs in a **player** sandbox; your
competition-owned **referee** sandbox holds the rules, datasets, ground truth, and scoring, drives
the player over a per-job network, and writes `/data/result.json`. They never share a sandbox, so a
submission can't read or patch the scorer.

- **solo** (`kind: solo`) — a 1-player duel. Each submission is scored independently against the
  round input; a new one takes the lead by beating the standing best by ≥1%. The default (7 of 9
  production competitions).
- **duel** (`kind: duel`) — N players head-to-head; the winner comes from a bracket, not the 1%
  rule. Only when quality is inherently relative.

Diagram and full contracts: [`SKILL.md`](skills/apex-competition-builder/SKILL.md) and
[`docs/authoring.md`](docs/authoring.md).

## Shipping

Your repo and images can each be public or private — the platform verifies and mirrors images **by
digest** and can pull private packages, so visibility is a transparency choice, not a technical one.

1. Design with the skill; implement your player and referee images (vendored).
2. `apex-dev preflight` passes; exercise the loop locally, then on stage.
3. Keyless-cosign-sign your images, push by digest, tag a release.
4. Open a [Competition onboarding issue](https://github.com/macrocosm-os/apex-competitions-builder/issues/new?template=competition-onboarding.yml)
   with your repo URL, released tag, image refs + digests, and your filled `HANDOFF.md`.
5. A maintainer reviews, copies your `spec.yaml` verbatim into the private
   `apex-competitions-registry`, and activates it on **stage first**, then prod.

The registry is private — it's the control plane deciding which digests are trusted — so you don't
PR it directly. Updating a live competition is the same loop: bump `version` (`(id, version)` is
immutable once synced), re-sign, request activation.

## More

- Docs index, agent-friendly single fetch: https://docs.macrocosmos.ai/llms.txt
- Platform overview: https://docs.macrocosmos.ai/subnets/subnet-1-apex
- Incentive mechanism: https://docs.macrocosmos.ai/subnets/subnet-1-apex/incentive-mechanism
- Miner-side view: https://github.com/macrocosm-os/apex
