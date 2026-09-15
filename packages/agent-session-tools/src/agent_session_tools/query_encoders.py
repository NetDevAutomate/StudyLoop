"""The QUERY-side encoder construction seam (lane A2, council D-2).

``retrieval.py`` used to hard-code ``SentenceTransformerEncoder`` at the one
call site that turns a query string into a vector. That hard-coding is what
this module replaces: :func:`get_query_encoder` is the single factory every
caller (the CLI, the MCP tool, the retrieval-eval harness) asks for a query
encoder, and it is the only place that decides *which* backend answers.

Why a whole module instead of a function: three invariants have to hold
together and none of them fit as a decorator on the old one-liner.

* **Cache key is (model, backend, revision), not model alone (E-A1).** The
  old ``_ENCODERS`` dict was keyed by model name only, which was correct while
  exactly one backend existed. The moment a second backend answers the same
  model name, a bare model key silently hands a torch caller an onnx encoder
  or vice versa -- the asymmetry the parity gate exists to catch would happen
  *inside the cache* instead of at the seam.
* **Single-flight construction.** A warm (``session-maint warm`` or similar)
  and a concurrent search must not both pay the load cost; the second caller
  blocks on the first's lock and then reads the same cached instance.
* **A load-phase hook, zero cost with no listener (lane A4 will consume
  it).** ``on_phase`` is ``None`` on every call this module makes internally;
  a caller that wants progress reporting passes a callback and gets ordered,
  monotonic events, nothing else changes.

Corpus-side embedding stays exactly as it is: ``embedding_store._load_encoder``
is untouched, torch-only, and out of scope here (council QA2.2). This module
only ever answers the query side.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from .embedding_store import Encoder

BACKEND_TORCH = "torch"
BACKEND_ONNX = "onnx"
BACKENDS = (BACKEND_TORCH, BACKEND_ONNX)
BACKEND_ENV = "STUDYLOOP_QUERY_ENCODER"
"""Per-process override of the configured backend; mirrors ``retrieval.MODE_ENV``."""

# torch is not revision-pinned today (sentence-transformers loads whatever the
# HF cache holds for ``main``); this is the cache-key placeholder for that
# backend so the key shape is uniform. Only onnx has a real pinned revision.
_UNPINNED_REVISION = "unpinned"


class LoadPhase(str, Enum):
    """Where a :class:`get_query_encoder` call is, for lane A4's progress UI.

    Every construction emits, in order: ``RUNTIME_IMPORT`` (about to import the
    backend's heavy module), ``WEIGHTS`` (about to construct the encoder,
    which loads weights/session), then either ``WARMUP`` (a dummy encode ran)
    or ``DISABLED`` (warmup was not requested -- still an event, so a listener
    sees a phase for every call rather than inferring absence), then ``READY``.
    Any exception emits ``FAILED`` instead of the remaining phases and
    propagates.
    """

    RUNTIME_IMPORT = "runtime_import"
    WEIGHTS = "weights"
    WARMUP = "warmup"
    READY = "ready"
    FAILED = "failed"
    DISABLED = "disabled"


EncoderKey = tuple[str, str, str]
"""``(model, backend, revision)`` -- the cache key (E-A1)."""


@dataclass(frozen=True, slots=True)
class PhaseEvent:
    """One phase transition, timestamped with :func:`time.monotonic`."""

    phase: LoadPhase
    key: EncoderKey
    at: float
    detail: str = ""


PhaseListener = Callable[[PhaseEvent], None]


def resolve_backend(requested: str | None = None) -> str:
    """Which backend answers a query encoder request: argument, else
    ``STUDYLOOP_QUERY_ENCODER``, else ``semantic_search.query_encoder`` in the
    config, else ``torch``.

    An unknown value is a caller error, not a silent fallback -- mirrors
    ``retrieval.resolve_mode``.
    """
    if requested is None:
        requested = os.environ.get(BACKEND_ENV) or None
    if requested is None:
        try:
            from .config_loader import get_semantic_config

            requested = get_semantic_config().get("query_encoder", BACKEND_TORCH)
        except Exception:  # config unreadable: torch always works
            requested = BACKEND_TORCH
    if requested not in BACKENDS:
        raise ValueError(
            f"unknown query encoder backend {requested!r}; expected one of {BACKENDS}"
        )
    return requested


def _default_revision(model: str, backend: str) -> str:
    if backend != BACKEND_ONNX:
        return _UNPINNED_REVISION
    from .embeddings import ONNX_ARTIFACTS

    artefact = ONNX_ARTIFACTS.get(model)
    if artefact is None:
        raise ValueError(
            f"no pinned ONNX artefact for model {model!r}; add it to "
            "embeddings.ONNX_ARTIFACTS before requesting the onnx backend"
        )
    return str(artefact["revision"])


_ENCODERS: dict[EncoderKey, Encoder] = {}
_CACHE_LOCK = threading.Lock()
_KEY_LOCKS: dict[EncoderKey, threading.Lock] = {}


def _lock_for(key: EncoderKey) -> threading.Lock:
    with _CACHE_LOCK:
        lock = _KEY_LOCKS.setdefault(key, threading.Lock())
    return lock


def _emit(
    on_phase: PhaseListener | None, phase: LoadPhase, key: EncoderKey, detail: str = ""
) -> None:
    if on_phase is None:  # zero cost with no listener
        return
    on_phase(PhaseEvent(phase=phase, key=key, at=time.monotonic(), detail=detail))


def _construct(
    model: str,
    backend: str,
    revision: str,
    *,
    local_files_only: bool,
    warmup: bool,
    on_phase: PhaseListener | None,
) -> Encoder:
    key = (model, backend, revision)
    try:
        _emit(on_phase, LoadPhase.RUNTIME_IMPORT, key)
        if backend == BACKEND_ONNX:
            from .onnx_encoder import OnnxEncoder

            _emit(on_phase, LoadPhase.WEIGHTS, key)
            encoder: Encoder = OnnxEncoder(
                model, local_files_only=local_files_only, revision=revision
            )
        else:
            from .embedding_store import SentenceTransformerEncoder

            _emit(on_phase, LoadPhase.WEIGHTS, key)
            encoder = SentenceTransformerEncoder(
                model, local_files_only=local_files_only
            )
        if warmup:
            _emit(on_phase, LoadPhase.WARMUP, key)
            encoder.encode([""])
        else:
            _emit(on_phase, LoadPhase.DISABLED, key, detail="warmup not requested")
        _emit(on_phase, LoadPhase.READY, key)
        return encoder
    except Exception as exc:
        _emit(on_phase, LoadPhase.FAILED, key, detail=f"{type(exc).__name__}: {exc}")
        raise


def cache_key(
    model: str, backend: str | None = None, revision: str | None = None
) -> EncoderKey:
    """The ``(model, backend, revision)`` key :func:`get_query_encoder` would use.

    A cheap, side-effect-free way for a caller (a pre-check before an
    expensive availability probe, a phase-hook listener keying its own state)
    to ask "which encoder would this resolve to?" without constructing one.
    """
    resolved_backend = resolve_backend(backend)
    resolved_revision = revision or _default_revision(model, resolved_backend)
    return (model, resolved_backend, resolved_revision)


def is_cached(
    model: str, backend: str | None = None, revision: str | None = None
) -> bool:
    """Whether :func:`cache_key` for these arguments already has a live encoder."""
    return cache_key(model, backend, revision) in _ENCODERS


def get_query_encoder(
    model: str,
    *,
    backend: str | None = None,
    revision: str | None = None,
    local_files_only: bool = True,
    warmup: bool = False,
    on_phase: PhaseListener | None = None,
) -> Encoder:
    """The one factory every query-side caller uses.

    ``backend`` defaults to :func:`resolve_backend`; ``revision`` defaults to
    the pinned artefact revision for onnx, or a fixed placeholder for torch
    (which is not revision-pinned). Concurrent callers for the same key block
    on one lock and share one constructed encoder (single-flight); a search
    and a warm racing each other pay the load cost once.
    """
    key = cache_key(model, backend, revision)
    _, resolved_backend, resolved_revision = key

    cached = _ENCODERS.get(key)
    if cached is not None:
        return cached

    lock = _lock_for(key)
    with lock:
        cached = _ENCODERS.get(key)
        if cached is not None:  # someone else won the race while we waited
            return cached
        encoder = _construct(
            model,
            resolved_backend,
            resolved_revision,
            local_files_only=local_files_only,
            warmup=warmup,
            on_phase=on_phase,
        )
        _ENCODERS[key] = encoder
        return encoder


def reset_cache() -> None:
    """Test-only: drop every cached encoder and its lock."""
    _ENCODERS.clear()
    _KEY_LOCKS.clear()


__all__ = [
    "BACKEND_ENV",
    "BACKEND_ONNX",
    "BACKEND_TORCH",
    "BACKENDS",
    "EncoderKey",
    "LoadPhase",
    "PhaseEvent",
    "PhaseListener",
    "cache_key",
    "get_query_encoder",
    "is_cached",
    "reset_cache",
    "resolve_backend",
]
