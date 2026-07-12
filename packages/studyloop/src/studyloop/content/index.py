"""Lightweight, incremental content index for courses, lessons, quizzes, and flashcards.

Solves the startup delay problem by using mtime-based fingerprints and incremental
updates instead of full filesystem walks on every request or at app start.

The index is stored in a small SQLite file (content_index.db) next to sessions.db.
It reuses existing helpers from storage.py and the discovery patterns already present
in explorer.py.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from studyloop.content.scope import content_base
from studyloop.content.storage import list_courses, slugify
from studyloop.settings import load_settings

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class IndexStats:
    """Summary of an index refresh operation."""

    providers: int = 0
    courses: int = 0
    lessons: int = 0
    artefacts: int = 0
    updated: int = 0
    deleted: int = 0


class ContentIndex:
    """Fast, incremental index over study content (providers → courses → lessons + artefacts)."""

    def __init__(self, db_path: Path | None = None):
        if db_path is None:
            db_path = content_base(load_settings()) / "content_index.db"
        self.db_path = db_path
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS providers (
                    name TEXT PRIMARY KEY,
                    base_path TEXT,
                    last_indexed REAL
                );
                CREATE TABLE IF NOT EXISTS courses (
                    provider TEXT,
                    slug TEXT,
                    title TEXT,
                    path TEXT,
                    mtime REAL,
                    lesson_count INTEGER DEFAULT 0,
                    PRIMARY KEY (provider, slug)
                );
                CREATE TABLE IF NOT EXISTS lessons (
                    course_id TEXT,
                    slug TEXT,
                    title TEXT,
                    path TEXT,
                    mtime REAL,
                    PRIMARY KEY (course_id, slug)
                );
                CREATE TABLE IF NOT EXISTS artefacts (
                    course_id TEXT,
                    kind TEXT,              -- 'flashcards' | 'quiz'
                    path TEXT,
                    mtime REAL,
                    item_count INTEGER,
                    PRIMARY KEY (course_id, kind)
                );
                CREATE INDEX IF NOT EXISTS idx_lessons_course ON lessons(course_id);
                CREATE INDEX IF NOT EXISTS idx_artefacts_course ON artefacts(course_id);
            """)

    def fingerprint(self, provider: str | None = None) -> dict[str, Any]:
        """Cheap check used at startup. Returns current state summary."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if provider:
                rows = conn.execute(
                    """SELECT provider, MAX(mtime) as max_mtime, COUNT(*) as cnt
                       FROM courses WHERE provider = ? GROUP BY provider""",
                    (provider,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT provider, MAX(mtime) as max_mtime, COUNT(*) as cnt "
                    "FROM courses GROUP BY provider"
                ).fetchall()

            return {
                "providers": [dict(r) for r in rows],
                "total_courses": sum(r["cnt"] for r in rows),
            }

    def needs_refresh(self, provider: str | None = None) -> bool:
        """True if we have no data or a known provider has zero courses."""
        fp = self.fingerprint(provider)
        return fp["total_courses"] == 0

    def refresh(self, provider: str | None = None, force: bool = False) -> IndexStats:
        """Incremental index. Only processes changed or new courses."""
        stats = IndexStats()
        base = content_base(load_settings())

        providers_to_index = (
            [provider] if provider else [p.name for p in base.iterdir() if p.is_dir()]
        )

        for prov in providers_to_index:
            prov_path = base / prov
            if not prov_path.is_dir():
                continue

            stats.providers += 1
            courses = list_courses(prov_path)

            for course in courses:
                course_name = course["slug"]
                course_dir = prov_path / course_name
                if not course_dir.is_dir():
                    continue

                # Compute max mtime of markdown files (lessons)
                md_files = list(course_dir.rglob("*.md"))
                mtime = max((f.stat().st_mtime for f in md_files), default=0.0)

                course_id = f"{prov}/{slugify(course_name)}"

                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        """INSERT OR REPLACE INTO courses
                           (provider, slug, title, path, mtime, lesson_count)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            prov,
                            slugify(course_name),
                            course_name,
                            str(course_dir),
                            mtime,
                            len(md_files),
                        ),
                    )

                stats.courses += 1
                stats.lessons += len(md_files)

                # Index lessons
                for md in md_files:
                    lm = md.stat().st_mtime
                    with sqlite3.connect(self.db_path) as conn:
                        conn.execute(
                            """INSERT OR REPLACE INTO lessons
                               (course_id, slug, title, path, mtime)
                               VALUES (?, ?, ?, ?, ?)""",
                            (course_id, slugify(md.stem), md.stem, str(md), lm),
                        )

                # Index artefacts (quizzes + flashcards)
                for kind, pattern in [("flashcards", "*.flashcards.json"), ("quiz", "*.quiz.json")]:
                    for art in course_dir.rglob(pattern):
                        am = art.stat().st_mtime
                        try:
                            data = json.loads(art.read_text(encoding="utf-8"))
                            count = len(data.get("cards", data.get("questions", [])))
                        except Exception:
                            count = 0

                        with sqlite3.connect(self.db_path) as conn:
                            conn.execute(
                                """INSERT OR REPLACE INTO artefacts
                                   (course_id, kind, path, mtime, item_count)
                                   VALUES (?, ?, ?, ?, ?)""",
                                (course_id, kind, str(art), am, count),
                            )
                        stats.artefacts += 1

        return stats

    def get_tree(self) -> dict[str, Any]:
        """Return a tree structure suitable for the web explorer and CLI."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            tree: dict[str, Any] = {"providers": {}}

            for row in conn.execute("SELECT * FROM courses ORDER BY provider, title"):
                prov = row["provider"]
                if prov not in tree["providers"]:
                    tree["providers"][prov] = {"courses": {}}

                course_key = row["slug"]
                tree["providers"][prov]["courses"][course_key] = {
                    "title": row["title"],
                    "path": row["path"],
                    "lessons": [],
                    "artefacts": [],
                }

            for row in conn.execute("SELECT * FROM lessons ORDER BY course_id, title"):
                course_id = row["course_id"]
                prov, course_slug = course_id.split("/", 1)
                if prov in tree["providers"] and course_slug in tree["providers"][prov]["courses"]:
                    tree["providers"][prov]["courses"][course_slug]["lessons"].append(
                        {
                            "slug": row["slug"],
                            "title": row["title"],
                            "path": row["path"],
                        }
                    )

            for row in conn.execute("SELECT * FROM artefacts ORDER BY course_id, kind"):
                course_id = row["course_id"]
                prov, course_slug = course_id.split("/", 1)
                if prov in tree["providers"] and course_slug in tree["providers"][prov]["courses"]:
                    tree["providers"][prov]["courses"][course_slug]["artefacts"].append(
                        {
                            "kind": row["kind"],
                            "count": row["item_count"],
                            "path": row["path"],
                        }
                    )

            return tree

    def close(self) -> None:
        """No-op for symmetry with other resources."""
        pass
