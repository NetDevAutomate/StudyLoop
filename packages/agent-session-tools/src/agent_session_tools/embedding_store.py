"""The embed job and the derived vector index: chunking, writing, reconciling, KNN.

This is the write half of the Stage 3 substrate. ``embedding_alignment`` says
what a correct ``message_embeddings`` table looks like and counts the ways it
can be wrong; this module is the only thing that makes rows, and it makes them
so those counts stay at zero.

Four decisions from the Stage 3 design shape everything here:

* **D-2 the vector index is a sidecar.** ``sqlite-vec``'s ``vec0`` virtual table
  and its shadow tables live in ``<db-stem>.vec.db`` beside the database
  (:func:`sidecar_path`), ``ATTACH``ed as ``vec``. ``sessions.db`` therefore
  never contains a virtual table, so ``VACUUM INTO``, ``integrity_check``,
  compaction, sync and every plain connection keep working with no extension
  loaded. The sidecar is disposable: :func:`reconcile` rebuilds it from
  ``message_embeddings`` and reports ``(inserted, deleted)``.
* **D-3 chunking, never truncation.** A message over the model's token cap
  becomes several chunks split on paragraph then sentence boundaries, and by
  hard token windows only when a single sentence still exceeds the cap.
  ``truncated = 1`` marks a chunk that came out of a hard window. No content is
  ever dropped: the chunks of a message concatenate back to its exact text.
* **D-4 the hash is written inside the write transaction.** Encoding happens
  outside any transaction (model inference must not hold a write lock against
  the exporters); then ``BEGIN IMMEDIATE``, re-read each candidate's content,
  and insert only when it still hashes to what was encoded. A message that
  changed underneath is skipped, stays ``missing``, and the next run picks it up.
* **D-5 the model is pinned per row.** ``embed`` refuses to run while vectors
  from another model or dimension exist unless ``replace_model=True`` sweeps
  them first — comparing two models' vectors byte-wise is silently wrong.

Nothing in :func:`chunk_text` or :func:`embed` requires ``sqlite-vec``; only
the index functions load the extension. :func:`availability` answers whether
the semantic layer can run at all and **never downloads a model**.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .embedding_alignment import (
    DEFAULT_MIN_CONTENT_LENGTH,
    alignment_report,
    content_sha256,
    missing_messages,
    sweep,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Iterable, Sequence

logger = logging.getLogger(__name__)

#: The install line every degradation path prints (D-8).
INSTALL_HINT = "uv tool install 'agent-session-tools[semantic]'"

#: Schema name the sidecar is ATTACHed under, and the vec0 table inside it.
SIDECAR_SCHEMA = "vec"
VEC_TABLE = "message_vec"

#: ``message_id || '#' || chunk_ix`` -- the vec0 primary key.
CHUNK_KEY_SEPARATOR = "#"

_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n[\s]*")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?;:])[ \t]*\n?[ \t]*(?=\S)|\n")
_WHITESPACE_RUN = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# the encoder seam
# ---------------------------------------------------------------------------


@runtime_checkable
class Encoder(Protocol):
    """What the embed job needs from a model, so tests can supply a fake one.

    ``encode`` returns one ``bytes`` per input text: ``dim`` float32 values,
    little-endian, which is exactly what ``vec0`` and ``numpy.frombuffer``
    read. Vectors are expected to be L2-normalised so ``vec0``'s L2 distance
    ranks the same way cosine similarity does.
    """

    name: str
    dim: int
    max_tokens: int

    def count_tokens(self, text: str) -> int: ...

    def encode(self, texts: Sequence[str]) -> list[bytes]: ...


class SentenceTransformerEncoder:
    """The real encoder: a ``sentence-transformers`` model behind :class:`Encoder`.

    ``name``, ``dim`` and ``max_tokens`` come from ``embeddings.SUPPORTED_MODELS``
    so the stored ``(model, dim)`` pair is the registry's, not a guess from the
    loaded weights; a disagreement between the two is raised at first
    :meth:`encode` rather than written into the table.
    """

    def __init__(self, model: str | None = None) -> None:
        from .embeddings import get_configured_model, get_model, get_model_config

        name = model or get_configured_model()
        config = get_model_config(name)
        self.name = name
        self.dim = int(config["dimensions"])
        self.max_tokens = int(config["max_tokens"])
        self._model = get_model(name)

    def count_tokens(self, text: str) -> int:
        """Length of the sequence the model would actually see, special tokens included.

        ``tokenize`` rather than ``encode``: the latter logs a warning for every
        text over the model's window, and chunking exists precisely to feed it
        those texts.
        """
        tokenizer = self._model.tokenizer
        return len(tokenizer.tokenize(text)) + tokenizer.num_special_tokens_to_add()

    def encode(self, texts: Sequence[str]) -> list[bytes]:
        import numpy as np

        if not texts:
            return []
        matrix = self._model.encode(
            list(texts),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        array = np.asarray(matrix, dtype="<f4")
        if array.ndim != 2 or array.shape[1] != self.dim:
            raise RuntimeError(
                f"model {self.name} produced {array.shape[-1]}-dimensional vectors, "
                f"but the registry records dim={self.dim}; fix SUPPORTED_MODELS before "
                "writing rows that claim the wrong dimension"
            )
        return [row.tobytes() for row in array]


# ---------------------------------------------------------------------------
# availability -- never downloads
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Availability:
    """Whether the semantic layer can run here, and if not, which half is missing."""

    ready: bool
    model_ok: bool
    extension_ok: bool
    reason: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _extension_available() -> tuple[bool, str]:
    try:
        import sqlite_vec
    except ImportError:
        return False, f"sqlite-vec is not installed; install: {INSTALL_HINT}"
    probe = sqlite3.connect(":memory:")
    try:
        probe.enable_load_extension(True)
        sqlite_vec.load(probe)
        probe.enable_load_extension(False)
    except (AttributeError, sqlite3.Error, OSError) as exc:
        return False, f"sqlite-vec will not load into this Python's sqlite3: {exc}"
    finally:
        probe.close()
    return True, ""


def _model_available(model: str) -> tuple[bool, str]:
    try:
        from huggingface_hub import try_to_load_from_cache
    except ImportError:
        return False, f"sentence-transformers is not installed; install: {INSTALL_HINT}"
    try:
        from .embeddings import get_model_config, is_available
    except ImportError:  # pragma: no cover - the package always imports
        return False, f"the embeddings module is unavailable; install: {INSTALL_HINT}"
    if not is_available():
        return False, f"sentence-transformers is not installed; install: {INSTALL_HINT}"
    hf_name = str(get_model_config(model)["hf_name"])
    for filename in ("config.json", "modules.json"):
        if not try_to_load_from_cache(hf_name, filename):
            return False, (
                f"model {model} ({hf_name}) is not in the local Hugging Face cache; "
                "run 'session-maint embed' once interactively to fetch it"
            )
    return True, ""


def availability(model: str | None = None) -> Availability:
    """Can this machine embed right now, without fetching anything?

    Called on the export path (D-7), so it must be cheap and must never pull a
    90 MB model into a SessionEnd hook: the model check is a *cache* lookup, not
    a load.
    """
    if model is None:
        try:
            from .embeddings import get_configured_model

            model = get_configured_model()
        except Exception:  # pragma: no cover - config is best-effort here
            model = "all-mpnet-base-v2"
    extension_ok, extension_reason = _extension_available()
    model_ok, model_reason = _model_available(model)
    reason = "; ".join(r for r in (extension_reason, model_reason) if r)
    return Availability(
        ready=extension_ok and model_ok,
        model_ok=model_ok,
        extension_ok=extension_ok,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# D-3 chunking
# ---------------------------------------------------------------------------


def _split_keeping_text(text: str, pattern: re.Pattern[str]) -> list[str]:
    """Split on ``pattern`` so the pieces concatenate back to ``text`` exactly.

    The separator stays attached to the piece before it, which is what makes
    "no content is ever dropped" checkable by string equality rather than by
    reading the code.
    """
    pieces: list[str] = []
    start = 0
    for match in pattern.finditer(text):
        if match.end() == start:  # a zero-width or leading match: nothing to cut
            continue
        pieces.append(text[start : match.end()])
        start = match.end()
    if start < len(text):
        pieces.append(text[start:])
    return [piece for piece in pieces if piece]


def _longest_prefix_within_cap(text: str, encoder: Encoder) -> int:
    """Character count of the longest prefix of ``text`` that fits the token cap."""
    low, high, best = 1, len(text), 0
    while low <= high:
        middle = (low + high) // 2
        if encoder.count_tokens(text[:middle]) <= encoder.max_tokens:
            best = middle
            low = middle + 1
        else:
            high = middle - 1
    return best


def _hard_windows(span: str, encoder: Encoder) -> list[tuple[str, bool]]:
    """Cut ``span`` into cap-sized windows, ignoring boundaries. Marks ``truncated``.

    Reached only when a single sentence is longer than the whole model window
    (a pasted log line, a minified blob). The pieces still concatenate back to
    ``span``; ``truncated`` records that the split fell wherever the token
    budget ran out rather than at a boundary the text offered.
    """
    windows: list[tuple[str, bool]] = []
    rest = span
    while rest:
        if encoder.count_tokens(rest) <= encoder.max_tokens:
            windows.append((rest, True))
            break
        cut = _longest_prefix_within_cap(rest, encoder)
        if cut <= 0:
            raise ValueError(
                f"encoder {encoder.name} reports max_tokens={encoder.max_tokens}, which "
                "cannot hold even one character; refusing to loop"
            )
        windows.append((rest[:cut], True))
        rest = rest[cut:]
    return windows


def _atoms(text: str, encoder: Encoder) -> list[tuple[str, bool]]:
    """Paragraphs, then sentences, then hard windows -- each piece within the cap."""
    atoms: list[tuple[str, bool]] = []
    for paragraph in _split_keeping_text(text, _PARAGRAPH_BREAK):
        if encoder.count_tokens(paragraph) <= encoder.max_tokens:
            atoms.append((paragraph, False))
            continue
        for sentence in _split_keeping_text(paragraph, _SENTENCE_BREAK):
            if encoder.count_tokens(sentence) <= encoder.max_tokens:
                atoms.append((sentence, False))
                continue
            atoms.extend(_hard_windows(sentence, encoder))
    return atoms


def chunk_text(text: str, encoder: Encoder) -> list[tuple[str, bool]]:
    """``[(chunk, truncated), ...]`` covering ``text`` exactly, each within the cap.

    ``"".join(chunk for chunk, _ in chunk_text(t, e)) == t`` for every ``t``:
    Stage 1 measured 15.7-21.8 % of embeddable messages over every candidate
    model's cap, so truncating would silently drop a fifth of the corpus's tail.
    """
    if not text:
        return []
    if encoder.max_tokens <= 0:
        raise ValueError(
            f"encoder {encoder.name} declares max_tokens={encoder.max_tokens}"
        )
    if encoder.count_tokens(text) <= encoder.max_tokens:
        return [(text, False)]

    chunks: list[tuple[str, bool]] = []
    current, current_truncated = "", False
    for piece, truncated in _atoms(text, encoder):
        if not current:
            current, current_truncated = piece, truncated
            continue
        merged = current + piece
        if encoder.count_tokens(merged) <= encoder.max_tokens:
            current, current_truncated = merged, current_truncated or truncated
        else:
            chunks.append((current, current_truncated))
            current, current_truncated = piece, truncated
    if current:
        chunks.append((current, current_truncated))
    return chunks


# ---------------------------------------------------------------------------
# D-4 the embed job
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EmbedStats:
    """What one :func:`embed` call did, and what is left."""

    model: str
    dim: int
    embedded_messages: int
    chunks_written: int
    skipped_changed: int
    remaining: int
    seconds: float
    truncated_chunks: int = 0
    swept: int = 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class _Encoded:
    """One candidate's encoded chunks, waiting for the hash check to let them in."""

    message_id: str
    content_sha256: str
    chunks: list[tuple[int, str, bool, bytes]] = field(default_factory=list)


def _min_content_length() -> int:
    try:
        from .config_loader import get_semantic_config

        return int(
            get_semantic_config().get("min_content_length", DEFAULT_MIN_CONTENT_LENGTH)
        )
    except Exception:  # pragma: no cover - a missing/odd config must not stop the job
        return DEFAULT_MIN_CONTENT_LENGTH


def _resolve_pin(model: str | None, encoder: Encoder | None) -> tuple[str, int]:
    """``(model name, dim)`` without loading a model, so a refusal stays cheap.

    An injected encoder is authoritative about its own name and dimension; a
    real run reads them from ``SUPPORTED_MODELS``, which is registry data. That
    ordering is what lets :func:`embed` refuse a model mismatch (D-5), or find
    an empty backlog, before spending seconds and hundreds of megabytes on
    weights it will not use.
    """
    if encoder is not None:
        if model is not None and model != encoder.name:
            raise ValueError(
                f"model={model!r} does not match the injected encoder's name "
                f"{encoder.name!r}; the stored model pin must be the model that encoded"
            )
        return encoder.name, encoder.dim
    from .embeddings import get_configured_model, get_model_config

    name = model or get_configured_model()
    return name, int(get_model_config(name)["dimensions"])


def _load_encoder(model: str) -> Encoder:
    """Load the real model. Only the extension is gated here.

    A cold Hugging Face cache is a *fetch*, not an error: ``session-maint
    embed`` is the interactive path allowed to warm it. The export hook is the
    path that must not (D-7), so it checks :func:`availability` ``.ready``
    before ever calling :func:`embed`.
    """
    availability_now = availability(model)
    if not availability_now.extension_ok:
        raise RuntimeError(
            availability_now.reason or f"semantic layer unavailable; {INSTALL_HINT}"
        )
    return SentenceTransformerEncoder(model)


def embed(
    conn: sqlite3.Connection,
    *,
    model: str | None = None,
    encoder: Encoder | None = None,
    budget_seconds: float | None = None,
    batch_size: int = 64,
    replace_model: bool = False,
    _after_encode: Callable[[], None] | None = None,
) -> EmbedStats:
    """Embed the backlog for one model, bounded by ``budget_seconds``.

    Encoding happens outside any transaction; each batch is then written under
    ``BEGIN IMMEDIATE`` after re-reading the candidate's content, so a message
    the exporter rewrote mid-flight is skipped (``skipped_changed``) rather than
    stored against text it no longer has. The budget is checked between
    batches, so a bounded run always leaves the table consistent.

    ``_after_encode`` is a test seam: it runs after a batch is encoded and
    before its write transaction, which is the only window in which the race
    the hash check defends against can be staged.
    """
    started = time.monotonic()
    model_name, dim = _resolve_pin(model, encoder)
    min_length = _min_content_length()

    swept = 0
    report = alignment_report(
        conn, model=model_name, dim=dim, min_content_length=min_length
    )
    if report.model_mismatch:
        if not replace_model:
            raise ValueError(
                f"{report.model_mismatch} vector(s) belong to another model or dimension "
                f"than {model_name} (dim {dim}). Comparing them with this model's vectors "
                "would be silently wrong. Rerun with --replace-model to sweep them first."
            )
        result = sweep(conn, model=model_name, dim=dim)
        conn.commit()
        swept = result.deleted
        logger.info("swept %d misaligned vector(s) before embedding", swept)
        report = alignment_report(
            conn, model=model_name, dim=dim, min_content_length=min_length
        )

    if report.missing == 0:
        return EmbedStats(
            model=model_name,
            dim=dim,
            embedded_messages=0,
            chunks_written=0,
            skipped_changed=0,
            remaining=0,
            seconds=round(time.monotonic() - started, 3),
            swept=swept,
        )

    resolved = encoder if encoder is not None else _load_encoder(model_name)
    if resolved.dim != dim:
        raise RuntimeError(
            f"model {model_name} loads as dim={resolved.dim} but the registry records "
            f"dim={dim}; fix SUPPORTED_MODELS before writing rows that claim the wrong dimension"
        )

    embedded_messages = chunks_written = skipped_changed = truncated_chunks = 0
    while True:
        if budget_seconds is not None and time.monotonic() - started >= budget_seconds:
            break
        candidates = missing_messages(
            conn, model=model_name, min_content_length=min_length, limit=batch_size
        )
        if not candidates:
            break

        encoded = _encode_batch(candidates, resolved)
        if _after_encode is not None:
            _after_encode()

        batch_messages, batch_chunks, batch_skipped, batch_truncated = _write_batch(
            conn, encoded, model=model_name, dim=dim
        )
        embedded_messages += batch_messages
        chunks_written += batch_chunks
        skipped_changed += batch_skipped
        truncated_chunks += batch_truncated
        if batch_messages == 0:
            # Every candidate changed under us (or vanished). They are still
            # `missing`, and re-reading the same list would spin forever.
            break

    remaining = alignment_report(
        conn, model=model_name, dim=dim, min_content_length=min_length
    ).missing
    return EmbedStats(
        model=model_name,
        dim=dim,
        embedded_messages=embedded_messages,
        chunks_written=chunks_written,
        skipped_changed=skipped_changed,
        remaining=remaining,
        seconds=round(time.monotonic() - started, 3),
        truncated_chunks=truncated_chunks,
        swept=swept,
    )


def _encode_batch(
    candidates: Iterable[tuple[str, str]], encoder: Encoder
) -> list[_Encoded]:
    """Chunk and encode a whole batch in one model call, holding no lock."""
    plans: list[tuple[str, str, list[tuple[str, bool]]]] = []
    texts: list[str] = []
    for message_id, content in candidates:
        chunks = chunk_text(content or "", encoder)
        if not chunks:
            continue
        plans.append((message_id, content_sha256(content or ""), chunks))
        texts.extend(chunk for chunk, _ in chunks)

    vectors = encoder.encode(texts)
    if len(vectors) != len(texts):
        raise RuntimeError(
            f"encoder {encoder.name} returned {len(vectors)} vectors for {len(texts)} chunks"
        )

    encoded: list[_Encoded] = []
    cursor = 0
    for message_id, sha, chunks in plans:
        row = _Encoded(message_id=message_id, content_sha256=sha)
        for chunk_ix, (chunk, truncated) in enumerate(chunks):
            vector = vectors[cursor]
            cursor += 1
            if len(vector) != encoder.dim * 4:
                raise RuntimeError(
                    f"encoder {encoder.name} returned {len(vector)} bytes for a "
                    f"dim={encoder.dim} vector (expected {encoder.dim * 4})"
                )
            row.chunks.append((chunk_ix, chunk, truncated, vector))
        encoded.append(row)
    return encoded


def _write_batch(
    conn: sqlite3.Connection, encoded: list[_Encoded], *, model: str, dim: int
) -> tuple[int, int, int, int]:
    """Insert an encoded batch under ``BEGIN IMMEDIATE``, re-checking every hash (D-4)."""
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.execute("BEGIN IMMEDIATE")
    messages = chunks = skipped = truncated = 0
    try:
        for row in encoded:
            current = conn.execute(
                "SELECT content FROM messages WHERE id = ?", (row.message_id,)
            ).fetchone()
            if (
                current is None
                or content_sha256(current[0] or "") != row.content_sha256
            ):
                # Rewritten or deleted between encode and write: still `missing`,
                # picked up by the next run against the text it now has.
                skipped += 1
                continue
            conn.executemany(
                "INSERT OR REPLACE INTO message_embeddings "
                "(message_id, chunk_ix, model, dim, content_sha256, truncated, embedding) "
                "VALUES (?,?,?,?,?,?,?)",
                [
                    (
                        row.message_id,
                        chunk_ix,
                        model,
                        dim,
                        row.content_sha256,
                        int(is_truncated),
                        vector,
                    )
                    for chunk_ix, _chunk, is_truncated, vector in row.chunks
                ],
            )
            messages += 1
            chunks += len(row.chunks)
            truncated += sum(1 for _ix, _c, flag, _v in row.chunks if flag)
    except Exception:
        if owns_transaction:
            conn.rollback()
        raise
    if owns_transaction:
        conn.commit()
    return messages, chunks, skipped, truncated


# ---------------------------------------------------------------------------
# D-2 the sidecar vector index
# ---------------------------------------------------------------------------


def sidecar_path(db_path: Path | str) -> Path:
    """``<stem>.vec.db`` beside ``db_path`` -- the derived index, never the record."""
    path = Path(db_path).expanduser()
    return path.parent / f"{path.stem}.vec.db"


def _main_database_file(conn: sqlite3.Connection) -> str:
    for _seq, name, filename in conn.execute("PRAGMA database_list"):
        if name == "main":
            return filename or ""
    return ""


def _load_extension(conn: sqlite3.Connection) -> None:
    try:
        import sqlite_vec
    except ImportError as exc:
        raise RuntimeError(
            f"sqlite-vec is not installed; install: {INSTALL_HINT}"
        ) from exc
    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)


def _sidecar_attached(conn: sqlite3.Connection) -> bool:
    return any(
        name == SIDECAR_SCHEMA
        for _seq, name, _file in conn.execute("PRAGMA database_list")
    )


def _attach_sidecar(conn: sqlite3.Connection) -> None:
    """Load the extension and ``ATTACH`` the sidecar as ``vec`` (idempotent)."""
    if _sidecar_attached(conn):
        return
    _load_extension(conn)
    main_file = _main_database_file(conn)
    # An in-memory main database has no file to sit beside; ATTACH '' gives
    # SQLite a private temporary database, which is the right lifetime for a
    # derived index belonging to a database that will not outlive the process.
    target = str(sidecar_path(main_file)) if main_file else ""
    conn.execute(f"ATTACH DATABASE ? AS {SIDECAR_SCHEMA}", (target,))


def _vec_table_sql(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        f"SELECT sql FROM {SIDECAR_SCHEMA}.sqlite_master WHERE type='table' AND name=?",
        (VEC_TABLE,),
    ).fetchone()
    return row[0] if row else None


def ensure_index(conn: sqlite3.Connection, *, model: str, dim: int) -> None:
    """Load ``sqlite-vec``, attach the sidecar, and create the ``vec0`` table if absent.

    A sidecar built for another dimension is not migrated: it is derived data,
    so it is dropped and rebuilt by the next :func:`reconcile`.
    """
    _attach_sidecar(conn)
    existing = _vec_table_sql(conn)
    if existing is not None and f"float[{dim}]" not in existing:
        logger.info(
            "sidecar vector index has a different dimension than %s (dim %d); rebuilding",
            model,
            dim,
        )
        conn.execute(f"DROP TABLE {SIDECAR_SCHEMA}.{VEC_TABLE}")
        existing = None
    if existing is None:
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {SIDECAR_SCHEMA}.{VEC_TABLE} "
            f"USING vec0(chunk_key TEXT PRIMARY KEY, embedding float[{dim}])"
        )


def chunk_key(message_id: str, chunk_ix: int) -> str:
    """The vec0 primary key for one chunk."""
    return f"{message_id}{CHUNK_KEY_SEPARATOR}{chunk_ix}"


def split_chunk_key(key: str) -> tuple[str, int]:
    """Inverse of :func:`chunk_key`. Splits on the LAST separator: ids may contain it."""
    message_id, _, index = key.rpartition(CHUNK_KEY_SEPARATOR)
    return message_id, int(index)


def reconcile(conn: sqlite3.Connection) -> tuple[int, int]:
    """Make the sidecar match ``message_embeddings`` exactly -> ``(inserted, deleted)``.

    The index is derived, so this is always safe to run and is the repair for a
    missing, stale or corrupt sidecar. It refuses only when the table itself is
    ambiguous (rows from two dimensions), which is a job for
    ``embedding_alignment.sweep`` first.
    """
    pins = conn.execute("SELECT DISTINCT model, dim FROM message_embeddings").fetchall()
    if len({int(dim) for _model, dim in pins}) > 1:
        raise ValueError(
            "message_embeddings holds vectors of more than one dimension; run "
            "'session-maint embed-check --fix' to sweep the mismatched rows before "
            "reconciling the index"
        )
    if not pins:
        _attach_sidecar(conn)
        if _vec_table_sql(conn) is None:
            return 0, 0
        deleted = conn.execute(f"DELETE FROM {SIDECAR_SCHEMA}.{VEC_TABLE}").rowcount
        conn.commit()
        return 0, max(deleted, 0)

    model, dim = str(pins[0][0]), int(pins[0][1])
    ensure_index(conn, model=model, dim=dim)

    wanted = {
        chunk_key(message_id, chunk_ix)
        for message_id, chunk_ix in conn.execute(
            "SELECT message_id, chunk_ix FROM message_embeddings"
        )
    }
    present = {
        key
        for (key,) in conn.execute(
            f"SELECT chunk_key FROM {SIDECAR_SCHEMA}.{VEC_TABLE}"
        )
    }

    to_delete = sorted(present - wanted)
    to_insert = sorted(wanted - present)
    for key in to_delete:
        conn.execute(
            f"DELETE FROM {SIDECAR_SCHEMA}.{VEC_TABLE} WHERE chunk_key = ?", (key,)
        )
    for key in to_insert:
        message_id, chunk_ix = split_chunk_key(key)
        row = conn.execute(
            "SELECT embedding FROM message_embeddings WHERE message_id=? AND chunk_ix=?",
            (message_id, chunk_ix),
        ).fetchone()
        if row is None:  # deleted between the two reads; the next run settles it
            continue
        conn.execute(
            f"INSERT INTO {SIDECAR_SCHEMA}.{VEC_TABLE}(chunk_key, embedding) VALUES (?,?)",
            (key, row[0]),
        )
    conn.commit()
    return len(to_insert), len(to_delete)


def knn(
    conn: sqlite3.Connection, vector: bytes, n: int
) -> list[tuple[str, int, float]]:
    """``n`` nearest chunks to ``vector`` as ``(message_id, chunk_ix, distance)``.

    Raw candidates: no visibility predicate, no self-exclusion, no join to
    ``sessions``. D-6 puts that on the caller, which over-fetches here and then
    filters through the same predicate the lexical arm uses -- so a hidden
    session's vector can be *found* but never *returned*.
    """
    if n <= 0:
        return []
    _attach_sidecar(conn)
    if _vec_table_sql(conn) is None:
        raise RuntimeError(
            "no vector index in the sidecar; run 'session-maint embed' (or "
            "embedding_store.reconcile) to build it"
        )
    rows = conn.execute(
        f"SELECT chunk_key, distance FROM {SIDECAR_SCHEMA}.{VEC_TABLE} "
        "WHERE embedding MATCH ? AND k = ?",
        (vector, n),
    ).fetchall()
    out: list[tuple[str, int, float]] = []
    for key, distance in rows:
        message_id, chunk_ix = split_chunk_key(key)
        out.append((message_id, chunk_ix, float(distance)))
    return out


__all__ = [
    "INSTALL_HINT",
    "Availability",
    "EmbedStats",
    "Encoder",
    "SentenceTransformerEncoder",
    "availability",
    "chunk_key",
    "chunk_text",
    "embed",
    "ensure_index",
    "knn",
    "reconcile",
    "sidecar_path",
    "split_chunk_key",
]
