"""``OnnxEncoder``: the fast fp32 ONNX query-side encoder (lane A2).

Kills the sentence-transformers/torch import and load (2.87 s, Stage 1) for
the QUERY side of a hybrid search only -- corpus embeddings stay exactly as
they are, torch-built, in the sidecar (council QA2.2). Implements the same
:class:`agent_session_tools.embedding_store.Encoder` Protocol the torch path
does, so :mod:`query_encoders` can hand either one to ``retrieval.py`` without
the caller knowing which ran.

Pinned artefact (council D-6, pinned before this file existed --
``embeddings.ONNX_ARTIFACTS``): the fp32 ``onnx/model.onnx`` graph and the
tokenizer files at one upstream commit of ``BAAI/bge-small-en-v1.5``, by
revision and sha256, checked 2026-09-15 against the model repo's own file
listing. Loading always passes ``local_files_only`` through unchanged (no
"helpful" retry without it) -- the search path's guarantee is "never a
download during a search"; fetching the artefact once is an explicit
install/doctor/backfill action, never something a query triggers.

Pooling: ``BAAI/bge-small-en-v1.5``'s own ``1_Pooling/config.json`` sets
``pooling_mode_cls_token: true`` (checked against the model repo, not
guessed) -- this is CLS-token pooling, not mean pooling, then L2-normalised
(``2_Normalize`` in ``modules.json``). Getting this wrong is exactly the kind
of asymmetry the parity gate exists to catch: a query vector pooled
differently from the corpus vectors changes ranking even though both are
"the same model".
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .embedding_store import INSTALL_HINT


def _load_tokenizer(hf_name: str, revision: str, *, local_files_only: bool) -> Any:
    try:
        from transformers import AutoTokenizer  # pyright: ignore[reportMissingImports]
    except ImportError as exc:
        raise RuntimeError(
            f"transformers is not installed; install: {INSTALL_HINT}"
        ) from exc
    try:
        return AutoTokenizer.from_pretrained(
            hf_name, revision=revision, local_files_only=local_files_only
        )
    except Exception as exc:
        raise RuntimeError(
            f"tokenizer for {hf_name}@{revision} is not in the local Hugging Face "
            "cache; run the install/doctor/backfill path to fetch it once "
            f"(never mid-search): {type(exc).__name__}: {exc}"
        ) from exc


def _load_session(
    hf_name: str, relpath: str, revision: str, *, local_files_only: bool
) -> Any:
    try:
        import onnxruntime  # pyright: ignore[reportMissingImports]
    except ImportError as exc:
        raise RuntimeError(
            f"onnxruntime is not installed; install: {INSTALL_HINT}"
        ) from exc
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise RuntimeError(
            f"huggingface-hub is not installed; install: {INSTALL_HINT}"
        ) from exc
    try:
        path = hf_hub_download(
            hf_name, relpath, revision=revision, local_files_only=local_files_only
        )
    except Exception as exc:
        raise RuntimeError(
            f"onnx artefact {hf_name}/{relpath}@{revision} is not in the local "
            "Hugging Face cache; run the install/doctor/backfill path to fetch "
            f"it once (never mid-search): {type(exc).__name__}: {exc}"
        ) from exc
    return onnxruntime.InferenceSession(path, providers=["CPUExecutionProvider"])


class OnnxEncoder:
    """The :class:`Encoder` Protocol via onnxruntime, for the query side only.

    ``session`` and ``tokenizer`` are injection points: production code never
    passes them (both are loaded from the pinned artefact), tests always do
    (a fake tokenizer/session pair with the same shapes, so unit tests never
    download a model or touch the network -- council TEST SHAPE rule).
    """

    def __init__(
        self,
        model: str | None = None,
        *,
        local_files_only: bool = True,
        revision: str | None = None,
        session: Any | None = None,
        tokenizer: Any | None = None,
    ) -> None:
        from .embeddings import ONNX_ARTIFACTS, get_configured_model, get_model_config

        name = model or get_configured_model()
        artefact = ONNX_ARTIFACTS.get(name)
        if artefact is None:
            raise ValueError(
                f"no pinned ONNX artefact for model {name!r}; add it to "
                "embeddings.ONNX_ARTIFACTS before requesting the onnx backend"
            )
        config = get_model_config(name)
        self.name = name
        self.dim = int(config["dimensions"])
        self.max_tokens = int(config["max_tokens"])
        self.pooling = str(artefact.get("pooling", "cls"))
        self.revision = revision or str(artefact["revision"])
        hf_name = str(artefact["hf_name"])
        self._tokenizer = tokenizer or _load_tokenizer(
            hf_name, self.revision, local_files_only=local_files_only
        )
        self._session = session or _load_session(
            hf_name,
            str(artefact["onnx_relpath"]),
            self.revision,
            local_files_only=local_files_only,
        )

    def count_tokens(self, text: str) -> int:
        """Length of the sequence the model would actually see, special tokens included."""
        return len(self._tokenizer(text, add_special_tokens=True)["input_ids"])

    def encode(self, texts: Sequence[str]) -> list[bytes]:
        import numpy as np

        if not texts:
            return []
        encoded = self._tokenizer(
            list(texts),
            padding=True,
            truncation=True,
            max_length=self.max_tokens,
            return_tensors="np",
        )
        input_names = {item.name for item in self._session.get_inputs()}
        feed = {
            key: value.astype(np.int64)
            for key, value in encoded.items()
            if key in input_names
        }
        output_name = self._session.get_outputs()[0].name
        (last_hidden_state,) = self._session.run([output_name], feed)
        if self.pooling == "cls":
            pooled = last_hidden_state[:, 0, :]
        else:
            mask = feed["attention_mask"][:, :, None].astype(last_hidden_state.dtype)
            summed = (last_hidden_state * mask).sum(axis=1)
            counts = np.clip(mask.sum(axis=1), 1e-9, None)
            pooled = summed / counts
        norm = np.linalg.norm(pooled, axis=1, keepdims=True)
        norm = np.where(norm == 0, 1.0, norm)
        normalised = np.asarray(pooled / norm, dtype="<f4")
        if normalised.ndim != 2 or normalised.shape[1] != self.dim:
            raise RuntimeError(
                f"model {self.name} produced {normalised.shape[-1]}-dimensional "
                f"vectors, but the registry records dim={self.dim}"
            )
        return [row.tobytes() for row in normalised]


__all__ = ["OnnxEncoder"]
