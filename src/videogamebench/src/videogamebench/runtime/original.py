"""Run the same pinned upstream entry points directly, outside Harbor."""

import os
from pathlib import Path

from session import Session

session = Session(Path("/opt/game"), Path("/state"))
session.started = True
session.controller = "vgagent"
session.run(os.environ.get(session.settings["api_key_env"]), None)
if session.error:
    raise SystemExit(session.error)
