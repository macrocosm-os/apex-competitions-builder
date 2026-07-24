# hello_world REFEREE image (the scorer sandbox).
#
# Builds FROM apex-referee-base (ships the SDK), so referee.py imports `apex_sdk.gym_v1`. NOTE:
# apex-referee-base is not published to a registry yet — this only builds after you `docker build`
# the base locally (see docs/authoring.md setup). Shipped competitions instead VENDOR the SDK:
# copy gym_v1/ into the repo, use `FROM python:3.12-slim`, and import the top-level `gym_v1`. Both
# patterns are documented in docs/authoring.md § "How your image gets the SDK".
# Runs by the platform convention /app/referee.py.
FROM apex-referee-base

COPY referee/referee.py /app/referee.py

CMD ["python", "/app/referee.py"]
