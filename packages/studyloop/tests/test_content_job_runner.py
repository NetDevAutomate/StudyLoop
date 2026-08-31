"""Tests for the job runner orchestrator (U4).

Stub backend + tmp-dir vault so we exercise the entire orchestration
path without touching real LLMs or the user's Obsidian dir. Each test
builds a fresh fixture so singleton state never leaks.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from _content_generator import DeterministicTestGenerator, GeneratorFixtureConfig
from _helpers import run_async

from studyloop.content import active_gen
from studyloop.content.job import JobRequest, _build_tasks, run_job
from studyloop.content.schemas import FlashcardDeck
from studyloop.content.scope import ResolvedSource, ScopeRequest
from studyloop.settings import CardGeneratorConfig, ContentConfig, Settings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _release_singleton(monkeypatch: pytest.MonkeyPatch):
    """Singleton is shared module state; release before AND after every test."""
    monkeypatch.setattr(
        "studyloop.content.job.get_generator",
        lambda _config: DeterministicTestGenerator(GeneratorFixtureConfig(card_count=3)),
    )
    run_async(active_gen.release())
    yield
    run_async(active_gen.release())


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    # 3-level tree: base/<publisher>/<course>/study-notes/<lesson>.md.
    # A "section" is one lesson file; course scope = one source per file.
    study = tmp_path / "Study"
    notes = study / "DataCamp" / "Intro_To_Pandas" / "study-notes"
    notes.mkdir(parents=True)
    (notes / "advanced-pandas.md").write_text(
        "# Pandas\n\nGroupby and pivot tables.", encoding="utf-8"
    )
    (notes / "joins.md").write_text("# Joins\n\nINNER, LEFT, RIGHT.", encoding="utf-8")
    return study


@pytest.fixture
def settings(vault: Path) -> Settings:
    s = Settings()
    s.content = ContentConfig(base_path=vault)
    s.card_generator = CardGeneratorConfig(backend="ollama", max_workers=2)
    return s


_PUBLISHER = "DataCamp"
_COURSE = "Intro_To_Pandas"


def _request(scope_kind: str = "section", **scope_kw) -> JobRequest:
    """Build a JobRequest with a default flashcards-only scope (section=joins file)."""
    scope = ScopeRequest(
        kind=scope_kind,  # type: ignore[arg-type]
        publisher=scope_kw.pop("publisher", _PUBLISHER),
        course=scope_kw.pop("course", _COURSE),
        section=scope_kw.pop("section", "joins"),
    )
    return JobRequest(
        publisher=_PUBLISHER,
        course=_COURSE,
        scope=scope,
        kinds=("flashcards",),
        on_existing=scope_kw.pop("on_existing", "suffix"),
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_writes_one_flashcard_file_per_source(self, settings: Settings, vault: Path) -> None:
        events: list[dict] = []
        result = run_job(
            "gen-1",
            JobRequest(
                publisher=_PUBLISHER,
                course=_COURSE,
                scope=ScopeRequest(kind="course", publisher=_PUBLISHER, course=_COURSE),
                kinds=("flashcards",),
            ),
            settings,
            on_event=events.append,
        )
        assert result.written == 2
        assert result.failed == 0
        # Events: started, 2x task_complete, all_done.
        types = [e["type"] for e in events]
        assert types[0] == "started"
        assert types[-1] == "all_done"
        assert types.count("task_complete") == 2
        # Files actually exist on disk.
        for outcome in result.outcomes:
            assert outcome.path is not None
            assert Path(outcome.path).is_file()
            data = json.loads(Path(outcome.path).read_text())
            FlashcardDeck.model_validate(data)  # writeback round-trips

    def test_writes_both_kinds_when_requested(self, settings: Settings, vault: Path) -> None:
        request = JobRequest(
            publisher=_PUBLISHER,
            course=_COURSE,
            scope=ScopeRequest(
                kind="section", publisher=_PUBLISHER, course=_COURSE, section="joins"
            ),
            kinds=("flashcards", "quizzes"),
        )
        result = run_job("gen-2", request, settings)
        assert result.written == 2  # 1 source x 2 kinds
        kinds_written = sorted(o.kind for o in result.outcomes if o.ok)
        assert kinds_written == ["flashcards", "quizzes"]

    def test_requested_count_controls_written_deck_sizes(
        self, settings: Settings, vault: Path
    ) -> None:
        events: list[dict] = []
        request = JobRequest(
            publisher=_PUBLISHER,
            course=_COURSE,
            scope=ScopeRequest(
                kind="section", publisher=_PUBLISHER, course=_COURSE, section="joins"
            ),
            kinds=("flashcards", "quizzes"),
            count_per_source=5,
        )

        result = run_job("gen-count", request, settings, on_event=events.append)

        assert result.written == 2
        started = events[0]
        assert started["type"] == "started"
        assert started["kinds"] == ["flashcards", "quizzes"]
        assert started["count_per_source"] == 5
        assert started["provider"] == "ollama"
        flashcards = json.loads(
            (vault / _PUBLISHER / _COURSE / "flashcards" / "joins-flashcards.json").read_text()
        )
        quizzes = json.loads(
            (vault / _PUBLISHER / _COURSE / "quizzes" / "joins-quiz.json").read_text()
        )
        assert len(flashcards["cards"]) == 5
        assert len(quizzes["questions"]) == 5


def test_build_tasks_uses_count_per_source_for_flashcards_and_quizzes() -> None:
    sources = [
        ResolvedSource(
            identifier="joins",
            title="Joins",
            markdown_text="# Joins\n\nINNER and LEFT joins.",
        )
    ]

    tasks = _build_tasks(sources, ("flashcards", "quizzes"), count_per_source=25)

    assert [(task.kind, task.count) for task in tasks] == [
        ("flashcards", 25),
        ("quiz", 25),
    ]


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


class TestPartialFailure:
    def test_one_failing_task_does_not_abort_run(
        self, settings: Settings, vault: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "studyloop.content.job.get_generator",
            lambda _config: DeterministicTestGenerator(
                GeneratorFixtureConfig(
                    card_count=3,
                    failure_mode="fail_titles",
                    failure_titles=("Joins",),
                )
            ),
        )
        result = run_job(
            "gen-3",
            JobRequest(
                publisher=_PUBLISHER,
                course=_COURSE,
                scope=ScopeRequest(kind="course", publisher=_PUBLISHER, course=_COURSE),
                kinds=("flashcards",),
            ),
            settings,
        )
        assert result.written == 1
        assert result.failed == 1
        # The good source still has a written file; the bad one has an error.
        good = next(o for o in result.outcomes if o.identifier == "advanced-pandas")
        bad = next(o for o in result.outcomes if o.identifier == "joins")
        assert good.ok and good.path
        assert not bad.ok and bad.error and "fail this title" in bad.error


class TestOnExistingPolicy:
    def test_overwrite_replaces_existing_file(self, settings: Settings, vault: Path) -> None:
        target_file = (
            settings.content.base_path
            / "DataCamp"
            / "Intro_To_Pandas"
            / "flashcards"
            / "joins-flashcards.json"
        )
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text("OLD")
        result = run_job(
            "gen-4",
            _request(on_existing="overwrite"),
            settings,
        )
        assert result.written == 1
        # File replaced; no longer "OLD".
        assert target_file.read_text() != "OLD"

    def test_suffix_writes_to_new_path_when_base_exists(
        self, settings: Settings, vault: Path
    ) -> None:
        target_dir = settings.content.base_path / "DataCamp" / "Intro_To_Pandas" / "flashcards"
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "joins-flashcards.json").write_text("OLD")
        result = run_job("gen-5", _request(on_existing="suffix"), settings)
        # Original preserved; new file at -1 suffix.
        assert (target_dir / "joins-flashcards.json").read_text() == "OLD"
        assert (target_dir / "joins-1-flashcards.json").is_file()
        assert result.written == 1

    def test_merge_dedupes_with_existing_deck(self, settings: Settings, vault: Path) -> None:
        # Pre-seed an existing deck at the target path.
        target_dir = settings.content.base_path / "DataCamp" / "Intro_To_Pandas" / "flashcards"
        target_dir.mkdir(parents=True, exist_ok=True)
        existing = FlashcardDeck(
            title="Joins",
            cards=[{"front": "old card", "back": "old answer"}],  # type: ignore[list-item]
        )
        existing.write_json(target_dir, "joins")

        result = run_job("gen-6", _request(on_existing="merge"), settings)
        assert result.written == 1
        merged = FlashcardDeck.model_validate(
            json.loads((target_dir / "joins-flashcards.json").read_text())
        )
        # Three generated cards plus the existing card are retained.
        assert len(merged.cards) == 4


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    def test_scope_resolution_failure_propagates(self, settings: Settings) -> None:
        from studyloop.content.scope import ScopeResolutionError

        request = JobRequest(
            publisher=_PUBLISHER,
            course=_COURSE,
            scope=ScopeRequest(
                kind="section", publisher=_PUBLISHER, course=_COURSE, section="missing"
            ),
            kinds=("flashcards",),
        )
        with pytest.raises(ScopeResolutionError):
            run_job("gen-7", request, settings)

    def test_run_job_does_not_release_caller_owned_singleton(self, settings: Settings) -> None:
        from studyloop.content.scope import ScopeResolutionError

        # The HTTP background task owns active_gen.release() now. The sync
        # orchestrator may also be reused by future CLI code, so it must not
        # clear caller-owned singleton state from a fresh event loop.
        run_async(active_gen.acquire("gen-prior", request=None))
        try:
            with pytest.raises(ScopeResolutionError):
                run_job(
                    "gen-8",
                    JobRequest(
                        publisher=_PUBLISHER,
                        course=_COURSE,
                        scope=ScopeRequest(
                            kind="section",
                            publisher=_PUBLISHER,
                            course=_COURSE,
                            section="missing",
                        ),
                        kinds=("flashcards",),
                    ),
                    settings,
                )
        finally:
            current = run_async(active_gen.current())
            assert current is not None
            assert current.job_id == "gen-prior"


class TestMaybeInjectBearer:
    """_maybe_inject_bearer sets AWS_BEARER_TOKEN_BEDROCK for a bedrock run
    only when a token is stored, and always restores the prior env after."""

    def _bedrock_config(self) -> CardGeneratorConfig:
        return CardGeneratorConfig(backend="bedrock")

    def test_injects_token_for_bedrock_when_stored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from studyloop.content.job import _maybe_inject_bearer

        monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
        with (
            patch("studyloop.secrets.get_secret", return_value="tok-stored"),
            _maybe_inject_bearer(self._bedrock_config()),
        ):
            assert os.environ["AWS_BEARER_TOKEN_BEDROCK"] == "tok-stored"
        assert "AWS_BEARER_TOKEN_BEDROCK" not in os.environ

    def test_no_token_stored_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from studyloop.content.job import _maybe_inject_bearer

        monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
        with (
            patch("studyloop.secrets.get_secret", return_value=None),
            _maybe_inject_bearer(self._bedrock_config()),
        ):
            assert "AWS_BEARER_TOKEN_BEDROCK" not in os.environ

    def test_noop_for_non_bedrock_backend(self) -> None:
        from studyloop.content.job import _maybe_inject_bearer

        cfg = CardGeneratorConfig(backend="ollama")
        with patch("studyloop.secrets.get_secret") as mock_get, _maybe_inject_bearer(cfg):
            pass
        mock_get.assert_not_called()

    def test_restores_prior_env_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from studyloop.content.job import _maybe_inject_bearer

        monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "pre-existing")
        with (
            patch("studyloop.secrets.get_secret", return_value="tok-stored"),
            _maybe_inject_bearer(self._bedrock_config()),
        ):
            assert os.environ["AWS_BEARER_TOKEN_BEDROCK"] == "tok-stored"
        assert os.environ["AWS_BEARER_TOKEN_BEDROCK"] == "pre-existing"
