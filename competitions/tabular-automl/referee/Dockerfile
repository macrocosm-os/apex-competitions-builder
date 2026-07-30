# tabular_automl REFEREE image (the scorer sandbox).
#
# Builds FROM apex-referee-base (ships the SDK). Runs by the platform convention
# /app/referee.py. Holds the dataset generation + reference models + loss (env/tasks.py) --
# ground truth (test_y) never leaves this image.
FROM apex-referee-base

RUN pip install --no-cache-dir numpy scikit-learn

COPY env /app/env
COPY referee/referee.py /app/referee.py

CMD ["python", "/app/referee.py"]
