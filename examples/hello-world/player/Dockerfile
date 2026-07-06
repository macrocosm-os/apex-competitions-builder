# hello_world player image.
#
# Build context = this directory (examples/hello-world/player):
#     docker build -t apex-competition-hello-world .
# or let apex-dev build it for you:
#     apex-dev run --spec ../spec.yaml --input ../fixtures/input.json \
#                  --submission ./submission.py --dockerfile ./Dockerfile
#
# hello_world's evaluate.py is pure stdlib, so this doesn't even need the SDK. A real
# competition would base FROM apex-player-base to get `from apex_sdk.gym_v1 import ...`.
FROM python:3.12-slim

# Match the platform sandbox user (run_as_user=1000).
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app /data \
    && chown -R 1000:1000 /app /data

WORKDIR /app

# Bake the eval entrypoint in. The SUBMISSION is NOT baked in: the platform (and apex-dev)
# writes the miner's submission to /app/submission.py at run time.
COPY evaluate.py /app/evaluate.py

USER 1000

# spec.entrypoints.evaluate.command is ["python", "/app/evaluate.py"]; set it as the
# default too so the image is runnable on its own.
CMD ["python", "/app/evaluate.py"]
