"""Explicit fetch path for the pinned ONNX query-encoder artefact (lane A5).

GAP THIS CLOSES: ``onnx_encoder``'s degradation message has always promised
"run the install/doctor/backfill path to fetch it once", but until this
module existed no product path actually did the fetching -- the pinned
artefact only ever landed in a local Hugging Face cache because a human
fetched it by hand. With ``query_encoder: auto`` now the shipped default
(Gate P), a machine with corpus vectors but no cached artefact silently
degrades hybrid search to lexical until someone notices and fetches.

``FETCH_COMMAND`` is the single name for the fix: :mod:`agent_session_tools
.maintenance`'s ``fetch-query-encoder`` subcommand and ``studyloop doctor
--fix`` both call :func:`fetch_query_encoder_artefact`, and both the
degradation messages in :mod:`agent_session_tools.onnx_encoder` and the setup
docs cite this same constant -- a structural test proves the promise and the
mechanism agree without copying prose (council TEST SHAPE rule).

EXPLICIT ACTION ONLY (mirrors the ``onnx_encoder``/``retrieval`` rule this
module exists to make good on): nothing here is ever called from a search or
the SessionEnd export hook. ``fetch_query_encoder_artefact`` always fetches
with ``local_files_only=False`` -- that is exactly what makes it the
*fetching* path rather than the *search* path -- and its only callers are a
CLI command and ``doctor --fix``, both deliberate user actions. Respects
``HF_HUB_OFFLINE=1`` with a named skip rather than trying and failing loudly.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

FETCH_COMMAND = "session-maint fetch-query-encoder"
"""The one CLI verb every degradation message and doc names (see module docstring)."""

FetchStatus = Literal["already_cached", "fetched", "offline_skip"]
CacheStatus = Literal["pass", "warn", "fail"]

# Exit codes for the CLI command, distinguishing all three success-ish
# outcomes from each other and from a hard failure (1): "nothing needed
# doing" (0), "downloaded it just now" (3), "declined because offline" (4).
# Deliberately outside click's reserved range (1 hard failure, 2 usage
# error -- click.UsageError.exit_code == 2) so a wrapper keying off these
# codes never confuses "fetched" with a typo'd option (E-A5 finding 3).
EXIT_CODES: dict[FetchStatus, int] = {
    "already_cached": 0,
    "fetched": 3,
    "offline_skip": 4,
}


class ArtefactVerificationError(RuntimeError):
    """A fetched (or already-cached) file's sha256/size does not match the pin."""


@dataclass(frozen=True, slots=True)
class FetchedFile:
    """One verified file backing the query encoder."""

    relpath: str
    path: Path
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class FetchResult:
    """The outcome of :func:`fetch_query_encoder_artefact`."""

    model: str
    hf_name: str
    revision: str
    status: FetchStatus
    files: tuple[FetchedFile, ...] = field(default_factory=tuple)
    detail: str = ""

    @property
    def total_bytes(self) -> int:
        return sum(f.size_bytes for f in self.files)


@dataclass(frozen=True, slots=True)
class CacheCheck:
    """The outcome of :func:`check_cached_artefact` -- read-only, never fetches."""

    model: str
    hf_name: str
    revision: str
    status: CacheStatus
    detail: str = ""


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_fetch_model(model: str | None = None) -> str:
    """Which model to fetch the ONNX artefact for: arg -> DB pin -> configured.

    Mirrors ``retrieval.warm_query_encoder``'s resolution order (lane A1):
    an explicit argument wins outright; otherwise prefer the model the
    configured database's ``message_embeddings`` are actually pinned to
    (fetching an artefact for a model nothing searches with is pure cost);
    otherwise fall back to the configured embedding model.
    """
    if model:
        return model
    from agent_session_tools.retrieval import _pinned_db_model

    pinned = _pinned_db_model()
    if pinned:
        return pinned
    from agent_session_tools.config_loader import get_embedding_model

    return get_embedding_model()


def _artefact_for(model: str) -> dict[str, object]:
    from agent_session_tools.embeddings import ONNX_ARTIFACTS

    artefact = ONNX_ARTIFACTS.get(model)
    if artefact is None:
        msg = (
            f"no pinned ONNX artefact for model {model!r}; add it to "
            "embeddings.ONNX_ARTIFACTS before fetching"
        )
        raise ValueError(msg)
    return artefact


# (relpath, sha256 registry key, size registry key or None -- only the onnx
# graph has a pinned size today). Tokenizer file names are fixed literals,
# matching onnx_encoder._load_tokenizer's own hard-coded "tokenizer.json".
def _fetch_plan(artefact: dict[str, object]) -> tuple[tuple[str, str, str | None], ...]:
    return (
        (str(artefact["onnx_relpath"]), "onnx_sha256", "onnx_size_bytes"),
        ("tokenizer.json", "tokenizer_sha256", None),
        ("tokenizer_config.json", "tokenizer_config_sha256", None),
    )


def fetch_query_encoder_artefact(model: str | None = None) -> FetchResult:
    """Fetch (or confirm) + verify the pinned ONNX query-encoder artefact.

    Resolves ``model`` via :func:`resolve_fetch_model`, then downloads the
    pinned ``onnx/model.onnx``, ``tokenizer.json`` and ``tokenizer_config.json``
    at the pinned revision (``local_files_only=False`` -- this function IS the
    explicit fetch), verifying each against ``embeddings.ONNX_ARTIFACTS``'s
    sha256 (and, for the onnx graph, its pinned size). Raises
    :class:`ArtefactVerificationError` on any mismatch -- a corrupted or
    substituted file must never be trusted for query encoding.

    Respects ``HF_HUB_OFFLINE=1``: returns an ``offline_skip`` result with a
    named reason instead of attempting (and failing) a download.
    """
    resolved_model = resolve_fetch_model(model)
    artefact = _artefact_for(resolved_model)
    hf_name = str(artefact["hf_name"])
    revision = str(artefact["revision"])

    if os.environ.get("HF_HUB_OFFLINE") == "1":
        return FetchResult(
            model=resolved_model,
            hf_name=hf_name,
            revision=revision,
            status="offline_skip",
            detail=(
                "HF_HUB_OFFLINE=1 is set; not fetching. Unset it (or run "
                "without it) to fetch the pinned artefact."
            ),
        )

    try:
        from huggingface_hub import hf_hub_download, try_to_load_from_cache
    except ImportError as exc:
        from agent_session_tools.embedding_store import INSTALL_HINT

        msg = f"huggingface-hub is not installed; install: {INSTALL_HINT}"
        raise RuntimeError(msg) from exc

    def _verify(path: Path, size_key: str | None) -> tuple[str, int]:
        # Size before hash: a cheap pre-filter that can actually short-circuit
        # a wrong file (E-A5 finding 7). Checking sha256 first can never
        # catch a size-pin bug -- identical sha256 implies identical bytes
        # implies identical length, so a size check running only after a
        # passing hash check is unreachable except as a false-rejection of a
        # correct artefact.
        size_bytes = path.stat().st_size
        if size_key is not None:
            expected_size = int(artefact[size_key])  # type: ignore[arg-type]
            if size_bytes != expected_size:
                msg = (
                    f"{hf_name}/{relpath}@{revision}: size mismatch "
                    f"(expected {expected_size:,} bytes, got {size_bytes:,})"
                )
                raise ArtefactVerificationError(msg)
        return _sha256_of(path), size_bytes

    fetched: list[FetchedFile] = []
    any_new = False
    for relpath, sha_key, size_key in _fetch_plan(artefact):
        was_cached = bool(try_to_load_from_cache(hf_name, relpath, revision=revision))
        if not was_cached:
            any_new = True
        downloaded = hf_hub_download(
            hf_name,
            relpath,
            revision=revision,
            local_files_only=False,
            force_download=False,
        )
        path = Path(downloaded)
        expected_sha = str(artefact[sha_key])
        actual_sha, size_bytes = _verify(path, size_key)
        if actual_sha != expected_sha and was_cached:
            # hf_hub_download without force_download returns the existing
            # cache pointer even when its contents no longer match the
            # registry pin -- a stale/substituted blob is handed straight
            # back and re-rejected forever otherwise (E-A5 finding 2). Retry
            # once with a real re-download before treating this as a
            # genuine supply-chain failure.
            any_new = True
            downloaded = hf_hub_download(
                hf_name,
                relpath,
                revision=revision,
                local_files_only=False,
                force_download=True,
            )
            path = Path(downloaded)
            actual_sha, size_bytes = _verify(path, size_key)
        if actual_sha != expected_sha:
            msg = (
                f"{hf_name}/{relpath}@{revision}: sha256 mismatch "
                f"(expected {expected_sha}, got {actual_sha}) -- refusing to "
                "trust this file for query encoding"
            )
            raise ArtefactVerificationError(msg)
        fetched.append(
            FetchedFile(
                relpath=relpath, path=path, sha256=actual_sha, size_bytes=size_bytes
            )
        )

    status: FetchStatus = "fetched" if any_new else "already_cached"
    return FetchResult(
        model=resolved_model,
        hf_name=hf_name,
        revision=revision,
        status=status,
        files=tuple(fetched),
    )


def check_cached_artefact(model: str | None = None) -> CacheCheck:
    """Read-only counterpart to :func:`fetch_query_encoder_artefact` -- never fetches.

    Used by ``studyloop doctor``'s ``query_encoder_artefact`` check: reports
    whether the pinned files are already in the local Hugging Face cache and,
    if so, whether their sha256 still matches the registry -- without ever
    triggering a download itself (D-7: doctor never fetches on the learner's
    behalf; ``--fix`` is the one path that does, by calling
    :func:`fetch_query_encoder_artefact` explicitly).
    """
    resolved_model = resolve_fetch_model(model)
    artefact = _artefact_for(resolved_model)
    hf_name = str(artefact["hf_name"])
    revision = str(artefact["revision"])

    from huggingface_hub import try_to_load_from_cache

    missing: list[str] = []
    mismatched: list[str] = []
    for relpath, sha_key, _size_key in _fetch_plan(artefact):
        cached = try_to_load_from_cache(hf_name, relpath, revision=revision)
        if not cached or not isinstance(cached, str):
            missing.append(relpath)
            continue
        actual_sha = _sha256_of(Path(cached))
        expected_sha = str(artefact[sha_key])
        if actual_sha != expected_sha:
            mismatched.append(relpath)

    if mismatched:
        return CacheCheck(
            model=resolved_model,
            hf_name=hf_name,
            revision=revision,
            status="fail",
            detail=f"sha256 mismatch: {', '.join(mismatched)}",
        )
    if missing:
        return CacheCheck(
            model=resolved_model,
            hf_name=hf_name,
            revision=revision,
            status="warn",
            detail=f"not cached: {', '.join(missing)}",
        )
    return CacheCheck(
        model=resolved_model, hf_name=hf_name, revision=revision, status="pass"
    )


__all__ = [
    "EXIT_CODES",
    "FETCH_COMMAND",
    "ArtefactVerificationError",
    "CacheCheck",
    "CacheStatus",
    "FetchResult",
    "FetchStatus",
    "FetchedFile",
    "check_cached_artefact",
    "fetch_query_encoder_artefact",
    "resolve_fetch_model",
]
