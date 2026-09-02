"""Tests for FastAPI web app — API endpoints via TestClient."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

pytest = __import__("pytest")
pytest.importorskip("fastapi")

from unittest.mock import patch  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402  # pyright: ignore[reportMissingImports]

from studyloop.cli import cli  # noqa: E402
from studyloop.web.app import create_app  # noqa: E402

if TYPE_CHECKING:
    from pytest import MonkeyPatch


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create a TestClient with a temp study directory."""
    # Create a course with flashcards and quizzes
    course_dir = tmp_path / "test-course"
    fc_dir = course_dir / "flashcards"
    fc_dir.mkdir(parents=True)
    quiz_dir = course_dir / "quizzes"
    quiz_dir.mkdir(parents=True)

    import json

    fc_dir.joinpath("ch1-flashcards.json").write_text(
        json.dumps(
            {
                "title": "Chapter 1",
                "cards": [
                    {"front": "What is Python?", "back": "A programming language"},
                    {"front": "What is a list?", "back": "An ordered collection"},
                ],
            }
        )
    )
    quiz_dir.joinpath("ch1-quiz.json").write_text(
        json.dumps(
            {
                "title": "Chapter 1 Quiz",
                "questions": [
                    {
                        "question": "Which is a Python type?",
                        "answerOptions": [
                            {"text": "int", "isCorrect": True},
                            {"text": "foo", "isCorrect": False},
                        ],
                    }
                ],
            }
        )
    )

    app = create_app(study_dirs=[str(course_dir)])
    return TestClient(app)


class TestIndex:
    def test_root_returns_html(self, client: TestClient) -> None:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_security_headers(self, client: TestClient) -> None:
        """R-13: DENY + CSP + Referrer-Policy + Permissions-Policy, no X-XSS-Protection.

        DENY (not SAMEORIGIN) because no iframe surface exists anywhere in
        static/ after the ttyd retirement (stage 4) — the same-origin
        /terminal/ iframe this header used to be weakened for is gone.
        X-XSS-Protection is a deprecated no-op in every modern browser and
        must NOT be set; the CSP below is its replacement. R-13c adds
        object-src/base-uri/frame-ancestors/form-action, the four directives
        a CSP audit checks for by name regardless of what default-src covers.
        `BaseHTTPMiddleware` (Starlette) only wraps the ASGI `http` scope, so
        none of these headers reach the WebSocket upgrade response for
        `/api/session/ws` etc. — inert, not a gap: a 101 Switching Protocols
        response has no document to render, so there is nothing for a
        content policy to police.
        """
        resp = client.get("/")
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["referrer-policy"] == "same-origin"
        assert resp.headers["permissions-policy"] == "geolocation=(), microphone=(), camera=()"
        assert "x-xss-protection" not in resp.headers

        csp = resp.headers["content-security-policy"]
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        # No 'unsafe-inline' for script-src: both inline <script> blocks that
        # used to live in index.html were moved to files under web/static/js/
        # in this same stage. 'unsafe-eval' IS present and required — Alpine
        # evaluates every x-data/x-text/@click expression via `new Function`
        # internally (Alpine's own documented CSP constraint); confirmed by
        # reproduction that script-src 'self' alone leaves every Alpine
        # binding throwing a CSP pageerror and rendering empty. style-src
        # keeps 'unsafe-inline' — Alpine's :style bindings and x-transition
        # set inline style attributes at runtime, which cannot be nonced
        # (only <style> elements/<link> can).
        script_src = next(part for part in csp.split(";") if "script-src" in part).strip()
        assert "unsafe-inline" not in script_src
        assert "unsafe-eval" in script_src
        # connect-src is 'self'-only by default: --dev --dev-engine
        # ghostty's WASM VT100 parser is the ONLY consumer of the data:
        # exception (its bootstrap calls
        # fetch("data:application/wasm;base64,...")), so `data:` must be
        # scoped to dev_mode, not sent unconditionally to every learner who
        # never passes --dev. See TestDevModeCsp below for the dev_mode=True
        # case.
        assert "connect-src 'self'" in csp
        connect_src = next(part for part in csp.split(";") if "connect-src" in part).strip()
        assert "data:" not in connect_src
        # R-13c: no <object>/<embed> plugin content, no <base> tag anywhere
        # in index.html (verified: zero matches), and every <form> uses
        # @submit.prevent with no action= attribute at all (verified: zero
        # matches) — so object-src/base-uri/form-action cost nothing and
        # close a real gap (a future <base> or a plugin embed would
        # otherwise be unrestricted by this policy). frame-ancestors is the
        # CSP-native form of X-Frame-Options: DENY, kept alongside it for
        # browsers that only honour one or the other.
        assert "object-src 'none'" in csp
        assert "base-uri 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "form-action 'self'" in csp

    def test_csp_header_present_on_document_response(self, client: TestClient) -> None:
        """Fold from the M1 council (A?): a CSP-violation console check alone
        would pass if the header were deleted entirely and the browser just
        never enforced anything. Assert the header itself exists, not only
        the absence of violations."""
        resp = client.get("/")
        assert resp.headers.get("content-security-policy"), (
            "Content-Security-Policy header missing from the document response"
        )

    def test_no_inline_script_blocks_in_index_html(self) -> None:
        """The two inline <script> blocks this stage moved out must not come back.

        A regression here would make the script-src 'self' CSP above break
        the app (no 'unsafe-inline', no nonce), rather than just fail this
        test — so this guards the CSP's own precondition, not just a style
        preference.
        """
        html = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "studyloop"
            / "web"
            / "static"
            / "index.html"
        ).read_text()
        # Strip HTML comments first: this repo's comments reference the word
        # "<script>" in prose (e.g. documenting where code moved to), which
        # is not a real tag and must not trip this check.
        without_comments = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
        real_script_tags = re.findall(r"<script\b[^>]*>", without_comments)
        no_src = [tag for tag in real_script_tags if "src=" not in tag]
        assert not no_src, (
            f"found a bare inline <script> block with no src=: {no_src!r} — "
            "move it to a file under web/static/js/ or the CSP's "
            "script-src 'self' will break it"
        )


class TestDevModeCsp:
    """R-13c fold (A2): connect-src 'self' data: must be dev_mode-only.

    The exception exists for exactly one consumer: --dev --dev-engine
    ghostty's WASM bootstrap. Sending it unconditionally would grant every
    default-mode learner a connect-src relaxation they have no use for.
    """

    def test_no_data_exception_when_dev_mode_is_off(self) -> None:
        app = create_app(dev_mode=False)
        resp = TestClient(app).get("/")
        csp = resp.headers["content-security-policy"]
        connect_src = next(part for part in csp.split(";") if "connect-src" in part).strip()
        assert "data:" not in connect_src

    def test_data_exception_present_when_dev_mode_is_on(self) -> None:
        app = create_app(dev_mode=True)
        resp = TestClient(app).get("/")
        csp = resp.headers["content-security-policy"]
        connect_src = next(part for part in csp.split(";") if "connect-src" in part).strip()
        assert "data:" in connect_src


class TestCoursesAPI:
    def test_list_courses(self, client: TestClient) -> None:
        resp = client.get("/api/courses")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "test-course"
        assert data[0]["flashcard_count"] == 2
        assert data[0]["quiz_count"] == 1
        # publisher is a display/grouping field (parent dir name); present + string.
        assert "publisher" in data[0]
        assert isinstance(data[0]["publisher"], str)

    def test_sources_returns_flat_strings(self, client: TestClient) -> None:
        resp = client.get("/api/sources/test-course?mode=flashcards")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert isinstance(data[0], str)

    def test_stats(self, client: TestClient) -> None:
        resp = client.get("/api/stats/test-course")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_reviews" in data

    def test_due(self, client: TestClient) -> None:
        resp = client.get("/api/due/test-course")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestWebCommandConfig:
    def test_web_reads_review_dirs_from_studyloop_config_env(
        self, monkeypatch: MonkeyPatch, tmp_path: Path
    ) -> None:
        import uvicorn
        from click.testing import CliRunner

        config_path = tmp_path / "custom-config.yaml"
        course_dir = tmp_path / "course-a"
        config_path.write_text(f"review:\n  directories:\n    - {course_dir}\n")
        monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))

        captured: dict[str, object] = {}

        def fake_create_app(**kwargs):
            captured.update(kwargs)
            return object()

        # _web.py calls _StudyLoopServer(config).run() (subclass of uvicorn.Server),
        # not uvicorn.run(), so patch the bound method to keep the test from binding
        # a real port.
        monkeypatch.setattr("studyloop.web.app.create_app", fake_create_app)
        monkeypatch.setattr(uvicorn.Server, "run", lambda *args, **kwargs: None)

        result = CliRunner().invoke(cli, ["web"])

        assert result.exit_code == 0, result.output
        assert captured["study_dirs"] == [str(course_dir)]

    def test_wrong(self, client: TestClient) -> None:
        resp = client.get("/api/wrong/test-course")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestCardsAPI:
    def test_get_flashcards(self, client: TestClient) -> None:
        resp = client.get("/api/cards/test-course?mode=flashcards")
        assert resp.status_code == 200
        cards = resp.json()
        assert len(cards) == 2
        assert cards[0]["type"] == "flashcard"
        assert cards[0]["front"] == "What is Python?"

    def test_get_quizzes(self, client: TestClient) -> None:
        resp = client.get("/api/cards/test-course?mode=quiz")
        assert resp.status_code == 200
        questions = resp.json()
        assert len(questions) == 1
        assert questions[0]["type"] == "quiz"

    def test_missing_course_404(self, client: TestClient) -> None:
        resp = client.get("/api/cards/nonexistent")
        assert resp.status_code == 404

    def test_post_review(self, client: TestClient, tmp_path: Path) -> None:
        with patch("studyloop.services.review.record_review"):
            resp = client.post(
                "/api/review",
                json={
                    "course": "test-course",
                    "card_hash": "abc123",
                    "correct": True,
                },
            )
            assert resp.status_code == 200
            assert resp.json()["ok"] is True


class TestHistoryAPI:
    def test_get_history_empty(self, client: TestClient) -> None:
        resp = client.get("/api/history")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_post_session(self, client: TestClient) -> None:
        with patch("studyloop.web.routes.history.record_session"):
            resp = client.post(
                "/api/session",
                json={
                    "course": "test-course",
                    "total": 10,
                    "correct": 8,
                },
            )
            assert resp.status_code == 200
            assert resp.json()["ok"] is True


class TestStaticFiles:
    def test_css_served(self, client: TestClient) -> None:
        resp = client.get("/style.css")
        assert resp.status_code == 200
        assert "text/css" in resp.headers["content-type"]

    def test_js_served(self, client: TestClient) -> None:
        resp = client.get("/components.js")
        assert resp.status_code == 200

    def test_manifest_served(self, client: TestClient) -> None:
        resp = client.get("/manifest.json")
        assert resp.status_code == 200
