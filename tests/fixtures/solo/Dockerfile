# A stand-in player Dockerfile, so CLI tests have a real file to pass to --dockerfile.
# `apex-dev run` exits 3 before building, so this is never actually built by the suite.
# For a real, buildable player image (vendored SDK, FROM python:3.12-slim), see
# https://github.com/macrocosm-os/apex-competition-hello-world.
FROM python:3.12-slim
COPY submission.py /app/submission.py
CMD ["python", "/app/launch.py", "--port", "8000"]
