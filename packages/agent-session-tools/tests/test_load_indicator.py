"""Honest phase indicator for encoder loads (lane A4, council D-8/D-10).

The owner rejected fake progress: no percentage bars (E-A9). What is left is a
PHASE indicator -- which phase, elapsed time, and the LAST MEASURED load on
this machine. Three council amendments shape every test here:

* grok F7: "usually ~2.9s" from one persisted sample is a fabricated
  distribution. The wording is "last load: X s".
* kimi F05: a persisted duration goes stale across model/backend/hardware
  changes, so the record is keyed by ``(model, backend, revision)`` *and* a
  hardware fingerprint, with cold and warm stored separately.
* astra QA4: a callback that fires only at phase BOUNDARIES can stay silent
  through a 3 s blocking phase. The reporter is timer-driven, so a single slow
  phase still ticks.

Nothing here loads a real model: every load is a fake encoder injected at A2's
factory seam, and every duration is written under a per-test
``STUDYLOOP_STATE_DIR``.
"""

from __future__ import annotations

import io
import json
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_session_tools import (
    embedding_store,
    load_indicator,
    query_encoders,
    retrieval,
)
from agent_session_tools.query_encoders import LoadPhase, PhaseEvent

KEY: query_encoders.EncoderKey = ("bge-small-en-v1.5", "onnx", "rev-abc")


@pytest.fixture(autouse=True)
def _state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Durations land in a per-test state dir, never the learner's real one."""
    state = tmp_path / "state"
    monkeypatch.setenv(load_indicator.STATE_DIR_ENV, str(state))
    monkeypatch.delenv(load_indicator.INDICATOR_ENV, raising=False)
    return state


@pytest.fixture(autouse=True)
def _clean_encoder_cache() -> Iterator[None]:
    query_encoders.reset_cache()
    yield
    query_encoders.reset_cache()


def _rendered(stream: io.StringIO) -> list[str]:
    """Every non-empty line the reporter wrote, carriage returns split out."""
    raw = stream.getvalue().replace("\n", "\r")
    return [part.strip() for part in raw.split("\r") if part.strip()]


class FakeEncoder:
    """Minimal ``Encoder`` stand-in; ``delay`` blocks inside construction."""

    name = "bge-small-en-v1.5"
    dim = 384
    max_tokens = 512

    def __init__(self, model: str, *, local_files_only: bool = False, **_: object):
        self.model = model

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def encode(self, texts: list[str]) -> list[bytes]:
        return [b"\x00" * 8 for _ in texts]


# ---------------------------------------------------------------------------
# (a) phases render in order from the hook, with monotonic timestamps
# ---------------------------------------------------------------------------


class TestPhaseOrder:
    def test_events_arrive_in_order_with_monotonic_timestamps(self) -> None:
        stream = io.StringIO()
        with load_indicator.PhaseIndicator(
            KEY, stream=stream, render=True
        ) as indicator:
            for phase in (
                LoadPhase.RUNTIME_IMPORT,
                LoadPhase.WEIGHTS,
                LoadPhase.WARMUP,
                LoadPhase.READY,
            ):
                indicator.on_phase(
                    PhaseEvent(phase=phase, key=KEY, at=time.monotonic())
                )
        phases = [event.phase for event in indicator.events]
        assert phases == [
            LoadPhase.RUNTIME_IMPORT,
            LoadPhase.WEIGHTS,
            LoadPhase.WARMUP,
            LoadPhase.READY,
        ]
        stamps = [event.at for event in indicator.events]
        assert stamps == sorted(stamps)

    def test_the_real_factory_drives_the_indicator(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A2's factory is the event source -- not a hand-rolled emitter here."""
        monkeypatch.setattr(embedding_store, "SentenceTransformerEncoder", FakeEncoder)
        indicator = load_indicator.PhaseIndicator(
            ("m", "torch", "unpinned"), stream=io.StringIO(), render=False
        )
        with indicator:
            query_encoders.get_query_encoder(
                "m", backend="torch", on_phase=indicator.on_phase
            )
        assert [event.phase for event in indicator.events] == [
            LoadPhase.RUNTIME_IMPORT,
            LoadPhase.WEIGHTS,
            LoadPhase.DISABLED,
            LoadPhase.READY,
        ]

    def test_every_load_phase_has_a_label(self) -> None:
        """A new phase in A2's enum must not render as a bare enum repr."""
        assert set(load_indicator.PHASE_LABELS) == set(LoadPhase)


# ---------------------------------------------------------------------------
# (b) timer behaviour: a blocking phase still ticks; short loads say nothing
# ---------------------------------------------------------------------------


class TestTimerBehaviour:
    def test_a_single_blocking_phase_still_produces_two_updates(self) -> None:
        """astra QA4: boundary-driven reporting can stay silent for seconds."""
        stream = io.StringIO()
        with load_indicator.PhaseIndicator(
            KEY, stream=stream, render=True
        ) as indicator:
            indicator.on_phase(
                PhaseEvent(phase=LoadPhase.WEIGHTS, key=KEY, at=time.monotonic())
            )
            time.sleep(0.9)  # ONE phase, no boundary crossed
            indicator.on_phase(
                PhaseEvent(phase=LoadPhase.READY, key=KEY, at=time.monotonic())
            )
        lines = _rendered(stream)
        weights_lines = [line for line in lines if "weights" in line]
        assert len(weights_lines) >= 2, lines

    def test_an_under_threshold_load_prints_nothing(self) -> None:
        stream = io.StringIO()
        with load_indicator.PhaseIndicator(
            KEY, stream=stream, render=True
        ) as indicator:
            indicator.on_phase(
                PhaseEvent(phase=LoadPhase.WEIGHTS, key=KEY, at=time.monotonic())
            )
            indicator.on_phase(
                PhaseEvent(phase=LoadPhase.READY, key=KEY, at=time.monotonic())
            )
        assert stream.getvalue() == ""

    def test_stdout_is_byte_identical_with_and_without_the_indicator(self) -> None:
        """A JSON consumer reads stdout; the indicator must never appear there."""

        def run(*, indicate: bool) -> tuple[bytes, str]:
            out = io.StringIO()
            err = io.StringIO()
            real_stdout = sys.stdout
            sys.stdout = out
            try:
                indicator = load_indicator.PhaseIndicator(
                    KEY, stream=err, render=indicate, first_render=0.05, tick=0.05
                )
                with indicator:
                    indicator.on_phase(
                        PhaseEvent(
                            phase=LoadPhase.WEIGHTS, key=KEY, at=time.monotonic()
                        )
                    )
                    time.sleep(0.2)
                    print(json.dumps({"rows": [], "retrieval_status": {}}))
                    indicator.on_phase(
                        PhaseEvent(phase=LoadPhase.READY, key=KEY, at=time.monotonic())
                    )
            finally:
                sys.stdout = real_stdout
            return out.getvalue().encode(), err.getvalue()

        quiet_stdout, quiet_stderr = run(indicate=False)
        loud_stdout, loud_stderr = run(indicate=True)
        assert quiet_stdout == loud_stdout
        assert quiet_stderr == ""
        assert loud_stderr != ""

    def test_a_non_tty_stream_suppresses_rendering_by_default(self) -> None:
        stream = io.StringIO()  # StringIO has no isatty() truth
        indicator = load_indicator.PhaseIndicator(KEY, stream=stream)
        assert indicator.enabled is False

    def test_the_env_var_forces_rendering_on_a_non_tty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(load_indicator.INDICATOR_ENV, "1")
        assert load_indicator.PhaseIndicator(KEY, stream=io.StringIO()).enabled is True

    def test_the_env_var_can_force_rendering_off_on_a_tty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class Tty(io.StringIO):
            def isatty(self) -> bool:
                return True

        assert load_indicator.PhaseIndicator(KEY, stream=Tty()).enabled is True
        monkeypatch.setenv(load_indicator.INDICATOR_ENV, "0")
        assert load_indicator.PhaseIndicator(KEY, stream=Tty()).enabled is False


# ---------------------------------------------------------------------------
# (c) persistence: keyed, cold and warm apart, stale keys fall back
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_a_completed_load_lands_under_the_state_dir(self, _state_dir: Path) -> None:
        indicator = load_indicator.PhaseIndicator(KEY, stream=io.StringIO())
        with indicator:
            indicator.on_phase(
                PhaseEvent(phase=LoadPhase.WEIGHTS, key=KEY, at=time.monotonic())
            )
            indicator.on_phase(
                PhaseEvent(phase=LoadPhase.READY, key=KEY, at=time.monotonic())
            )
        path = load_indicator.durations_path()
        assert path.parent == _state_dir
        stored = json.loads(path.read_text(encoding="utf-8"))
        record_id = load_indicator.record_id(KEY)
        assert record_id in stored["loads"]
        assert load_indicator.KIND_COLD in stored["loads"][record_id]

    def test_the_next_render_says_last_load(self) -> None:
        # Recorded long enough ago that the next load is cold too, so the cold
        # number is the one that applies.
        load_indicator.record_load(
            KEY,
            2.9,
            kind=load_indicator.KIND_COLD,
            now=time.time() - load_indicator.WARM_WINDOW_SECONDS - 1,
        )
        stream = io.StringIO()
        indicator = load_indicator.PhaseIndicator(
            KEY, stream=stream, render=True, first_render=0.05
        )
        with indicator:
            indicator.on_phase(
                PhaseEvent(phase=LoadPhase.WEIGHTS, key=KEY, at=time.monotonic())
            )
            time.sleep(0.15)
            indicator.on_phase(
                PhaseEvent(phase=LoadPhase.READY, key=KEY, at=time.monotonic())
            )
        assert any("last load: 2.9s" in line for line in _rendered(stream))

    def test_only_the_other_kind_on_file_names_that_kind(self) -> None:
        """A cold number must not be passed off as this warm load's own."""
        load_indicator.record_load(KEY, 2.9, kind=load_indicator.KIND_COLD)
        assert load_indicator.classify_load(KEY) == load_indicator.KIND_WARM
        assert load_indicator.last_load_phrase(KEY) == "last cold load: 2.9s"

    def test_never_the_word_usually(self) -> None:
        """grok F7: one sample is not a distribution."""
        load_indicator.record_load(KEY, 2.9, kind=load_indicator.KIND_COLD)
        assert "usually" not in load_indicator.last_load_phrase(KEY).lower()

    def test_a_changed_backend_falls_back_to_first_run_wording(self) -> None:
        load_indicator.record_load(KEY, 2.9, kind=load_indicator.KIND_COLD)
        other_backend = (KEY[0], "torch", KEY[2])
        assert (
            load_indicator.last_load_phrase(other_backend)
            == load_indicator.FIRST_RUN_PHRASE
        )

    def test_a_changed_hardware_fingerprint_falls_back_to_first_run_wording(
        self,
    ) -> None:
        load_indicator.record_load(KEY, 2.9, kind=load_indicator.KIND_COLD)
        assert (
            load_indicator.last_load_phrase(KEY, fingerprint="some-other-machine")
            == load_indicator.FIRST_RUN_PHRASE
        )

    def test_cold_and_warm_are_recorded_separately(self) -> None:
        load_indicator.record_load(KEY, 2.9, kind=load_indicator.KIND_COLD)
        load_indicator.record_load(KEY, 0.4, kind=load_indicator.KIND_WARM)
        cold = load_indicator.last_load(KEY, load_indicator.KIND_COLD)
        warm = load_indicator.last_load(KEY, load_indicator.KIND_WARM)
        assert cold is not None and warm is not None
        assert (cold.seconds, warm.seconds) == (2.9, 0.4)

    def test_a_first_ever_load_classifies_as_cold(self) -> None:
        assert load_indicator.classify_load(KEY) == load_indicator.KIND_COLD

    def test_a_load_soon_after_another_classifies_as_warm(self) -> None:
        now = 1_000_000.0
        load_indicator.record_load(KEY, 2.9, kind=load_indicator.KIND_COLD, now=now - 5)
        assert load_indicator.classify_load(KEY, now=now) == load_indicator.KIND_WARM

    def test_a_load_long_after_the_last_one_classifies_as_cold_again(self) -> None:
        now = 1_000_000.0
        load_indicator.record_load(
            KEY,
            2.9,
            kind=load_indicator.KIND_COLD,
            now=now - load_indicator.WARM_WINDOW_SECONDS - 1,
        )
        assert load_indicator.classify_load(KEY, now=now) == load_indicator.KIND_COLD

    def test_an_unreadable_record_file_never_breaks_a_load(
        self, _state_dir: Path
    ) -> None:
        _state_dir.mkdir(parents=True, exist_ok=True)
        load_indicator.durations_path().write_text("{not json", encoding="utf-8")
        assert load_indicator.last_load(KEY, load_indicator.KIND_COLD) is None
        assert load_indicator.last_load_phrase(KEY) == load_indicator.FIRST_RUN_PHRASE

    def test_the_state_dir_honours_the_env_var_lazily(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        moved = tmp_path / "moved"
        monkeypatch.setenv(load_indicator.STATE_DIR_ENV, str(moved))
        assert load_indicator.state_dir() == moved


# ---------------------------------------------------------------------------
# (d) never a percent
# ---------------------------------------------------------------------------


class TestNeverAPercent:
    @pytest.mark.parametrize("phase", list(LoadPhase))
    def test_no_rendered_line_contains_a_percent_sign(self, phase: LoadPhase) -> None:
        load_indicator.record_load(KEY, 2.9, kind=load_indicator.KIND_COLD)
        indicator = load_indicator.PhaseIndicator(
            KEY, stream=io.StringIO(), render=True
        )
        with indicator:
            indicator.on_phase(
                PhaseEvent(phase=phase, key=KEY, at=time.monotonic(), detail="d")
            )
            assert "%" not in indicator.line()

    def test_the_first_run_phrase_has_no_percent_and_no_prediction(self) -> None:
        assert "%" not in load_indicator.FIRST_RUN_PHRASE
        assert "may take" in load_indicator.FIRST_RUN_PHRASE


# ---------------------------------------------------------------------------
# (e) failure renders honestly and stops the reporter
# ---------------------------------------------------------------------------


class TestFailureAndDisabled:
    def test_failure_renders_the_reason_and_stops_ticking(self) -> None:
        stream = io.StringIO()
        indicator = load_indicator.PhaseIndicator(
            KEY, stream=stream, render=True, first_render=0.05, tick=0.05
        )
        with indicator:
            indicator.on_phase(
                PhaseEvent(phase=LoadPhase.WEIGHTS, key=KEY, at=time.monotonic())
            )
            time.sleep(0.15)
            indicator.on_phase(
                PhaseEvent(
                    phase=LoadPhase.FAILED,
                    key=KEY,
                    at=time.monotonic(),
                    detail="FileNotFoundError: no artefact",
                )
            )
            after_failure = stream.getvalue()
            time.sleep(0.2)
            assert stream.getvalue() == after_failure, "reporter kept ticking"
        lines = _rendered(stream)
        assert any("failed" in line for line in lines)
        assert any("FileNotFoundError: no artefact" in line for line in lines)

    def test_a_failed_load_is_not_recorded_as_a_duration(self) -> None:
        indicator = load_indicator.PhaseIndicator(KEY, stream=io.StringIO())
        with indicator:
            indicator.on_phase(
                PhaseEvent(
                    phase=LoadPhase.FAILED, key=KEY, at=time.monotonic(), detail="boom"
                )
            )
        assert load_indicator.last_load(KEY, load_indicator.KIND_COLD) is None

    def test_a_disabled_phase_renders_honestly(self) -> None:
        """DISABLED means "warm-up was not requested", NOT "the semantic
        layer is off" -- ``ready`` still follows it. The rendered label must
        not read like the layer is switched off (minor finding, fix round 1)."""
        indicator = load_indicator.PhaseIndicator(
            KEY, stream=io.StringIO(), render=True
        )
        with indicator:
            indicator.on_phase(
                PhaseEvent(
                    phase=LoadPhase.DISABLED,
                    key=KEY,
                    at=time.monotonic(),
                    detail="warmup not requested",
                )
            )
            line = indicator.line()
            assert load_indicator.PHASE_LABELS[LoadPhase.DISABLED] in line
            assert "disabled" not in line

    def test_a_cached_encoder_emits_nothing_and_records_nothing(self) -> None:
        stream = io.StringIO()
        indicator = load_indicator.PhaseIndicator(KEY, stream=stream, render=True)
        with indicator:
            pass  # the factory returned a cached encoder: no phases at all
        assert stream.getvalue() == ""
        assert load_indicator.last_load(KEY, load_indicator.KIND_COLD) is None

    def test_a_pending_tick_write_never_lands_after_the_closing_line(self) -> None:
        """Regression for nit finding #7 (fix round 1).

        ``on_phase`` used to flip ``_finished`` only AFTER writing the
        closing line, and the tick writer's own ``_finished`` guard ran
        BEFORE it took the lock -- never re-checked once inside it. So a
        ticker thread that had already read ``_finished`` as False (it
        decided to render before the terminal event arrived) but had not
        yet reached its write -- e.g. parked waiting for the lock the
        closing write also needs -- could still append one more stale
        render after ``ready``/``failed`` once that lock freed up.

        Reproduced deterministically, without relying on real scheduling
        luck: a gate on the indicator's lock holds a "ticker" thread's
        acquisition open until AFTER ``on_phase(READY)`` -- including its
        own closing write -- has fully returned on this (main) thread. The
        ticker thread's outer check therefore ran (and passed) before the
        close; only its write is delayed past it.
        """
        stream = io.StringIO()
        indicator = load_indicator.PhaseIndicator(KEY, stream=stream, render=False)
        indicator._started_at = time.monotonic()
        indicator.on_phase(
            PhaseEvent(phase=LoadPhase.WEIGHTS, key=KEY, at=time.monotonic())
        )
        stale_render = indicator.line()
        indicator._write(
            stale_render
        )  # a legitimate earlier tick: `_wrote` is now True

        gate = threading.Event()
        real_lock = indicator._lock
        racer_holder: list[threading.Thread] = []

        class _GatedLock:
            """Delays ``acquire()`` from the racer thread only, until ``gate``."""

            def acquire(self, *args: object, **kwargs: object) -> bool:
                if threading.current_thread() is racer_holder[0]:
                    gate.wait(timeout=1)
                return real_lock.acquire(*args, **kwargs)  # type: ignore[arg-type]

            def release(self) -> None:
                real_lock.release()

            def __enter__(self) -> None:
                self.acquire()

            def __exit__(self, *_exc: object) -> None:
                self.release()

        indicator._lock = _GatedLock()  # type: ignore[assignment]

        racer = threading.Thread(target=indicator._write, args=(stale_render,))
        racer_holder.append(racer)
        racer.start()
        # The racer's outer guard has already run (``_finished`` was False);
        # it is now parked on the gate, exactly like a real ticker thread
        # that decided to render before the terminal event arrived.

        indicator.on_phase(
            PhaseEvent(phase=LoadPhase.READY, key=KEY, at=time.monotonic())
        )
        # The close, including its own write, has now fully happened on this
        # thread. Only now does the parked "ticker" get to run.
        gate.set()
        racer.join(timeout=1)

        lines = _rendered(stream)
        assert lines, "the closing line was never written"
        assert lines[-1].startswith("semantic model"), lines


# ---------------------------------------------------------------------------
# Wiring: the query side (A2's factory via retrieval) and the corpus side
# ---------------------------------------------------------------------------


class TestQuerySideWiring:
    def test_retrieval_encoder_records_a_load_duration(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(embedding_store, "SentenceTransformerEncoder", FakeEncoder)
        retrieval._encoder("bge-small-en-v1.5")
        key = query_encoders.cache_key("bge-small-en-v1.5", "torch")
        assert load_indicator.last_load(key, load_indicator.KIND_COLD) is not None

    def test_a_failing_query_encoder_load_still_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class Boom:
            def __init__(self, *args: object, **kwargs: object) -> None:
                raise RuntimeError("kaboom")

        monkeypatch.setattr(embedding_store, "SentenceTransformerEncoder", Boom)
        with pytest.raises(RuntimeError, match="kaboom"):
            retrieval._encoder("bge-small-en-v1.5")

    def test_a_warm_cache_hit_skips_the_indicator_entirely(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nit finding #7 (fix round 1): ``query_encoders.is_cached`` already
        exists precisely so a caller can tell a warm hit from a real load --
        every search on a long-lived mcp/web process was paying for a
        ``PhaseIndicator`` construction and, on a TTY, a spawned+joined
        ticker thread even though a cached encoder emits no phases and
        renders nothing."""
        monkeypatch.setattr(embedding_store, "SentenceTransformerEncoder", FakeEncoder)
        retrieval._encoder("bge-small-en-v1.5")  # first call: real cold load
        assert query_encoders.is_cached("bge-small-en-v1.5", "torch")

        def _explode(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("a cached load must not construct an indicator")

        monkeypatch.setattr(load_indicator, "PhaseIndicator", _explode)
        # A warm hit must not even try to build the indicator.
        retrieval._encoder("bge-small-en-v1.5")

    def test_the_indicator_never_resolves_the_key_itself(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The factory owns key resolution AND its failure message.

        Resolving ``cache_key()`` in ``_encoder`` to build the indicator would
        raise the indicator's copy of "no pinned ONNX artefact" before the
        factory ever ran, replacing whatever the factory would have said.
        """
        from agent_session_tools import config_loader

        monkeypatch.setattr(
            config_loader, "get_semantic_config", lambda: {"query_encoder": "onnx"}
        )

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("factory boom")

        monkeypatch.setattr(query_encoders, "get_query_encoder", _boom)
        with pytest.raises(RuntimeError, match="factory boom"):
            retrieval._encoder("model-with-no-pinned-artefact")

    def test_the_indicator_adopts_the_key_from_the_first_event(self) -> None:
        indicator = load_indicator.PhaseIndicator(stream=io.StringIO())
        assert indicator.key is None
        with indicator:
            indicator.on_phase(
                PhaseEvent(phase=LoadPhase.WEIGHTS, key=KEY, at=time.monotonic())
            )
        assert indicator.key == KEY

    def test_the_background_warm_records_its_duration_without_rendering(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = tmp_path / "warm-config.yaml"
        config.write_text(
            "semantic_search:\n  hybrid: true\n  model: bge-small-en-v1.5\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
        monkeypatch.delenv(retrieval.MODE_ENV, raising=False)
        monkeypatch.setattr(embedding_store, "SentenceTransformerEncoder", FakeEncoder)
        retrieval.warm_query_encoder(surface=retrieval.SURFACE_MCP, blocking=True)
        assert retrieval.encoder_warm_status().state == retrieval.WarmState.WARM
        key = query_encoders.cache_key("bge-small-en-v1.5", "torch")
        assert load_indicator.last_load(key, load_indicator.KIND_COLD) is not None


class TestCorpusSideWiring:
    def test_the_corpus_encoder_emits_the_same_phase_enum(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """D-8: one phase enum shared by both encoders."""
        monkeypatch.setattr(embedding_store, "SentenceTransformerEncoder", FakeEncoder)
        monkeypatch.setattr(
            embedding_store,
            "availability",
            lambda model: embedding_store.Availability(
                ready=True, model_ok=True, extension_ok=True, reason=""
            ),
        )
        seen: list[PhaseEvent] = []
        embedding_store._load_encoder("bge-small-en-v1.5", on_phase=seen.append)
        assert [event.phase for event in seen] == [
            LoadPhase.RUNTIME_IMPORT,
            LoadPhase.WEIGHTS,
            LoadPhase.READY,
        ]

    def test_a_corpus_load_failure_emits_failed_and_propagates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class Boom:
            def __init__(self, *args: object, **kwargs: object) -> None:
                raise RuntimeError("kaboom")

        monkeypatch.setattr(embedding_store, "SentenceTransformerEncoder", Boom)
        monkeypatch.setattr(
            embedding_store,
            "availability",
            lambda model: embedding_store.Availability(
                ready=True, model_ok=True, extension_ok=True, reason=""
            ),
        )
        seen: list[PhaseEvent] = []
        with pytest.raises(RuntimeError, match="kaboom"):
            embedding_store._load_encoder("bge-small-en-v1.5", on_phase=seen.append)
        assert seen[-1].phase is LoadPhase.FAILED


class TestConcurrency:
    def test_the_reporter_is_safe_when_phases_arrive_from_another_thread(self) -> None:
        stream = io.StringIO()
        indicator = load_indicator.PhaseIndicator(
            KEY, stream=stream, render=True, first_render=0.05, tick=0.05
        )
        with indicator:

            def emit() -> None:
                indicator.on_phase(
                    PhaseEvent(phase=LoadPhase.WEIGHTS, key=KEY, at=time.monotonic())
                )
                time.sleep(0.2)
                indicator.on_phase(
                    PhaseEvent(phase=LoadPhase.READY, key=KEY, at=time.monotonic())
                )

            thread = threading.Thread(target=emit)
            thread.start()
            thread.join(timeout=5)
        assert [event.phase for event in indicator.events][-1] is LoadPhase.READY
        assert _rendered(stream)


class TestNoImportTimeCost:
    """Council D-10: the machine-independent half of "the load did not go silent".

    A wall-clock assertion in CI measures the runner, not the product, so the
    regression that IS worth gating is the lazy-import contract -- and this
    module is a new way to break it, because it imports ``query_encoders`` at
    module scope. A CLI entry point that reaches for the indicator must not pay
    for a runtime it may never load.
    """

    def test_importing_the_indicator_pulls_no_ml_runtime(self) -> None:
        import subprocess

        script = (
            "import sys; "
            "import agent_session_tools.load_indicator; "
            "assert 'torch' not in sys.modules, 'torch imported at import time'; "
            "assert 'onnxruntime' not in sys.modules, 'onnxruntime imported at import time'; "
            "assert 'sentence_transformers' not in sys.modules, "
            "'sentence_transformers imported at import time'; "
            "print('OK')"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.strip() == "OK"
