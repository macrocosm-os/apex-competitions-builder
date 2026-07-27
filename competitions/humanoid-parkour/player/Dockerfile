# humanoid_parkour PLAYER image (the miner submission server).
#
# Builds FROM apex-player-base (ships the SDK). The submission is NOT baked in —
# the platform writes the miner's ONNX policy to /app/submission.onnx at run time.
# This image is public: it contains no course generator, seeds, or scoring logic
# (those live in the referee image).
FROM apex-player-base

USER root
RUN pip install --no-cache-dir numpy==2.3.4 onnxruntime==1.28.0
USER 1000

COPY player/launch.py /app/launch.py

# spec.entrypoints.evaluate.command is ["python", "/app/launch.py", "--port", "8000"].
CMD ["python", "/app/launch.py", "--port", "8000"]
