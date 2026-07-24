# hello_world PLAYER image (the miner submission server).
#
# Builds FROM apex-player-base (ships the SDK), so launch.py imports `apex_sdk.gym_v1`. NOTE:
# apex-player-base is not published to a registry yet, so this only builds after you `docker build`
# the base locally (see docs/authoring.md setup). Shipped competitions instead VENDOR the SDK:
# copy gym_v1/ into the repo, use `FROM python:3.12-slim`, and import the top-level `gym_v1`. Both
# patterns are documented in docs/authoring.md § "How your image gets the SDK".
# The submission is NOT baked in — the platform (and apex-dev) writes the miner's submission to
# /app/submission.py at run time.
FROM apex-player-base

COPY player/launch.py /app/launch.py

# spec.entrypoints.evaluate.command is ["python", "/app/launch.py", "--port", "8000"].
CMD ["python", "/app/launch.py", "--port", "8000"]
