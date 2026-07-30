# otto_product_classification REFEREE image (the scorer sandbox).
#
# Builds FROM apex-referee-base (ships the SDK). Owns the metric and the validity gates.
# Runs by convention at /app/referee.py; the platform injects MATCH_ID, SEED, CONFIG_JSON,
# PLAYER_URLS, NUM_PLAYERS and reads /data/result.json.
#
# NO pip installs: env/metric.py is math.log + math.fsum, so there is no numpy (or any other)
# version that could ever silently drift a score. The image is base + two paths.
#
# NO DATA IS BAKED IN. The ground truth — and the test id list, which is a projection of it —
# arrive at run time as spec.private_data[0]: an R2 object the platform fetches,
# sha256-verifies, and bind-mounts READ-ONLY at /private/test_labels.csv. env/labels.py
# re-verifies the digest and raises if the mount is absent. This image never reaches the
# internet, and no `mkdir /private` is needed (the mount point is created for us).
#
# data/test_features.csv is needed by NOBODY in the eval path: the player serves a precomputed
# CSV and the referee needs only ids + labels. It exists solely so miners can predict, and is
# therefore in neither image.
#
# BUILD CONTEXT = the competition directory (competitions/otto-product-classification):
#     docker build -f referee/Dockerfile -t otto-product-classification-referee .
FROM apex-referee-base

COPY env/ /app/env/
COPY referee/referee.py /app/referee.py

CMD ["python", "/app/referee.py"]
