# humanoid_parkour REFEREE image (the scorer sandbox).
#
# Builds FROM apex-referee-base (ships the SDK). Owns MuJoCo, the course
# generator, and all scoring/termination gates. Runs by convention at
# /app/referee.py; the platform injects MATCH_ID, SEED, CONFIG_JSON,
# PLAYER_URLS, NUM_PLAYERS and reads /data/result.json.
#
# BUILD CONTEXT = the competition directory (competitions/humanoid-parkour):
#     docker build -f referee/Dockerfile -t humanoid-parkour-referee .
FROM apex-referee-base

USER root
RUN pip install --no-cache-dir numpy==2.3.4 mujoco==3.10.0
USER 1000

COPY env/ /app/env/
COPY referee/referee.py /app/referee.py
