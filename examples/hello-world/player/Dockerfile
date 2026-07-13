# hello_world PLAYER image (the miner submission server).
#
# Builds FROM apex-player-base (ships the SDK). The submission is NOT baked in — the platform
# (and apex-dev) writes the miner's submission to /app/submission.py at run time.
FROM apex-player-base

COPY player/launch.py /app/launch.py

# spec.entrypoints.evaluate.command is ["python", "/app/launch.py", "--port", "8000"].
CMD ["python", "/app/launch.py", "--port", "8000"]
