"""Doctor checks for the exporter the hooks actually call.

Two checks born of one incident (Stage 4 record, 2026-09-12): the learner's
database reached a schema newer than the pinned ``session-export`` supported,
the pinned exporter refused every run, the hooks discarded the refusal, and
nothing was captured for a day.

* ``exporter_schema`` -- the schema version the *pinned* exporter supports
  against the database's ``user_version``. Older than the database: every
  export fails. Newer: its first run will migrate the database, said out loud.
* ``export_freshness`` -- how long ago the newest message was captured. A hook
  that never runs, or always fails, leaves no other trace.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from studyloop import installers
from studyloop.doctor.models import CheckResult

#: A quiet day is not a fault; a silent week is. Warn after this many hours.
EXPORT_FRESHNESS_HOURS = 24

_VERSION_SNIPPET = (
    "from agent_session_tools.migrations import CURRENT_VERSION; print(CURRENT_VERSION)"
)


def pinned_exporter_path() -> Path:
    """The exporter every hook calls (``installers.pinned_exporter()`` with ``$HOME`` expanded)."""
    return Path(installers.pinned_exporter().replace("$HOME", str(installers._HOME)))


def exporter_schema_version(exporter: Path, timeout: float = 30.0) -> int | None:
    """``CURRENT_VERSION`` of the agent-session-tools the exporter script runs, or ``None``.

    The console script's shebang names its interpreter; asking that interpreter
    is the only way to know what the *hook* will run, as opposed to whatever
    ``import agent_session_tools`` resolves to in this process.
    """
    try:
        first = exporter.open("rb").readline().decode("utf-8", "replace").strip()
    except OSError:
        return None
    if not first.startswith("#!"):
        return None
    interpreter = first[2:].split()[0]
    try:
        # The interpreter path comes from the script's own shebang, not from input.
        done = subprocess.run(
            [interpreter, "-c", _VERSION_SNIPPET],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    try:
        return int(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def database_user_version(db_path: Path) -> int | None:
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _db_path() -> Path:
    from agent_session_tools.config_loader import get_db_path

    return Path(get_db_path()).expanduser()


def check_exporter_schema(exporter: Path | None = None, db_path: Path | None = None) -> CheckResult:
    exporter = exporter or pinned_exporter_path()
    db_path = db_path or _db_path()
    if not exporter.exists() or not os.access(exporter, os.X_OK):
        return CheckResult(
            category="harness",
            name="exporter_schema",
            status="fail",
            message=f"pinned exporter {exporter} is missing; every export hook fails",
            fix_hint="studyloop install tools",
            fix_auto=True,
        )
    supported = exporter_schema_version(exporter)
    if not db_path.exists():
        return CheckResult(
            category="harness",
            name="exporter_schema",
            status="pass",
            message=(
                f"no session database yet; the first export creates it "
                f"(exporter schema v{supported})"
            ),
            fix_hint="",
            fix_auto=False,
        )
    current = database_user_version(db_path)
    if supported is None or current is None:
        return CheckResult(
            category="harness",
            name="exporter_schema",
            status="warn",
            message=(
                f"could not compare schemas (exporter {supported}, database {current}); "
                f"run {exporter} once and read {installers.EXPORT_HOOK_LOG}"
            ),
            fix_hint="",
            fix_auto=False,
        )
    if supported < current:
        return CheckResult(
            category="harness",
            name="exporter_schema",
            status="fail",
            message=(
                f"the exporter the hooks call supports schema v{supported} but the database "
                f"is v{current}: every export fails as 'newer than supported'; nothing is captured"
            ),
            fix_hint="studyloop install tools  (reinstall the pinned tools from this release)",
            fix_auto=False,
        )
    if supported > current:
        return CheckResult(
            category="harness",
            name="exporter_schema",
            status="warn",
            message=(
                f"the exporter supports schema v{supported}; the database is v{current} and its "
                f"first run will migrate it -- take a backup first if that matters to you"
            ),
            fix_hint="",
            fix_auto=False,
        )
    return CheckResult(
        category="harness",
        name="exporter_schema",
        status="pass",
        message=f"exporter and database agree on schema v{current}",
        fix_hint="",
        fix_auto=False,
    )


def newest_message_at(db_path: Path) -> datetime | None:
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute("SELECT MAX(timestamp) FROM messages").fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if not row or not row[0]:
        return None
    text = str(row[0]).replace("Z", "+00:00")
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


def check_export_freshness(
    db_path: Path | None = None,
    *,
    now: datetime | None = None,
    max_age_hours: float = EXPORT_FRESHNESS_HOURS,
) -> CheckResult:
    db_path = db_path or _db_path()
    newest = newest_message_at(db_path) if db_path.exists() else None
    if newest is None:
        return CheckResult(
            category="harness",
            name="export_freshness",
            status="warn",
            message="no exported messages found; the hooks have never captured a session",
            fix_hint="studyloop doctor --fix  (installs the export hooks), then close one session",
            fix_auto=True,
        )
    age_hours = ((now or datetime.now(UTC)) - newest).total_seconds() / 3600
    if age_hours > max_age_hours:
        return CheckResult(
            category="harness",
            name="export_freshness",
            status="warn",
            message=(
                f"newest exported message is {age_hours:.0f} h old (limit {max_age_hours:.0f} h); "
                f"if you have used a harness since, read {installers.EXPORT_HOOK_LOG}"
            ),
            fix_hint="",
            fix_auto=False,
        )
    return CheckResult(
        category="harness",
        name="export_freshness",
        status="pass",
        message=f"newest exported message is {age_hours:.1f} h old",
        fix_hint="",
        fix_auto=False,
    )


__all__ = [
    "EXPORT_FRESHNESS_HOURS",
    "check_export_freshness",
    "check_exporter_schema",
    "database_user_version",
    "exporter_schema_version",
    "newest_message_at",
    "pinned_exporter_path",
]
