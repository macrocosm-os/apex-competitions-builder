# apex-referee-base
#
# Base image that competition REFEREE images (solo and duel) build FROM. It ships a
# Python 3.12 runtime with the apex-competition-sdk installed, so a referee image can do:
#
#     from apex_sdk.gym_v1 import Referee, GameResult, PlayerClient
#
# BUILD CONTEXT = REPO ROOT. This Dockerfile COPYs pyproject.toml + src/ (and the
# README the build backend needs) from the repo root, so build it from there:
#
#     docker build -f images/referee-base/Dockerfile -t apex-referee-base .
#
# It intentionally sets NO hard ENTRYPOINT: the competition referee image that builds
# FROM this base sets its own CMD/ENTRYPOINT.

FROM python:3.12-slim

# Non-root user matching how the platform runs sandboxes (run_as_user=1000).
RUN useradd --create-home --uid 1000 app

# App + data dirs, owned by the sandbox user. /data is where the referee writes
# result.json (and the optional trace.jsonl).
RUN mkdir -p /app /data && chown -R 1000:1000 /app /data

WORKDIR /app

# Install the toolkit. It is stdlib-only aside from pyyaml/jsonschema, so this stays
# small. Copy only what the build backend needs to produce the wheel.
COPY pyproject.toml README.md /src/
COPY src/ /src/src/
RUN pip install --no-cache-dir /src && rm -rf /src

USER 1000
