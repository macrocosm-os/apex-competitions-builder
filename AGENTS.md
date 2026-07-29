# AGENTS.md

Guidance for coding agents working with **apex-competitions-builder**.

## Read this first

This repo is a **toolkit you read from, not a codebase you change.** It ships the spec schema, the
`gym_v1` wire protocol, the `apex-dev` validation CLI, and the competition-design skill — and **no
competition code**.

Your competition belongs in **its own repo**. The overwhelmingly likely correct action here is to
read this repo and write somewhere else. In particular:

- **Do not add your competition to this repo** — not under `examples/`, not anywhere.
- **Do not edit the toolkit to make your competition work.** If the schema rejects your spec, the spec
  is wrong. If `gym_v1` doesn't do what you need, write it in your own image, not here.
- **Do not vendor by importing from an installed `apex_sdk`** in your competition images. Copy
  `src/apex_sdk/gym_v1/` into your repo — see the vendoring rule below.

Only change this repo if a human explicitly asked you to change **the toolkit itself**. If so, skip to
[Changing the toolkit](#changing-the-toolkit).

## Building a competition

Two steps, in order.

**1. Load the skill.** If your harness supports skills, invoke `apex-competition-builder`.
Otherwise read `SKILL.md` top to bottom before designing anything — it encodes doctrine you will
get wrong by intuition (the 1% takeover rule driving most design decisions, the
constrained-submission-format ladder, anti-Goodhart gates, evaluation sizing).

```
skills/apex-competition-builder/SKILL.md              # start here, read it fully
skills/apex-competition-builder/reference/evaluation-design.md
skills/apex-competition-builder/reference/security-checklist.md
skills/apex-competition-builder/HANDOFF.md            # the onboarding manifest to fill in
```

**2. Fork the worked example:** https://github.com/macrocosm-os/apex-competition-hello-world — a
complete, buildable competition laid out exactly like the repo you are about to write.

**3. Get it reviewed.** A finished competition isn't done — Macrocosmos has to review and activate
it, and the registry that does that is private, so there is nothing to PR. The only way in is to
**open a [Competition onboarding issue](https://github.com/macrocosm-os/apex-competitions-builder/issues/new?template=competition-onboarding.yml)
on this repo** (`macrocosm-os/apex-competitions-builder`). Have ready:

- a description of the competition and the success statement (what a winning solution should *be*,
  beyond the score),
- the filled `skills/apex-competition-builder/HANDOFF.md`,
- the competition repo URL and released tag,
- the player and referee image refs + digests (`sha256:…`, never a tag).

Do not open that issue on the user's behalf without their say-so — it's a public request to another
org, and the digests must come from a real signed release, not placeholders. Prepare the content and
let them file it.

Then `docs/authoring.md` for the full mechanics.

### The one rule agents most often break

**Vendor `gym_v1`; do not build `FROM apex-player-base` / `apex-referee-base`.** Copy
`src/apex_sdk/gym_v1/` into your competition repo, build `FROM python:3.12-slim`, and import the
**top-level** `gym_v1` (not `apex_sdk.gym_v1`). The base images in `images/` are **not published to
any registry**, so `FROM apex-player-base` only resolves on a machine that built it locally and
**fails in your release CI**.

`FROM apex-*-base` looks like the conventional, "correct" pattern, so agents routinely rewrite
working vendored Dockerfiles into broken ones — and "fix" the docs that say otherwise. Don't. The
docs are deliberate and consistent; building FROM the bases is the intended *future*, not usable
now.

---

## Changing the toolkit

**Only if a human explicitly asked you to modify this repo.** Otherwise see above.

### Repo map

| Path | What it is |
|------|-----------|
| `src/apex_sdk/schema/apex.competition.v1.json` | The spec schema. The platform validates against this exact file. |
| `src/apex_sdk/spec.py` | `load_spec`, `validate_dict`, `load_schema`, `check_resource_ceilings`, `LoadedSpec`, `SpecError`. |
| `src/apex_sdk/gym_v1/` | `player.py` (`Player`, `serve`), `referee.py` (`Referee`, `GameResult`, `RefereeContext`), `client.py` (`PlayerClient`, `PlayerError`). |
| `src/apex_sdk/dev/cli.py` | `apex-dev preflight` / `apex-dev run`. |
| `docs/authoring.md` | The authoring flow. Authoritative for mechanics. |
| `images/` | Base image Dockerfiles — unpublished, see the vendoring rule above. |
| `tests/fixtures/solo/` | A test fixture spec. **Not** an example to copy. |
| `.claude-plugin/`, `.codex-plugin/`, `.grok-plugin/`, `.agents/plugins/` | Installable plugin and marketplace manifests for the canonical skill. |

### Setup, test, lint

```bash
uv sync --extra dev              # or: pip install -e ".[dev]"
uv run pytest -q
uv run ruff check .
uv run black --check .
```

CI (`.github/workflows/ci.yml`) runs those three on Python 3.11 and 3.12. Run them before proposing
a change. Line length is **120** (`ruff` and `black` are both configured for it in
`pyproject.toml`) — do not reformat to 88.

### Constraints that aren't obvious from the source

**The schema is a published contract.** `apex.competition.v1.json` is what the platform validates
against, and `(id, version)` is immutable once a competition syncs. Never loosen or rename a field
to make a test pass. Additive, backward-compatible changes only; anything else needs a new schema
version and coordination with the platform.

**`gym_v1` must stay stdlib-only.** It exists to be copied into competition repos. A runtime
dependency there becomes a dependency every competition image has to install and pin. The toolkit's own
runtime surface (`pyyaml`, `jsonschema`) is deliberately tiny too.

**Resource ceilings are real.** `ENV_CEILINGS` in `spec.py` (stage 2 CPU / 2Gi, prod 4 CPU / 4Gi)
mirrors platform-side enforcement. Changing them here does not change what the platform accepts.

**`apex-dev run` does not execute anything yet.** It validates args, prints the resolved plan, and
exits 3. That is intentional, not a bug — a local two-sandbox harness is a follow-up. Its exit codes
are contract the tests assert: `2` bad args, `3` execution not implemented, `4` no Docker,
`5` timeout, `6` bad/missing `result.json`.

**Documentation is the product here.** External designers and their agents read this repo, so
`README.md`, `docs/authoring.md`, and `SKILL.md` carry as much weight as the code. They overlap by
design — if you change behaviour, update them together and keep them consistent.

**Don't add example competitions.** The worked example lives in its own repo so it demonstrates a
real competition's layout and release CI. Need something to validate against? Add it under
`tests/fixtures/` and label it a fixture.

### Conventions

- Python ≥ 3.11. Tests are plain `pytest` — no fixtures framework, no network, no Docker.
- Commit messages: imperative summary with a conventional-commit prefix (`docs:`, `fix:`, `feat:`),
  then a body explaining *why*. Match the existing `git log`.
- Branch and open a PR; `main` is protected.
