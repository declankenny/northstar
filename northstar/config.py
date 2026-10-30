"""Where things live. One place, so the app and the backup tool always agree."""

import os
from pathlib import Path

DEFAULT_DB_PATH = "data/northstar.db"


def database_path() -> Path:
    """The SQLite file: NORTHSTAR_DB if set, otherwise data/northstar.db."""
    return Path(os.environ.get("NORTHSTAR_DB", DEFAULT_DB_PATH))
