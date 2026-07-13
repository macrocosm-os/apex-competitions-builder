# hello_world REFEREE image (the scorer sandbox).
#
# Builds FROM apex-referee-base (ships the SDK). Runs by the platform convention /app/referee.py.
FROM apex-referee-base

COPY referee/referee.py /app/referee.py

CMD ["python", "/app/referee.py"]
