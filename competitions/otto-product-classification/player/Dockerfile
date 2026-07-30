# otto_product_classification PLAYER image (the miner submission server).
#
# Builds FROM apex-player-base (ships the SDK). The submission is NOT baked in — the platform
# writes the miner's CSV to /app/submission.csv at run time.
#
# NO pip installs: parsing and serving a CSV is stdlib work (csv, math, http.server).
#
# This image contains NO dataset, NO labels, and NO scoring authority. env/ is code plus the
# split salt and the sha256 of an object the public spec already publishes — the labels
# themselves are mounted into the REFEREE only. Safe to publish, by construction.
#
# BUILD CONTEXT = the competition directory (competitions/otto-product-classification):
#     docker build -f player/Dockerfile -t otto-product-classification-player .
FROM apex-player-base

COPY env/ /app/env/
COPY player/launch.py /app/launch.py

# spec.entrypoints.evaluate.command is ["python", "/app/launch.py", "--port", "8000"].
CMD ["python", "/app/launch.py", "--port", "8000"]
