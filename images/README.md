# Base images

Two thin base images that competition images build **FROM**. Both ship a Python 3.12
runtime with the `apex-competition-sdk` installed and a non-root `app` user (uid 1000,
matching how the platform runs sandboxes with `run_as_user=1000`).

| Image | Base FROM for | Gives you |
|-------|---------------|-----------|
| `apex-player-base` (`images/player-base/Dockerfile`) | a competition **player** image (solo eval, or a duel player) | `from apex_sdk.gym_v1 import Player, serve` |
| `apex-referee-base` (`images/referee-base/Dockerfile`) | a duel competition's **referee** image | `from apex_sdk.gym_v1 import Referee, GameResult, PlayerClient` |

Both create `/app` (the `WORKDIR`) and `/data`, owned by uid 1000. The platform mounts
the round input at `/data/input.json` and reads the result from `/data/result.json`.

## Build context = repo root

The SDK is not on PyPI yet, so these Dockerfiles install it by copying the SDK source
(`pyproject.toml`, `README.md`, `src/`) into the image and running `pip install`. That
means **the build context must be the repo root**, and you pass the Dockerfile with `-f`:

```bash
# from the repo root
docker build -f images/player-base/Dockerfile  -t apex-player-base  .
docker build -f images/referee-base/Dockerfile -t apex-referee-base .
```

Neither image sets a hard `ENTRYPOINT` — the competition image that builds FROM it sets
its own command (and for the player, the platform overrides it with
`spec.entrypoints.evaluate.command` at run time).

## Using them in a competition image

```dockerfile
FROM apex-player-base
COPY evaluate.py /app/evaluate.py
# The platform writes the miner's submission to spec.submission.target_path
# (e.g. /app/submission.py) and runs spec.entrypoints.evaluate.command.
```

## Extra read-only mounts in the referee

A referee container may receive additional read-only bind mounts declared in the spec's
`private_data` block (e.g. `/private/test_labels.csv`) — private ground truth the platform
fetches, sha256-verifies, and mounts per job. The base image needs no `mkdir` for these; the
mount point is created for you. Referee code must treat those paths as read-only, must not
assume they exist without checking, and must never attempt to fetch them itself (sandboxes have
no egress). Player containers never receive these mounts.
