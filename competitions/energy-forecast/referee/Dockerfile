# energy_forecast REFEREE image (the scorer sandbox).
#
# Builds FROM apex-referee-base (ships the SDK). Owns the pinned historical
# demand data, instance sampling, and scoring gates. Runs by convention at
# /app/referee.py; the platform injects MATCH_ID, SEED, CONFIG_JSON,
# PLAYER_URLS, NUM_PLAYERS and reads /data/result.json.
#
# data/*_history.csv is refreshed daily by resolver/fetch_ground_truth.py
# (run outside any sandbox) and baked in at the next image build/release --
# this image never reaches the internet itself.
#
# BUILD CONTEXT = the competition directory (competitions/energy-forecast):
#     docker build -f referee/Dockerfile -t energy-forecast-referee .
FROM apex-referee-base

USER root
RUN pip install --no-cache-dir numpy==2.3.4
USER 1000

COPY env/ /app/env/
COPY data/ /app/data/
COPY referee/referee.py /app/referee.py
