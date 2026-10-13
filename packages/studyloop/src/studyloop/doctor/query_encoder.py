"""Doctor check for the pinned ONNX query-encoder artefact (lane A5).

Closes the gap Gate P exposed: with ``query_encoder: auto`` as the shipped
default, a machine whose backend resolves to onnx but whose local Hugging
Face cache never got the pinned artefact silently degrades hybrid search to
lexical -- nobody is told. This check is the "somebody is told" half; the fix
is ``agent_session_tools.artefact_fetch.fetch_query_encoder_artefact``, which
``--fix`` calls explicitly (D-7: doctor never fetches on the learner's behalf
except through the fix path the learner asked for by passing ``--fix``).

Never imports ``torch``/``sentence-transformers``/``onnxruntime`` to run:
backend resolution reads config only, the runtime probe is
``importlib.util.find_spec`` over the resolved backend's own imports
(``embedding_store.RUNTIME_MODULES``), and the cache probe is
``huggingface_hub.try_to_load_from_cache`` + a local sha256 hash, so this
check costs nothing close to what constructing an encoder would.

A runtime the resolved path needs but this interpreter cannot import is a
WARN wherever a surface resolves to hybrid (issue #46 item 3): that is the
silent lexical-only degradation this check exists to report, and the hint it
carries fixes the venv that raised it (``embedding_store.install_hint``).
Where no surface resolves to hybrid the encoder is never built, so it stays
an info.

The resolved backend is never compared to :data:`query_encoders.BACKEND_ONNX`
un-concretised: ``auto`` (the wave-1 encoder mitigation lane) concretises to
a real backend PER MODEL, so this check resolves the model first
(:func:`agent_session_tools.artefact_fetch.resolve_fetch_model`) and calls
``query_encoders._concretise`` (via ``getattr``, since it does not exist on
every base ref this check has to run against) before deciding whether the
artefact is even required -- otherwise a shipped ``auto`` default would go
silent on exactly the machine this lane exists to protect (council finding
A5-1).
"""

from __future__ import annotations

import importlib.util
import sys

from studyloop.doctor.models import CheckResult


def _missing_runtime_modules(backend: str) -> tuple[str, ...]:
    """The resolved backend's own imports that this interpreter cannot find.

    ``find_spec`` rather than a real import (torch costs seconds). The lists
    are ``embedding_store.RUNTIME_MODULES`` -- the same ones the ``[semantic]``
    extra is pinned to -- so the probe asks about what the ONNX path actually
    imports, not ``sentence_transformers`` as a proxy for "the extra".
    """
    from agent_session_tools import embedding_store

    missing: list[str] = []
    for name in embedding_store.RUNTIME_MODULES.get(backend, ()):
        try:
            found = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            missing.append(name)
    return tuple(missing)


def _hybrid_surfaces() -> list[str]:
    from agent_session_tools import retrieval

    return [
        surface
        for surface in retrieval.SURFACES
        if retrieval.resolve_mode(surface=surface) == retrieval.MODE_HYBRID
    ]


def check_query_encoder_artefact() -> list[CheckResult]:
    from agent_session_tools import query_encoders

    try:
        backend = query_encoders.resolve_backend()
    except ValueError:
        # An unresolvable config value is a different check's problem to
        # fail loudly on (query_encoders.resolve_backend raises for its own
        # callers) -- this check only cares whether onnx would need a fetch.
        return [
            CheckResult(
                "deps",
                "query_encoder_artefact",
                "info",
                "query encoder backend is misconfigured; skipping the "
                "artefact check (resolving a backend elsewhere will surface "
                "the error)",
                "",
                fix_auto=False,
            )
        ]

    from agent_session_tools.artefact_fetch import (
        FETCH_COMMAND,
        check_cached_artefact,
        resolve_fetch_model,
    )

    model = resolve_fetch_model()
    # `auto` (wave-1 encoder mitigation) concretises per model rather than
    # being a fixed backend: resolve the model FIRST so an `auto` config
    # that would resolve to onnx for THIS model is not silently reported as
    # "not required" (council finding A5-1). `_concretise` does not exist on
    # this lane's base ref yet -- when it lands, this picks it up with no
    # further change here.
    concretise = getattr(query_encoders, "_concretise", None)
    effective_backend = concretise(model, backend) if concretise is not None else backend

    missing = _missing_runtime_modules(effective_backend)
    if missing:
        # Issue #46 item 3: a runtime the resolved path needs is not importable
        # in THIS interpreter. Where a surface resolves to hybrid that is the
        # silent lexical-only degradation this check exists to report -- a
        # warn, with the hint that fixes this venv. Where nothing resolves to
        # hybrid the encoder is never built, so it stays an info.
        from agent_session_tools import embedding_store

        hybrid = _hybrid_surfaces()
        where = f"not importable in {sys.prefix}: {', '.join(missing)} missing"
        if hybrid:
            message = (
                f"semantic runtime for the {effective_backend} query encoder is {where}; "
                f"{', '.join(hybrid)} resolve to hybrid and will silently fall back "
                "to lexical search"
            )
        else:
            message = (
                f"semantic runtime for the {effective_backend} query encoder is {where}; "
                "no surface resolves to hybrid, so the artefact check does not apply"
            )
        return [
            CheckResult(
                "deps",
                "query_encoder_artefact",
                "warn" if hybrid else "info",
                message,
                embedding_store.install_hint(),
                fix_auto=False,
            )
        ]

    if effective_backend != query_encoders.BACKEND_ONNX:
        return [
            CheckResult(
                "deps",
                "query_encoder_artefact",
                "info",
                f"query encoder backend is {backend!r}; the pinned ONNX artefact is not required",
                "",
                fix_auto=False,
            )
        ]

    try:
        check = check_cached_artefact(model)
    except ValueError as exc:
        # The configured (or auto-concretised) backend resolves to onnx, but
        # the model has no entry in embeddings.ONNX_ARTIFACTS -- a
        # misconfiguration, not a bug in this checker (E-A5 finding 4).
        return [
            CheckResult(
                "deps",
                "query_encoder_artefact",
                "warn",
                f"query encoder backend resolves to onnx for model {model!r}, "
                f"but it has no pinned ONNX artefact ({exc}); change the "
                "configured model or add a pin to embeddings.ONNX_ARTIFACTS",
                "",
                fix_auto=False,
            )
        ]
    if check.status == "pass":
        return [
            CheckResult(
                "deps",
                "query_encoder_artefact",
                "pass",
                f"ONNX query-encoder artefact cached and verified for "
                f"{check.model} ({check.hf_name}@{check.revision})",
                "",
                fix_auto=False,
            )
        ]
    if check.status == "fail":
        return [
            CheckResult(
                "deps",
                "query_encoder_artefact",
                "fail",
                f"ONNX query-encoder artefact for {check.model} failed "
                f"verification: {check.detail}",
                FETCH_COMMAND,
                fix_auto=True,
            )
        ]
    return [
        CheckResult(
            "deps",
            "query_encoder_artefact",
            "warn",
            f"backend would resolve to onnx for {check.model} but the pinned "
            f"artefact is not cached ({check.hf_name}@{check.revision}, "
            f"{check.detail})",
            FETCH_COMMAND,
            fix_auto=True,
        )
    ]
