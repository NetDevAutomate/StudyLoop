"""Doctor check for the pinned ONNX query-encoder artefact (lane A5).

Closes the gap Gate P exposed: with ``query_encoder: auto`` as the shipped
default, a machine whose backend resolves to onnx but whose local Hugging
Face cache never got the pinned artefact silently degrades hybrid search to
lexical -- nobody is told. This check is the "somebody is told" half; the fix
is ``agent_session_tools.artefact_fetch.fetch_query_encoder_artefact``, which
``--fix`` calls explicitly (D-7: doctor never fetches on the learner's behalf
except through the fix path the learner asked for by passing ``--fix``).

Never imports ``torch``/``sentence-transformers``/``onnxruntime`` to run:
backend resolution reads config only, and the cache probe is
``huggingface_hub.try_to_load_from_cache`` + a local sha256 hash, so this
check costs nothing close to what constructing an encoder would.
"""

from __future__ import annotations

import importlib.util

from studyloop.doctor.models import CheckResult


def check_query_encoder_artefact() -> list[CheckResult]:
    if importlib.util.find_spec("sentence_transformers") is None:
        return [
            CheckResult(
                "deps",
                "query_encoder_artefact",
                "info",
                "semantic layer not installed; the ONNX query-encoder artefact "
                "check does not apply",
                "uv tool install 'agent-session-tools[semantic]'",
                fix_auto=False,
            )
        ]

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

    if backend != query_encoders.BACKEND_ONNX:
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

    from agent_session_tools.artefact_fetch import FETCH_COMMAND, check_cached_artefact

    check = check_cached_artefact()
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
