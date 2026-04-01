"""Minimal web server for the study PWA — no external dependencies.

Serves static files and JSON API endpoints using only stdlib http.server.
"""

from __future__ import annotations

import json
import logging
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from studyctl.review_db import (
    get_course_stats,
    get_due_cards,
    record_card_review,
    record_session,
)
from studyctl.review_loader import (
    discover_directories,
    find_content_dirs,
    load_flashcards,
    load_quizzes,
)

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


class StudyHandler(SimpleHTTPRequestHandler):
    """Handle static files + /api/* JSON endpoints."""

    def __init__(self, *args, study_dirs=None, **kwargs) -> None:  # type: ignore[override]
        self._study_dirs: list[str] = study_dirs or []
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/courses":
            self._handle_courses()
        elif path.startswith("/api/cards/"):
            course = path.split("/api/cards/", 1)[1]
            qs = parse_qs(parsed.query)
            mode = qs.get("mode", ["flashcards"])[0]
            self._handle_cards(course, mode)
        elif path.startswith("/api/sources/"):
            course = path.split("/api/sources/", 1)[1]
            qs = parse_qs(parsed.query)
            mode = qs.get("mode", ["flashcards"])[0]
            self._handle_sources(course, mode)
        elif path.startswith("/api/stats/"):
            course = path.split("/api/stats/", 1)[1]
            self._handle_stats(course)
        elif path == "/api/history":
            self._handle_history()
        else:
            # Serve static files; route / to index.html
            if path == "/":
                self.path = "/index.html"
            super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/review":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            self._handle_review(body)
        elif parsed.path == "/api/session":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            self._handle_session(body)
        else:
            self._json_response({"error": "not found"}, 404)

    def _handle_courses(self) -> None:
        courses = discover_directories(self._study_dirs)
        result = []
        for name, path in courses:
            fc_dir, quiz_dir = find_content_dirs(path)
            fc_count = len(load_flashcards(fc_dir)) if fc_dir else 0
            quiz_count = len(load_quizzes(quiz_dir)) if quiz_dir else 0
            due = len(get_due_cards(name))
            stats = get_course_stats(name)
            result.append(
                {
                    "name": name,
                    "flashcard_count": fc_count,
                    "quiz_count": quiz_count,
                    "due_count": due,
                    "total_reviews": stats.get("total_reviews", 0),
                    "mastered": stats.get("mastered", 0),
                }
            )
        self._json_response(result)

    def _handle_cards(self, course_name: str, mode: str) -> None:
        courses = discover_directories(self._study_dirs)
        match = next(((n, p) for n, p in courses if n == course_name), None)
        if not match:
            self._json_response({"error": f"Course '{course_name}' not found"}, 404)
            return

        _, path = match
        fc_dir, quiz_dir = find_content_dirs(path)

        if mode == "flashcards" and fc_dir:
            cards = load_flashcards(fc_dir)
            self._json_response(
                [
                    {
                        "type": "flashcard",
                        "front": c.front,
                        "back": c.back,
                        "hash": c.card_hash,
                        "source": c.source,
                    }
                    for c in cards
                ]
            )
        elif mode == "quiz" and quiz_dir:
            questions = load_quizzes(quiz_dir)
            self._json_response(
                [
                    {
                        "type": "quiz",
                        "question": q.question,
                        "options": [
                            {
                                "text": o.text,
                                "is_correct": o.is_correct,
                                "rationale": o.rationale,
                            }
                            for o in q.options
                        ],
                        "hint": q.hint,
                        "hash": q.card_hash,
                        "source": q.source,
                    }
                    for q in questions
                ]
            )
        else:
            self._json_response({"error": f"No {mode} content for {course_name}"}, 404)

    def _handle_sources(self, course_name: str, mode: str) -> None:
        """Return unique source names for filtering by chapter."""
        courses = discover_directories(self._study_dirs)
        match = next(((n, p) for n, p in courses if n == course_name), None)
        if not match:
            self._json_response([])
            return
        _, path = match
        fc_dir, quiz_dir = find_content_dirs(path)
        sources: set[str] = set()
        if mode == "flashcards" and fc_dir:
            for c in load_flashcards(fc_dir):
                if c.source:
                    sources.add(c.source)
        elif mode == "quiz" and quiz_dir:
            for q in load_quizzes(quiz_dir):
                if q.source:
                    sources.add(q.source)
        self._json_response(sorted(sources))

    def _handle_stats(self, course_name: str) -> None:
        stats = get_course_stats(course_name)
        self._json_response(stats)

    def _handle_history(self) -> None:
        """Return recent review sessions for the home page."""
        import sqlite3

        from studyctl.review_db import _get_db, ensure_tables

        path = _get_db()
        if not path.exists():
            self._json_response([])
            return
        ensure_tables(path)
        conn = sqlite3.connect(path)
        rows = conn.execute(
            "SELECT course, mode, total, correct, duration_seconds, "
            "started_at, finished_at FROM review_sessions "
            "ORDER BY started_at DESC LIMIT 20"
        ).fetchall()
        conn.close()
        self._json_response(
            [
                {
                    "course": r[0],
                    "mode": r[1],
                    "total": r[2],
                    "correct": r[3],
                    "duration": r[4],
                    "date": r[5][:10] if r[5] else None,
                }
                for r in rows
            ]
        )

    def _handle_review(self, body: dict) -> None:
        try:
            record_card_review(
                course=body["course"],
                card_type=body.get("card_type", "flashcard"),
                card_hash=body["card_hash"],
                correct=body["correct"],
                response_time_ms=body.get("response_time_ms"),
            )
            self._json_response({"ok": True})
        except (KeyError, Exception) as exc:
            self._json_response({"error": str(exc)}, 400)

    def _handle_session(self, body: dict) -> None:
        try:
            record_session(
                course=body["course"],
                mode=body.get("mode", "flashcards"),
                total=body["total"],
                correct=body["correct"],
                duration_seconds=body.get("duration_seconds"),
            )
            self._json_response({"ok": True})
        except (KeyError, Exception) as exc:
            self._json_response({"error": str(exc)}, 400)

    def _json_response(self, data: object, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        logger.info(fmt, *args)


def serve(
    host: str = "localhost",
    port: int = 8567,
    study_dirs: list[str] | None = None,
) -> None:
    """Start the study PWA web server."""
    handler = partial(StudyHandler, study_dirs=study_dirs)
    server = HTTPServer((host, port), handler)
    print(f"Study PWA serving at http://{host}:{port}")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
