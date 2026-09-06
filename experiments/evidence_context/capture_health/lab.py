"""Synthetic JSON importer and health report; no real harness integration."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def instant(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Explicit timezone required")
    return result


class CaptureLab:
    def __init__(self, path: Path):
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
        PRAGMA application_id=1398229060;
        CREATE TABLE records(source TEXT, id TEXT, body TEXT, PRIMARY KEY(source,id));
        CREATE TABLE attempts(seq INTEGER PRIMARY KEY, source TEXT, at TEXT, outcome TEXT,
          imported INTEGER, error_code TEXT);
        """)

    @classmethod
    def open(cls, path: Path) -> CaptureLab:
        """Open an existing lab store without creating or migrating another DB."""
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True)
        if conn.execute("PRAGMA application_id").fetchone()[0] != 1398229060:
            conn.close()
            raise ValueError("Not a capture-health lab database")
        lab = cls.__new__(cls)
        lab.conn = conn
        conn.row_factory = sqlite3.Row
        return lab

    def close(self) -> None:
        self.conn.close()

    def capture(self, source: str, path: Path, at: str) -> bool:
        """One atomic synthetic file import. Failure retains prior successful data."""
        timestamp = instant(at)
        previous = self.conn.execute(
            "SELECT at FROM attempts WHERE source=? ORDER BY seq DESC LIMIT 1", (source,)
        ).fetchone()
        if previous and timestamp < instant(previous[0]):
            raise ValueError("Attempt timestamp precedes prior attempt")
        if not source:
            raise ValueError("Source identity required")
        error = None
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(rows, list) or any(
                not isinstance(r, dict)
                or not isinstance(r.get("id"), str)
                or not r["id"]
                or not isinstance(r.get("body"), str)
                for r in rows
            ):
                raise ValueError("Invalid records")
            if len({r["id"] for r in rows}) != len(rows):
                raise ValueError("Duplicate IDs in source snapshot")
        except OSError:
            rows, error = [], "source_unreadable"
        except (ValueError, UnicodeError):
            rows, error = [], "parse_failed"
        with self.conn:
            if error is None:
                self.conn.executemany(
                    "INSERT OR REPLACE INTO records VALUES (?,?,?)",
                    [(source, r["id"], r["body"]) for r in rows],
                )
            self.conn.execute(
                "INSERT INTO attempts(source,at,outcome,imported,error_code) VALUES (?,?,?,?,?)",
                (source, at, "failed" if error else "success", len(rows), error),
            )
        return error is None

    def report(
        self,
        source: str,
        *,
        now: str,
        max_age_seconds: int,
        detected: bool | None,
        skill_installed: bool | None,
        hook_registered: bool | None,
        repair_gaps: int | None = None,
    ) -> dict:
        if max_age_seconds <= 0 or (repair_gaps is not None and repair_gaps < 0):
            raise ValueError("Positive freshness threshold and nonnegative gap count required")
        clock = instant(now)
        attempts = list(
            self.conn.execute("SELECT * FROM attempts WHERE source=? ORDER BY seq", (source,))
        )
        last = attempts[-1] if attempts else None
        successes = [a for a in attempts if a["outcome"] == "success"]
        success = successes[-1] if successes else None
        lag = (clock - instant(success["at"])).total_seconds() if success else None
        issues = []
        for label, value in (
            ("source_detected", detected),
            ("skill_installed", skill_installed),
            ("hook_registered", hook_registered),
        ):
            if value is not True:
                issues.append(label + ("_unknown" if value is None else "_missing"))
        if not success:
            issues.append("no_successful_capture")
        if last and last["outcome"] == "failed":
            issues.append(last["error_code"])
        if lag is not None and lag > max_age_seconds:
            issues.append("capture_stale")
        if any(instant(a["at"]) > clock for a in attempts):
            issues.append("clock_inconsistent")
        if repair_gaps is None:
            issues.append("repair_coverage_unknown")
        elif repair_gaps:
            issues.append("repair_gaps")
        return {
            "source": source,
            "detected": detected,
            "skill_installed": skill_installed,
            "hook_registered": hook_registered,
            "last_attempt": last["at"] if last else None,
            "last_success": success["at"] if success else None,
            "last_imported_records": success["imported"] if success else None,
            "capture_age_seconds": lag,
            "max_age_seconds": max_age_seconds,
            "parse_failures": sum(a["error_code"] == "parse_failed" for a in attempts),
            "unreadable_failures": sum(a["error_code"] == "source_unreadable" for a in attempts),
            "repair_gaps": repair_gaps,
            "issues": issues,
            "state": "attention_required" if issues else "recent_capture_observed",
            "history_completeness": "not_established",
            "configuration_evidence": "caller_supplied_lab_fixture",
        }
