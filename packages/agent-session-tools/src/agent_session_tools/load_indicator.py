"""An honest phase indicator for encoder loads (lane A4, council D-8/D-10).

WHY THIS EXISTS. Loading the embedding model costs seconds (2.87 s measured for
the torch/sentence-transformers query path), and until now it cost them
silently: a learner typed a search and waited with no signal that anything was
happening. The obvious fix -- a progress bar -- is the one the owner explicitly
rejected (E-A9), and rightly: nothing in the load reports its own completion
fraction, so any percentage would be invented. A bar that fills at a made-up
rate teaches the learner to distrust the whole surface.

What is honest is a PHASE indicator:

* WHICH phase the load is in -- the enum lives in :mod:`query_encoders`
  (``runtime_import | weights | warmup | ready | failed | disabled``) and both
  the query-side factory and the corpus-side loader emit it, so there is one
  vocabulary rather than two (council D-8).
* HOW LONG it has been running -- elapsed, ticking, measured.
* WHAT THE LAST LOAD ON THIS MACHINE COST -- ``last load: 2.9s``, never
  "usually ~2.9s". One persisted sample is not a distribution (grok F7), and a
  sample taken on different weights, a different backend or different hardware
  is not even about the current load (kimi F05) -- hence the record is keyed by
  ``(model, backend, revision)`` plus a hardware fingerprint, and a key with no
  record falls back to first-run wording instead of borrowing someone else's
  number.

WHY THE REPORTER IS TIMER-DRIVEN. A listener that renders only when a phase
event arrives can stay silent for the entire duration of the slow phase --
``weights`` is a single blocking call, so a boundary-driven reporter prints
"weights" once and then looks frozen for three seconds (astra QA4). The
reporter therefore owns a ticker thread: it wakes at ``first_render`` (300 ms,
so a fast load stays completely silent) and re-renders on a fixed cadence with
the elapsed clock ticking, until a terminal phase or the caller cancels it.

WHERE IT WRITES. stderr, only, always. ``session-query --json`` consumers and
the MCP protocol both own stdout; a progress line there is corruption, not
noise. Rendering is suppressed when stderr is not a TTY unless
``STUDYLOOP_LOAD_INDICATOR=1`` forces it -- that suppression is a COURTESY for
pipes and logs, so silence must never be read as "nothing is loading". The
duration RECORD is written either way: it is also the load-duration receipt
(council D-10), and CI checks the machine-independent lazy-import contract
rather than wall clocks.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TYPE_CHECKING

from .query_encoders import LoadPhase, PhaseEvent

if TYPE_CHECKING:
    from .query_encoders import EncoderKey

INDICATOR_ENV = "STUDYLOOP_LOAD_INDICATOR"
"""``1`` forces rendering even when stderr is a pipe; ``0`` forces it off."""

STATE_DIR_ENV = "STUDYLOOP_STATE_DIR"
"""Same variable ``studyloop.settings`` reads (E-B10); resolved lazily here too."""

DURATIONS_RELPATH = "encoder-load-durations.json"

FIRST_RENDER_SECONDS = 0.3
"""Nothing is printed before this: a fast load should stay silent."""

TICK_SECONDS = 0.25
"""Re-render cadence while a single phase blocks."""

WARM_WINDOW_SECONDS = 900.0
"""A load within this long of the previous one counts as warm (see :func:`classify_load`)."""

KIND_COLD = "cold"
KIND_WARM = "warm"
KINDS = (KIND_COLD, KIND_WARM)

RECORD_VERSION = 1

FIRST_RUN_PHRASE = "first load on this machine may take a few seconds"
"""Deliberately not a number: there is nothing measured to report yet."""

PHASE_LABELS: dict[LoadPhase, str] = {
    LoadPhase.RUNTIME_IMPORT: "importing runtime",
    LoadPhase.WEIGHTS: "weights",
    LoadPhase.WARMUP: "warm-up",
    LoadPhase.READY: "ready",
    LoadPhase.FAILED: "failed",
    LoadPhase.DISABLED: "disabled",
}

_TERMINAL_PHASES = (LoadPhase.READY, LoadPhase.FAILED)


# ---------------------------------------------------------------------------
# Persisted last-load durations
# ---------------------------------------------------------------------------


def state_dir() -> Path:
    """Where durations are persisted, honouring ``STUDYLOOP_STATE_DIR``.

    Resolved at call time, never bound at import: a test (or a subprocess it
    spawns) redirects writable state with the environment variable, and
    ``settings.py``'s import-time ``CONFIG_DIR`` is exactly the trap that
    causes (council D-11). ``Path.home()`` is read here for the same reason.
    """
    if env_dir := os.environ.get(STATE_DIR_ENV):
        return Path(env_dir).expanduser()
    return Path.home() / ".local" / "share" / "studyloop"


def durations_path() -> Path:
    return state_dir() / DURATIONS_RELPATH


def hardware_fingerprint() -> str:
    """A coarse machine identity, so a duration measured elsewhere is not reused.

    Coarse on purpose: OS, architecture and core count are what change the
    load cost by an order of magnitude (an x86 CI box versus an arm64 laptop).
    It is not a unique machine id, and nothing here needs one.
    """
    return f"{platform.system()}-{platform.machine()}-cpu{os.cpu_count() or 0}"


@dataclass(frozen=True, slots=True)
class LoadRecord:
    """One measured load: how long it took, and when."""

    kind: str
    seconds: float
    at: float


def record_id(key: EncoderKey, fingerprint: str | None = None) -> str:
    """The record key: A2's ``(model, backend, revision)`` plus the machine.

    Both halves matter (kimi F05). The revision is what makes a future int8
    artefact a different record from today's fp32 one -- a new quantisation
    MUST get its own registry entry rather than reusing this key, or it would
    silently inherit fp32's timings.
    """
    return "|".join([*key, fingerprint or hardware_fingerprint()])


def read_records() -> dict[str, dict[str, LoadRecord]]:
    """Every persisted duration, or ``{}`` when the file is missing or corrupt.

    A corrupt or unreadable file is never an error: this data only decorates a
    progress line, and failing a search over it would be absurd.
    """
    try:
        raw = json.loads(durations_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict) or raw.get("version") != RECORD_VERSION:
        return {}
    loads = raw.get("loads")
    if not isinstance(loads, dict):
        return {}
    parsed: dict[str, dict[str, LoadRecord]] = {}
    for ident, kinds in loads.items():
        if not isinstance(kinds, dict):
            continue
        for kind, payload in kinds.items():
            if kind not in KINDS or not isinstance(payload, dict):
                continue
            try:
                record = LoadRecord(
                    kind=kind,
                    seconds=float(payload["seconds"]),
                    at=float(payload["at"]),
                )
            except (KeyError, TypeError, ValueError):
                continue
            parsed.setdefault(ident, {})[kind] = record
    return parsed


def last_load(
    key: EncoderKey, kind: str, *, fingerprint: str | None = None
) -> LoadRecord | None:
    """The last measured load of this ``kind`` for this key on this machine."""
    return read_records().get(record_id(key, fingerprint), {}).get(kind)


def classify_load(
    key: EncoderKey, *, fingerprint: str | None = None, now: float | None = None
) -> str:
    """Whether a load starting now is :data:`KIND_COLD` or :data:`KIND_WARM`.

    The distinction that matters to a waiting learner is whether the OS page
    cache and the Hugging Face cache are hot, and the only signal available
    without measuring is recency: a load shortly after another load of the same
    artefact is warm, one long after (or the first ever) is cold. That is a
    documented heuristic for CHOOSING WHICH MEASURED NUMBER TO SHOW -- never a
    prediction, and never presented as one.
    """
    records = read_records().get(record_id(key, fingerprint), {})
    if not records:
        return KIND_COLD
    latest = max(record.at for record in records.values())
    reference = time.time() if now is None else now
    return KIND_WARM if reference - latest <= WARM_WINDOW_SECONDS else KIND_COLD


def record_load(
    key: EncoderKey,
    seconds: float,
    *,
    kind: str,
    fingerprint: str | None = None,
    now: float | None = None,
) -> None:
    """Persist one measured load, replacing the previous one of the same kind.

    Doubles as the load-duration receipt (council D-10): the acceptance tier
    regression-checks it, CI does not (a wall clock is machine-dependent).
    Written atomically, and never allowed to raise into a load path.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown load kind {kind!r}; expected one of {KINDS}")
    ident = record_id(key, fingerprint)
    records = read_records()
    entry = dict(records.get(ident, {}))
    entry[kind] = LoadRecord(
        kind=kind, seconds=float(seconds), at=time.time() if now is None else now
    )
    records[ident] = entry
    payload = {
        "version": RECORD_VERSION,
        "loads": {
            stored_ident: {
                stored_kind: {"seconds": record.seconds, "at": record.at}
                for stored_kind, record in stored.items()
            }
            for stored_ident, stored in records.items()
        },
    }
    path = durations_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        return  # a progress note is never worth failing a load over


def last_load_phrase(
    key: EncoderKey,
    kind: str | None = None,
    *,
    fingerprint: str | None = None,
) -> str:
    """``last load: 2.9s``, or first-run wording when nothing was measured.

    Never "usually" and never an average (grok F7): this is one measurement,
    described as one measurement.

    When the only measurement on file is of the OTHER kind -- a cold number
    while this load looks warm, or the reverse -- the phrase names that kind
    (``last cold load: 2.9s``) rather than either quietly passing it off as
    comparable or claiming a first run that already happened.
    """
    resolved_kind = (
        classify_load(key, fingerprint=fingerprint) if kind is None else kind
    )
    record = last_load(key, resolved_kind, fingerprint=fingerprint)
    if record is not None:
        return f"last load: {record.seconds:.1f}s"
    other = KIND_WARM if resolved_kind == KIND_COLD else KIND_COLD
    fallback = last_load(key, other, fingerprint=fingerprint)
    if fallback is not None:
        return f"last {other} load: {fallback.seconds:.1f}s"
    return FIRST_RUN_PHRASE


# ---------------------------------------------------------------------------
# The timer-driven reporter
# ---------------------------------------------------------------------------


class PhaseIndicator:
    """A timer-driven stderr reporter for one encoder load.

    Use it as a context manager around the construction call and hand
    :meth:`on_phase` to the factory's ``on_phase`` hook::

        with PhaseIndicator() as indicator:
            encoder = get_query_encoder(model, on_phase=indicator.on_phase)

    ``key`` is normally left unset: every :class:`PhaseEvent` carries the
    ``(model, backend, revision)`` key, so the indicator adopts it from the
    first event. That matters beyond convenience -- resolving the key here
    instead would duplicate the factory's own resolution AND its failure modes,
    so an unpinned-artefact request would raise out of the *indicator* and
    replace the factory's explanatory error with a worse one. Callers with no
    hook of their own (the corpus-side loader) pass the key explicitly.

    A load that never emits a phase (the factory returned a cached encoder)
    prints nothing and records nothing. A load that finishes under
    ``first_render`` also prints nothing -- but its duration is still recorded,
    because the record is a receipt, not a UI detail.
    """

    def __init__(
        self,
        key: EncoderKey | None = None,
        *,
        stream: IO[str] | None = None,
        render: bool | None = None,
        first_render: float = FIRST_RENDER_SECONDS,
        tick: float = TICK_SECONDS,
        fingerprint: str | None = None,
        record: bool = True,
    ) -> None:
        self.key = key
        self.events: list[PhaseEvent] = []
        # stderr by default, and stderr only: stdout belongs to JSON consumers
        # and to the MCP protocol.
        self._stream: IO[str] | None = sys.stderr if stream is None else stream
        self._first_render = first_render
        self._tick = tick
        self._fingerprint = fingerprint
        self._record = record
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._phase: LoadPhase | None = None
        self._detail = ""
        self._started_at: float | None = None
        self._finished = False
        self._wrote = False
        self._width = 0
        self.enabled = _rendering_enabled(render, self._stream)
        self.kind = KIND_COLD
        self._phrase = FIRST_RUN_PHRASE
        if key is not None:
            self._adopt(key)

    def _adopt(self, key: EncoderKey) -> None:
        """Fix the key, and with it WHICH measured number this render may cite.

        Read once, at the start of the load: whether the relevant sample is the
        cold or the warm one depends on how long ago the last load was, and that
        answer must not change halfway through this load.
        """
        self.key = key
        self.kind = classify_load(key, fingerprint=self._fingerprint)
        self._phrase = last_load_phrase(key, self.kind, fingerprint=self._fingerprint)

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> PhaseIndicator:
        self._started_at = time.monotonic()
        if self.enabled:
            self._thread = threading.Thread(
                target=self._tick_loop, name="encoder-load-indicator", daemon=True
            )
            self._thread.start()
        return self

    def close(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=1)

    def __enter__(self) -> PhaseIndicator:
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.close()

    # -- the hook A2's factory calls --------------------------------------

    def on_phase(self, event: PhaseEvent) -> None:
        """A :data:`query_encoders.PhaseListener`. Safe from any thread."""
        with self._lock:
            first = not self.events
            self.events.append(event)
            self._phase = event.phase
            self._detail = event.detail
            terminal = event.phase in _TERMINAL_PHASES
        if first and self.key is None:
            self._adopt(event.key)
        if not terminal:
            return
        self._stop.set()
        if event.phase is LoadPhase.READY and self._record and self.key is not None:
            record_load(
                self.key,
                self.elapsed(),
                kind=self.kind,
                fingerprint=self._fingerprint,
            )
        if self._wrote:  # only close a line we actually opened
            self._write(self.line(), final=True)
        self._finished = True

    def phase(self, phase: LoadPhase, detail: str = "") -> None:
        """Emit a phase for a loader that has no hook of its own (corpus side).

        Only meaningful with an explicit ``key``: there is no event to adopt one
        from.
        """
        if self.key is None:
            raise ValueError(
                "PhaseIndicator.phase() needs an explicit key; only events from "
                "a factory hook carry one"
            )
        self.on_phase(
            PhaseEvent(phase=phase, key=self.key, at=time.monotonic(), detail=detail)
        )

    # -- rendering ---------------------------------------------------------

    def elapsed(self) -> float:
        if self._started_at is None:
            return 0.0
        return time.monotonic() - self._started_at

    def line(self) -> str:
        """The current one-line render. No percentage, ever."""
        phase = self._phase
        if phase is None or self.key is None:
            return ""
        model = self.key[0]
        label = PHASE_LABELS.get(phase, phase.value)
        seconds = self.elapsed()
        if phase is LoadPhase.FAILED:
            reason = f" -- {self._detail}" if self._detail else ""
            return f"semantic model ({model}): failed after {seconds:.1f}s{reason}"
        if phase is LoadPhase.READY:
            return f"semantic model ({model}): ready in {seconds:.1f}s"
        return (
            f"loading semantic model ({model}): {label} ... "
            f"{seconds:.1f}s ({self._phrase})"
        )

    def _tick_loop(self) -> None:
        if self._stop.wait(self._first_render):
            return  # finished before the threshold: stay silent
        while True:
            self._write(self.line())
            if self._stop.wait(self._tick):
                return

    def _write(self, line: str, *, final: bool = False) -> None:
        if not line or self._stream is None or self._finished:
            return
        with self._lock:
            self._width = max(self._width, len(line))
            padded = line.ljust(self._width)
            try:
                self._stream.write(f"\r{padded}" + ("\n" if final else ""))
                self._stream.flush()
            except (OSError, ValueError):  # pragma: no cover - closed pipe
                self._stream = None
                return
            self._wrote = True


def _rendering_enabled(render: bool | None, stream: IO[str] | None) -> bool:
    """Explicit argument, else ``STUDYLOOP_LOAD_INDICATOR``, else "is it a TTY?"."""
    if render is not None:
        return render
    forced = os.environ.get(INDICATOR_ENV)
    if forced in {"0", "1"}:
        return forced == "1"
    try:
        return bool(stream is not None and stream.isatty())
    except (OSError, ValueError):  # pragma: no cover - closed stream
        return False


__all__ = [
    "DURATIONS_RELPATH",
    "FIRST_RENDER_SECONDS",
    "FIRST_RUN_PHRASE",
    "INDICATOR_ENV",
    "KINDS",
    "KIND_COLD",
    "KIND_WARM",
    "PHASE_LABELS",
    "RECORD_VERSION",
    "STATE_DIR_ENV",
    "TICK_SECONDS",
    "WARM_WINDOW_SECONDS",
    "LoadRecord",
    "PhaseIndicator",
    "classify_load",
    "durations_path",
    "hardware_fingerprint",
    "last_load",
    "last_load_phrase",
    "read_records",
    "record_id",
    "record_load",
    "state_dir",
]
