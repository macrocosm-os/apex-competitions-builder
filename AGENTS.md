# AGENTS.md

Guidance for coding agents working in **apex-competitions-sdk**.

## What this repo is

The public SDK for building [Apex](https://macrocosmos.ai) competitions (Bittensor Subnet 1).
It ships four things and **no competition code**:

1. `apex.competition.v1` — the spec JSON Schema the platform validates against.
2. `gym_v1` — the player/referee wire protocol.
3. `apex-dev` — a local validation CLI.
4. `skills/apex-competition-builder/` — the agent skill for designing a competition.

Competitions live in **their own repos**, not here. If a task is "build a competition", you are
almost certainly meant to be authoring a *different* repo and only *reading* this one.

## First: are you building a competition, or changing the SDK?

**Building a competition** → do not add it to this repo. Load the skill and follow it:

```
skills/apex-competition-builder/SKILL.md              # start here, read it fully
skills/apex-competition-builder/reference/evaluation-design.md
skills/apex-competition-builder/reference/security-checklist.md
skills/apex-competition-builder/HANDOFF.md            # the onboarding manifest to fill in
```

If your harness supports skills, invoke `apex-competition-builder`; otherwise just read
`SKILL.md` top to bottom before designing anything. It encodes non-obvious doctrine (the 1%
takeover rule driving every design decision, the constrained-submission-format ladder,
anti-Goodhart gates, evaluation sizing) that you will get wrong by intuition.

Then fork the worked example: **https://github.com/macrocosm-os/apex-competition-hello-world**

**Changing the SDK itself** → continue below.

## Repo map

| Path | What it is |
|------|-----------|
| `src/apex_sdk/schema/apex.competition.v1.json` | The spec schema. The platform validates against this exact file. |
| `src/apex_sdk/spec.py` | `load_spec`, `validate_dict`, `load_schema`, `check_resource_ceilings`, `LoadedSpec`, `SpecError`. |
| `src/apex_sdk/gym_v1/` | `player.py` (`Player`, `serve`), `referee.py` (`Referee`, `GameResult`, `RefereeContext`), `client.py` (`PlayerClient`, `PlayerError`). |
| `src/apex_sdk/dev/cli.py` | `apex-dev preflight` / `apex-dev run`. |
| `docs/authoring.md` | The authoring flow. Authoritative for mechanics. |
| `images/` | Base image Dockerfiles — **unpublished**, see below. |
| `tests/fixtures/solo/` | A test fixture spec. **Not** an example to copy. |

## Setup, test, lint

```bash
uv sync --extra dev              # or: pip install -e ".[dev]"
uv run pytest -q
uv run ruff check .
uv run black --check .
```

CI (`.github/workflows/ci.yml`) runs exactly those three on Python 3.11 and 3.12. Run all three
before proposing a change. Line length is **120** (`ruff` and `black` are both configured for it
in `pyproject.toml`) — do not reformat to 88.

## Rules specific to this repo

**Vendoring is the image pattern — do not "fix" docs back to `FROM apex-*-base`.** Competition
images must vendor `src/apex_sdk/gym_v1/` into their own repo and build `FROM python:3.12-slim`,
importing the top-level `gym_v1` (not `apex_sdk.gym_v1`). The base images in `images/` are **not
published to any registry**, so `FROM apex-player-base` only resolves on a machine that built it
locally and fails in a competition's release CI. Building FROM the bases is the intended future;
it is not usable now. Several docs say this deliberately and consistently — keep them aligned.

**The schema is a published contract.** `apex.competition.v1.json` is what the platform validates
against, and `(id, version)` is immutable once a competition syncs. Never loosen or rename a field
to make a test pass. Additive, backward-compatible changes only; anything else needs a new schema
version and coordination with the platform.

**Resource ceilings are real.** `ENV_CEILINGS` in `spec.py` (stage 2 CPU / 2Gi, prod 4 CPU / 4Gi)
mirrors platform-side enforcement. Changing them here does not change what the platform accepts.

**`apex-dev run` does not execute anything yet.** It validates args, prints the resolved plan, and
exits 3. That is intentional, not a bug — a local two-sandbox harness is a follow-up. Its exit
codes are part of the contract the tests assert: `2` bad args, `3` execution not implemented,
`4` no Docker, `5` timeout, `6` bad/missing `result.json`.

**Documentation is the product here.** This repo is read by external competition designers and by
agents acting for them, so `docs/authoring.md`, `SKILL.md`, and `README.md` carry as much weight as
the code. If you change behaviour, update them in the same change — and keep them consistent with
each other, since they overlap heavily by design.

**Don't add example competitions to this repo.** The worked example intentionally lives in its own
repo so it demonstrates a real competition's layout and release CI. Add fixtures under
`tests/fixtures/` if you need something to validate against, and label them as fixtures.

## Conventions

- Python ≥ 3.11. The runtime dependency surface is deliberately tiny (`pyyaml`, `jsonschema`);
  `gym_v1` itself is stdlib-only so it can be vendored without dragging in dependencies. **Do not
  add a runtime dependency to `gym_v1`.**
- Tests are plain `pytest`, no fixtures framework, no network, no Docker.
- Commit messages: imperative summary with a conventional-commit prefix (`docs:`, `fix:`, `feat:`),
  then a body explaining *why*. Match the existing `git log`.
- Branch and open a PR; `main` is protected and activation-adjacent changes get reviewed.
