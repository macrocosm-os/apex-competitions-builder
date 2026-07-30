# tabular_automl PLAYER image (the miner submission server).
#
# Builds FROM apex-player-base (ships the SDK). The submission is NOT baked in -- the
# platform (and apex-dev) writes the miner's submission.py to /app/submission.py at run
# time. sklearn/numpy are provided here so miners can build real pipelines without
# vendoring dependencies into their submission.
FROM apex-player-base

RUN pip install --no-cache-dir numpy scikit-learn

COPY player/launch.py /app/launch.py

# spec.entrypoints.evaluate.command is ["python", "/app/launch.py", "--port", "8000"].
CMD ["python", "/app/launch.py", "--port", "8000"]
