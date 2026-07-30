# research_harness REFEREE image (the scorer sandbox).
#
# Builds FROM apex-referee-base (ships the SDK). Owns the world generator, the BM25
# index, the context-buffer tool surface, the ONLY connection to the frozen base model,
# the token meter, and all scoring. Runs by convention at /app/referee.py; the platform
# injects MATCH_ID, SEED, CONFIG_JSON, PLAYER_URLS, NUM_PLAYERS plus the base_model
# variables (MODEL_BASE_URL, MODEL_NAME, MODEL_TEMPERATURE, MODEL_MAX_OUTPUT_TOKENS,
# MODEL_TOKEN_BUDGET) and reads /data/result.json.
#
# No pip dependencies: retrieval is stdlib BM25 and the model client is stdlib urllib,
# so there is no search or vendor SDK in the image.
#
# BUILD CONTEXT = the competition directory (competitions/research-harness):
#     docker build -f referee/Dockerfile -t research-harness-referee .
FROM apex-referee-base

COPY env/ /app/env/
COPY referee/referee.py /app/referee.py
