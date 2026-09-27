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
        # Two different situations share a missing exporter. With a session
        # database present, hooks are (or were) capturing history and now every
        # run fails silently -- the incident this check was born of: ``fail``.
        # With no database, nothing has ever been captured and nothing is being
        # lost -- a fresh install, or a machine that never ran ``install
        # tools`` -- so this is the same ``warn`` the "session-export: not
        # found on PATH" row gives. Reporting ``fail`` here broke the release
        # ``install-smoke`` (a wheel in a fresh venv) on every run since the
        # check landed on 2026-09-12.
        if not db_path.exists():
            return CheckResult(
                category="harness",
                name="exporter_schema",
                status="warn",
                message=(
                    f"pinned exporter {exporter} is not installed and no session database "
                    "exists yet; nothing is captured until `studyloop install tools` runs"
                ),
                fix_hint="studyloop install tools",
                fix_auto=True,
            )
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
    return _parse_stamp(row[0])


def _parse_stamp(raw: object) -> datetime | None:
    text = str(raw).replace("Z", "+00:00")
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


#: Where kiro-cli 2.x keeps its sessions: one ``<uuid>.jsonl`` plus ``<uuid>.json``
#: per session. The Kiro exporter still reads only data.sqlite3's conversation
#: tables, which kiro-cli stopped updating on 2026-09-05 on the machine that
#: reported the gap (StudyLoop #49). Until the exporter reads this store, the
#: directory changing after the newest ``kiro_cli`` export means Kiro sessions are
#: missing from the database. Retire this probe when #49 lands.
KIRO_SESSIONS_DIR = Path.home() / ".kiro" / "sessions" / "cli"


def newest_message_by_source(db_path: Path) -> dict[str, datetime]:
    """Newest exported message per ``sessions.source``; ``{}`` when unreadable."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return {}
    try:
        rows = conn.execute(
            "SELECT s.source, MAX(m.timestamp) FROM messages m "
            "JOIN sessions s ON s.id = m.session_id GROUP BY s.source"
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    newest: dict[str, datetime] = {}
    for source, raw in rows:
        stamp = _parse_stamp(raw) if raw else None
        if source and stamp:
            newest[str(source)] = stamp
    return newest


def _age(hours: float) -> str:
    if hours < 1:
        return "under 1 h"
    return f"{hours:.0f} h" if hours < 48 else f"{hours / 24:.0f} d"


def check_export_freshness(
    db_path: Path | None = None,
    *,
    now: datetime | None = None,
    max_age_hours: float = EXPORT_FRESHNESS_HOURS,
    kiro_sessions_dir: Path | None = None,
) -> CheckResult:
    """How long ago each harness last had a message exported.

    The newest message across every harness hid a 22-day Kiro gap behind a 48 h
    Codex age (reported 2026-09-27), so a warning lists every harness's own age.
    Kiro gets one more probe: kiro-cli's session store changing well after the
    newest ``kiro_cli`` export means sessions the exporter cannot read (#49). That
    warns even when another harness is fresh, because the fresh one hides it.
    """
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
    now = now or datetime.now(UTC)
    by_source = newest_message_by_source(db_path)
    listing = ", ".join(
        f"{source} {_age((now - stamp).total_seconds() / 3600)}"
        for source, stamp in sorted(by_source.items(), key=lambda item: item[1], reverse=True)
    )

    store = kiro_sessions_dir or KIRO_SESSIONS_DIR
    kiro_newest = by_source.get("kiro_cli")
    try:
        store_changed = datetime.fromtimestamp(store.stat().st_mtime, tz=UTC)
    except OSError:
        store_changed = None
    if (
        kiro_newest is not None
        and store_changed is not None
        and (store_changed - kiro_newest).total_seconds() / 3600 > max_age_hours
    ):
        kiro_age = _age((now - kiro_newest).total_seconds() / 3600)
        changed_age = _age((now - store_changed).total_seconds() / 3600)
        return CheckResult(
            category="harness",
            name="export_freshness",
            status="warn",
            message=(
                f"kiro_cli's newest export is {kiro_age} old, but kiro-cli wrote to {store} "
                f"{changed_age} ago: kiro-cli keeps its sessions there now and the exporter "
                f"does not read that store yet, so newer Kiro sessions are not in the "
                f"database. By harness: {listing}"
            ),
            fix_hint="Nothing to repair locally; the exporter has to learn this store "
            "(StudyLoop #49). The session files stay on disk for a later backfill.",
            fix_auto=False,
        )

    age_hours = (now - newest).total_seconds() / 3600
    if age_hours > max_age_hours:
        by_harness = f"; by harness: {listing}" if listing else ""
        return CheckResult(
            category="harness",
            name="export_freshness",
            status="warn",
            message=(
                f"newest exported message is {age_hours:.0f} h old (limit {max_age_hours:.0f} h)"
                f"{by_harness}; if you have used a harness since, read "
                f"{installers.EXPORT_HOOK_LOG}"
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
    "KIRO_SESSIONS_DIR",
    "check_export_freshness",
    "check_exporter_schema",
    "database_user_version",
    "exporter_schema_version",
    "newest_message_at",
    "newest_message_by_source",
    "pinned_exporter_path",
]
