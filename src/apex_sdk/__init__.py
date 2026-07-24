"""apex-competition-sdk: contracts and tooling for building Apex competitions.

Public surface:
    apex_sdk.spec       - load & validate an apex.competition.v1 spec
    apex_sdk.gym_v1     - the duel wire protocol (player server, referee harness, client)
"""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("apex-competition-sdk")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0+unknown"

del _pkg_version, PackageNotFoundError
