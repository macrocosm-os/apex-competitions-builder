# algo_speedrun PLAYER image (the miner submission carrier).
#
# Builds FROM apex-player-base. The submission is NOT baked in -- the platform writes it
# to /app/submission.py at run time. This image never imports or executes the miner's
# code: it only reads and returns the file's bytes over gym_v1's /act, so it needs no
# torch, no nanochat, no extra pip dependencies at all -- the stdlib is enough.
#
# BUILD CONTEXT = the competition directory (competitions/algo-speedrun):
#     docker build -f player/Dockerfile -t algo-speedrun-player .
FROM apex-player-base

COPY player/launch.py /app/launch.py

CMD ["python", "/app/launch.py", "--port", "8000"]
