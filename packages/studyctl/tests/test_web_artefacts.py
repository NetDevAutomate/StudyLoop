"""Tests for artefact serving — path validation and directory traversal prevention."""

from __future__ import annotations

from typing import TYPE_CHECKING

pytest = __import__("pytest")
pytest.importorskip("fastapi")

from unittest.mock import patch  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from studyctl.web.app import create_app  # noqa: E402

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def artefact_client(tmp_path: Path) -> TestClient:
    """Create a TestClient with a temp content base_path."""
    # Set up course with artefacts
    course_dir = tmp_path / "my-course"
    audio_dir = course_dir / "audio"
    audio_dir.mkdir(parents=True)
    video_dir = course_dir / "video"
    video_dir.mkdir(parents=True)

    (audio_dir / "episode-01.mp3").write_bytes(b"fake-audio")
    (video_dir / "overview.mp4").write_bytes(b"fake-video")

    # Also create a course with flashcards so /api/courses works
    fc_dir = course_dir / "flashcards"
    fc_dir.mkdir(parents=True)

    from studyctl.settings import ContentConfig, Settings

    fake_settings = Settings(content=ContentConfig(base_path=tmp_path))

    app = create_app(study_dirs=[str(course_dir)])

    with patch("studyctl.web.routes.artefacts.load_settings", return_value=fake_settings):
        yield TestClient(app)


class TestArtefactServing:
    def test_serve_audio_file(self, artefact_client: TestClient) -> None:
        resp = artefact_client.get("/artefacts/my-course/audio/episode-01.mp3")
        assert resp.status_code == 200
        assert resp.content == b"fake-audio"

    def test_serve_video_file(self, artefact_client: TestClient) -> None:
        resp = artefact_client.get("/artefacts/my-course/video/overview.mp4")
        assert resp.status_code == 200
        assert resp.content == b"fake-video"

    def test_nonexistent_file_404(self, artefact_client: TestClient) -> None:
        resp = artefact_client.get("/artefacts/my-course/audio/missing.mp3")
        assert resp.status_code == 404

    def test_nonexistent_course_404(self, artefact_client: TestClient) -> None:
        resp = artefact_client.get("/artefacts/bad-course/audio/file.mp3")
        assert resp.status_code == 404


class TestDirectoryTraversal:
    def test_dotdot_in_course_blocked(self, artefact_client: TestClient) -> None:
        resp = artefact_client.get("/artefacts/../etc/audio/passwd")
        # FastAPI path validation or our check blocks this
        assert resp.status_code in (404, 422)

    def test_dotdot_in_filename_blocked(self, artefact_client: TestClient) -> None:
        resp = artefact_client.get("/artefacts/my-course/audio/../../etc/passwd")
        assert resp.status_code in (404, 422)

    def test_dotdot_in_type_blocked(self, artefact_client: TestClient) -> None:
        resp = artefact_client.get("/artefacts/my-course/../../../etc/passwd")
        assert resp.status_code in (404, 422)


class TestListArtefacts:
    def test_list_course_artefacts(self, artefact_client: TestClient) -> None:
        resp = artefact_client.get("/api/artefacts/my-course")
        assert resp.status_code == 200
        data = resp.json()
        types = {item["type"] for item in data}
        assert "audio" in types
        assert "video" in types

    def test_list_nonexistent_course_404(self, artefact_client: TestClient) -> None:
        resp = artefact_client.get("/api/artefacts/nonexistent")
        assert resp.status_code == 404
