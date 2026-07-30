"""apex-competition-sdk: contracts and tooling for building Apex competitions.

Public surface:
    apex_sdk.spec       - load & validate an apex.competition.v1 spec
    apex_sdk.gym_v1     - the duel wire protocol (player server, referee harness, client)
"""

# Derived from package metadata so it cannot drift from pyproject.toml (it had: 0.1.0 here
# vs 0.3.0 there). pyproject is the single source of truth.
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("apex-competition-sdk")
except PackageNotFoundError:  # source checkout without an install
    __version__ = "0.0.0.dev0"
