"""The version of Northstar. It is written once, as `version` in pyproject.toml, and read from the installed package."""

from importlib.metadata import version

VERSION = version("northstar")
