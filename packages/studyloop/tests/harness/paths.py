"""Single isolated IPC-path contract for executable test harnesses."""

from __future__ import annotations

import os
from pathlib import Path

SESSION_DIR = Path(os.environ["STUDYLOOP_SESSION_DIR"]).resolve()
STATE_FILE = SESSION_DIR / "session-state.json"
TOPICS_FILE = SESSION_DIR / "session-topics.md"
PARKING_FILE = SESSION_DIR / "session-parking.md"
ONELINE_FILE = SESSION_DIR / "session-oneline.txt"
SESSIONS_DIR = SESSION_DIR / "sessions"
