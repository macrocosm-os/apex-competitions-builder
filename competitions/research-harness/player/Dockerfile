# research_harness PLAYER image (the miner submission server).
#
# Builds FROM apex-player-base (ships the SDK). The submission is NOT baked in — the
# platform writes the miner's harness to /app/submission.py at run time.
#
# This image is public and deliberately near-empty: no corpus, no world generator, no
# BM25 index, no scoring rules, no base-model credentials, no seed. A harness's entire
# capability surface is the action dicts it returns to the referee, so there is nothing
# here to read or patch. No extra pip dependencies: a harness gets the stdlib.
#
# BUILD CONTEXT = the competition directory (competitions/research-harness):
#     docker build -f player/Dockerfile -t research-harness-player .
FROM apex-player-base

COPY player/launch.py /app/launch.py

# spec.entrypoints.evaluate.command is ["python", "/app/launch.py", "--port", "8000"].
CMD ["python", "/app/launch.py", "--port", "8000"]
