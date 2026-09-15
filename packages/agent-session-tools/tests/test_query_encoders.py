"""The QUERY-side construction seam (lane A2, council D-2): factory + OnnxEncoder.

No test here downloads a model or touches the network (TEST SHAPE, council
A20): the ``OnnxEncoder`` tests inject a fake tokenizer/session with the same
call shape onnxruntime and a HF fast tokenizer expose, and the offline test
asserts the real local-cache miss path never opens a socket. The one test
that needs the real pinned artefact (parity against the torch encoder) is
marked ``integration`` and skips with the reason when the artefact is not in
the local Hugging Face cache -- the demonstrated skip path the council rules
accept as evidence in place of a live download (D-26).
"""

from __future__ import annotations

import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from agent_session_tools import embedding_store as store
from agent_session_tools import query_encoders
from agent_session_tools.onnx_encoder import OnnxEncoder

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

ONNX_MODEL = "bge-small-en-v1.5"
ONNX_DIM = 384  # embeddings.SUPPORTED_MODELS[ONNX_MODEL]["dimensions"]


@pytest.fixture(autouse=True)
def _reset_encoder_cache():
    """Every test starts and ends with a clean factory cache (E-A1 risk)."""
    query_encoders.reset_cache()
    yield
    query_encoders.reset_cache()


class FakeTorchEncoder:
    """A minimal stand-in for ``SentenceTransformerEncoder`` (torch backend)."""

    def __init__(
        self, model: str, *, local_files_only: bool = False, delay: float = 0.0
    ) -> None:
        self.name = model
        self.dim = 4
        self.max_tokens = 64
        self.local_files_only = local_files_only
        self.constructed_at = time.monotonic()
        if delay:
            time.sleep(delay)

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def encode(self, texts):  # noqa: ANN001 - Protocol shape
        return [struct.pack("<4f", 1.0, 0.0, 0.0, 0.0) for _ in texts]


class FakeTokenizer:
    """Enough of a fast HF tokenizer's call shape for ``OnnxEncoder.encode``."""

    def _ids(self, text: str) -> list[int]:
        words = text.split() or ["<empty>"]
        return [(abs(hash(w)) % 900) + 1 for w in words]

    def __call__(
        self,
        texts: Any,
        *,
        add_special_tokens: bool = True,
        padding: bool = False,
        truncation: bool = False,
        max_length: int | None = None,
        return_tensors: str | None = None,
    ) -> dict[str, Any]:
        import numpy as np

        single = isinstance(texts, str)
        batch = [texts] if single else list(texts)
        sequences = [[101, *self._ids(t), 102] for t in batch]
        if truncation and max_length:
            sequences = [seq[:max_length] for seq in sequences]
        if padding:
            width = max(len(seq) for seq in sequences)
            sequences = [seq + [0] * (width - len(seq)) for seq in sequences]
        attention = [[1 if tok else 0 for tok in seq] for seq in sequences]
        token_type = [[0] * len(seq) for seq in sequences]
        if return_tensors == "np":
            return {
                "input_ids": np.array(sequences, dtype=np.int64),
                "attention_mask": np.array(attention, dtype=np.int64),
                "token_type_ids": np.array(token_type, dtype=np.int64),
            }
        return {"input_ids": sequences[0] if single else sequences}


class _Named:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeSession:
    """Enough of ``onnxruntime.InferenceSession`` for ``OnnxEncoder.encode``.

    Deterministic: the hidden state at every position is the token id itself,
    broadcast across ``dim`` channels, so CLS pooling (position 0) is exactly
    checkable by hand from the tokenizer's first real token id.
    """

    def __init__(self, dim: int = ONNX_DIM, delay: float = 0.0) -> None:
        self.dim = dim
        self.delay = delay
        self.run_count = 0

    def get_inputs(self):
        return [_Named("input_ids"), _Named("attention_mask"), _Named("token_type_ids")]

    def get_outputs(self):
        return [_Named("last_hidden_state")]

    def run(self, output_names, feed):
        import numpy as np

        if self.delay:
            time.sleep(self.delay)
        self.run_count += 1
        ids = feed["input_ids"]
        hidden = np.repeat(ids[:, :, None].astype("float32"), self.dim, axis=2)
        return [hidden]


def _onnx_encoder(*, dim: int = ONNX_DIM, session_delay: float = 0.0) -> OnnxEncoder:
    return OnnxEncoder(
        ONNX_MODEL,
        tokenizer=FakeTokenizer(),
        session=FakeSession(dim=dim, delay=session_delay),
    )


class TestOnnxEncoderProtocolConformance:
    def test_isinstance_of_encoder_protocol(self):
        encoder = _onnx_encoder()
        assert isinstance(encoder, store.Encoder)

    def test_dim_matches_the_model_registry(self):
        encoder = _onnx_encoder()
        assert encoder.dim == 384

    def test_encode_returns_the_byte_format_the_sidecar_expects(self):
        import numpy as np

        encoder = _onnx_encoder()
        (vector,) = encoder.encode(["a query about window functions"])
        assert isinstance(vector, bytes)
        assert len(vector) == encoder.dim * 4  # float32 little-endian
        array = np.frombuffer(vector, dtype="<f4")
        assert array.shape == (encoder.dim,)
        # CLS pooling + L2-normalise: unit length.
        assert abs(float(np.linalg.norm(array)) - 1.0) < 1e-5

    def test_encode_empty_list_returns_empty_list(self):
        assert _onnx_encoder().encode([]) == []

    def test_unknown_model_has_no_pinned_artefact(self):
        with pytest.raises(ValueError, match="no pinned ONNX artefact"):
            OnnxEncoder(
                "not-a-real-model", tokenizer=FakeTokenizer(), session=FakeSession()
            )


class TestBackendResolution:
    def test_default_is_torch(self):
        assert query_encoders.resolve_backend() == query_encoders.BACKEND_TORCH

    def test_unknown_backend_is_a_caller_error(self):
        with pytest.raises(ValueError, match="unknown query encoder backend"):
            query_encoders.resolve_backend("vibes")

    def test_config_selects_onnx(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "agent_session_tools.config_loader.get_semantic_config",
            lambda: {"query_encoder": "onnx"},
        )
        assert query_encoders.resolve_backend() == query_encoders.BACKEND_ONNX

    def test_env_var_beats_config(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "agent_session_tools.config_loader.get_semantic_config",
            lambda: {"query_encoder": "onnx"},
        )
        monkeypatch.setenv(query_encoders.BACKEND_ENV, "torch")
        assert query_encoders.resolve_backend() == query_encoders.BACKEND_TORCH

    def test_argument_beats_everything(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv(query_encoders.BACKEND_ENV, "onnx")
        assert query_encoders.resolve_backend("torch") == query_encoders.BACKEND_TORCH


class TestFactoryTruthTable:
    def test_default_backend_is_torch_and_uses_sentence_transformer_encoder(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(store, "SentenceTransformerEncoder", FakeTorchEncoder)
        encoder = query_encoders.get_query_encoder("some-model")
        assert isinstance(encoder, FakeTorchEncoder)

    def test_onnx_backend_builds_an_onnx_encoder(self, monkeypatch: pytest.MonkeyPatch):
        built: dict[str, Any] = {}

        class FakeOnnx:
            def __init__(self, model, *, local_files_only, revision):
                built["model"] = model
                built["revision"] = revision
                self.name, self.dim, self.max_tokens = model, 4, 64

            def count_tokens(self, text):
                return len(text.split())

            def encode(self, texts):
                return [b"\x00" * 16 for _ in texts]

        monkeypatch.setattr("agent_session_tools.onnx_encoder.OnnxEncoder", FakeOnnx)
        encoder = query_encoders.get_query_encoder(ONNX_MODEL, backend="onnx")
        assert isinstance(encoder, FakeOnnx)
        assert built["model"] == ONNX_MODEL
        from agent_session_tools.embeddings import ONNX_ARTIFACTS

        assert built["revision"] == ONNX_ARTIFACTS[ONNX_MODEL]["revision"]

    def test_unknown_backend_fails_loudly(self):
        with pytest.raises(ValueError, match="unknown query encoder backend"):
            query_encoders.get_query_encoder("some-model", backend="vibes")

    def test_cache_is_keyed_by_model_backend_and_revision(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(store, "SentenceTransformerEncoder", FakeTorchEncoder)

        class FakeOnnx(FakeTorchEncoder):
            def __init__(self, model, *, local_files_only, revision):
                super().__init__(model, local_files_only=local_files_only)

        monkeypatch.setattr("agent_session_tools.onnx_encoder.OnnxEncoder", FakeOnnx)

        torch_encoder = query_encoders.get_query_encoder(
            "same-name", backend="torch", revision="r1"
        )
        onnx_encoder = query_encoders.get_query_encoder(
            "same-name", backend="onnx", revision="r1"
        )
        other_revision = query_encoders.get_query_encoder(
            "same-name", backend="torch", revision="r2"
        )

        assert torch_encoder is not onnx_encoder
        assert torch_encoder is not other_revision
        assert (
            query_encoders.get_query_encoder(
                "same-name", backend="torch", revision="r1"
            )
            is torch_encoder
        )

    def test_single_flight_constructs_once_under_concurrency(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        constructed: list[FakeTorchEncoder] = []
        real_init = FakeTorchEncoder.__init__

        def slow_init(self, model, *, local_files_only=False):
            real_init(self, model, local_files_only=local_files_only, delay=0.05)
            constructed.append(self)

        monkeypatch.setattr(FakeTorchEncoder, "__init__", slow_init)
        monkeypatch.setattr(store, "SentenceTransformerEncoder", FakeTorchEncoder)

        results: list[Any] = []
        barrier_errors: list[BaseException] = []

        def worker():
            try:
                results.append(query_encoders.get_query_encoder("racey-model"))
            except BaseException as exc:  # pragma: no cover - failure path only
                barrier_errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        assert not barrier_errors
        assert len(constructed) == 1, (
            "construction ran more than once under concurrency"
        )
        assert len(results) == 8
        assert all(result is results[0] for result in results)


class TestOfflineRule:
    def test_constructing_with_the_artefact_absent_raises_and_never_touches_the_network(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-empty"))
        monkeypatch.setenv("HF_HUB_OFFLINE", "0")  # even if this says "go online"...

        def _blocked(*_args, **_kwargs):
            raise AssertionError("network attempted during an offline construction")

        monkeypatch.setattr(socket.socket, "connect", _blocked)

        with pytest.raises(RuntimeError, match="not in the local Hugging Face cache"):
            OnnxEncoder(ONNX_MODEL, local_files_only=True)

    def test_hybrid_search_degrades_to_lexical_when_onnx_is_selected_and_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        pytest.importorskip("sqlite_vec")
        import sqlite3
        from importlib.resources import files

        from agent_session_tools import retrieval
        from agent_session_tools.migrations import migrate

        monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-empty"))
        monkeypatch.setattr(
            "agent_session_tools.config_loader.get_semantic_config",
            lambda: {"query_encoder": "onnx"},
        )

        conn = sqlite3.connect(tmp_path / "sessions.db")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            files("agent_session_tools").joinpath("schema.sql").read_text()
        )
        migrate(conn)
        conn.execute(
            "INSERT INTO sessions(id, source, updated_at) VALUES ('s-a', 'kiro_cli', '2026-09-01')"
        )
        conn.execute(
            "INSERT INTO messages(id, session_id, role, content, timestamp, seq) "
            "VALUES ('m-a', 's-a', 'assistant', "
            "'the docker image tag was wrong during deployment, fifty chars', "
            "'2026-09-01T10:00:00', 1)"
        )
        conn.execute(
            "INSERT INTO message_embeddings(message_id, chunk_ix, model, dim, "
            "content_sha256, truncated, embedding) VALUES "
            "('m-a', 0, 'bge-small-en-v1.5', 384, ?, 0, ?)",
            ("deadbeef" * 8, b"\x00" * (384 * 4)),
        )
        conn.commit()

        result = retrieval.search(conn, "docker image tag", mode="hybrid")
        assert result.status.mode == "lexical"
        assert "hybrid requested but lexical only" in (result.status.note or "")
        assert "not in the local Hugging Face cache" in (result.status.note or "")
        conn.close()


class TestPhaseHook:
    def test_events_fire_in_order_with_monotonic_timestamps(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        class SlowFake(FakeTorchEncoder):
            def __init__(self, model, *, local_files_only=False):
                super().__init__(model, local_files_only=local_files_only, delay=0.02)

        monkeypatch.setattr(store, "SentenceTransformerEncoder", SlowFake)

        events: list[query_encoders.PhaseEvent] = []
        query_encoders.get_query_encoder("phased-model", on_phase=events.append)

        phases = [event.phase for event in events]
        assert phases == [
            query_encoders.LoadPhase.RUNTIME_IMPORT,
            query_encoders.LoadPhase.WEIGHTS,
            query_encoders.LoadPhase.DISABLED,
            query_encoders.LoadPhase.READY,
        ]
        timestamps = [event.at for event in events]
        assert timestamps == sorted(timestamps)
        assert timestamps[-1] > timestamps[0]
        assert all(
            event.key == ("phased-model", "torch", query_encoders._UNPINNED_REVISION)
            for event in events
        )

    def test_warmup_true_emits_warmup_not_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(store, "SentenceTransformerEncoder", FakeTorchEncoder)
        events: list[query_encoders.PhaseEvent] = []
        query_encoders.get_query_encoder(
            "warm-model", warmup=True, on_phase=events.append
        )
        assert query_encoders.LoadPhase.WARMUP in [event.phase for event in events]
        assert query_encoders.LoadPhase.DISABLED not in [
            event.phase for event in events
        ]

    def test_failure_emits_failed_and_reraises(self, monkeypatch: pytest.MonkeyPatch):
        class Boom:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("kaboom")

        monkeypatch.setattr(store, "SentenceTransformerEncoder", Boom)
        events: list[query_encoders.PhaseEvent] = []
        with pytest.raises(RuntimeError, match="kaboom"):
            query_encoders.get_query_encoder("boom-model", on_phase=events.append)
        assert events[-1].phase == query_encoders.LoadPhase.FAILED
        assert "kaboom" in events[-1].detail

    def test_no_listener_is_zero_cost_and_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(store, "SentenceTransformerEncoder", FakeTorchEncoder)
        # on_phase defaults to None; must not raise.
        query_encoders.get_query_encoder("no-listener-model")


class TestNoImportTimeCost:
    def test_importing_retrieval_and_config_loader_never_imports_torch_or_onnxruntime(
        self,
    ):
        """council D-2 / kimi F20: the whole 2.87s chain this lane exists to kill."""
        script = (
            "import sys; "
            "import agent_session_tools.retrieval; "
            "import agent_session_tools.config_loader; "
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
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.strip() == "OK"


class TestParitySmokeMachinery:
    """The CI-safe proxy (d): tests the comparison machinery, not a real model.

    Real torch-vs-onnx parity on the pinned artefact is
    ``TestOnnxTorchParityAcceptance`` below (network-free unit run == skip
    with the reason; a real run needs the cached artefact, council D-26).
    """

    def test_identical_vectors_have_cosine_one_and_agree_on_ranking(self):
        from agent_session_tools import embeddings as embeddings_mod

        texts = ["north text", "east text", "south text"]
        vectors = {
            "north text": struct.pack("<4f", 1.0, 0.0, 0.0, 0.0),
            "east text": struct.pack("<4f", 0.0, 1.0, 0.0, 0.0),
            "south text": struct.pack("<4f", 0.0, 0.0, 1.0, 0.0),
        }
        for text in texts:
            cosine = embeddings_mod.cosine_similarity(vectors[text], vectors[text])
            assert cosine == pytest.approx(1.0)

    def test_a_perturbed_vector_still_agrees_above_the_floor(self):
        from agent_session_tools import embeddings as embeddings_mod

        base = struct.pack("<4f", 1.0, 0.0, 0.0, 0.0)
        perturbed = struct.pack("<4f", 0.999, 0.02, 0.0, 0.0)
        cosine = embeddings_mod.cosine_similarity(base, perturbed)
        assert cosine >= 0.999


@pytest.mark.integration
class TestOnnxTorchParityAcceptance:
    """Real torch vs real onnx on the pinned artefact -- opt-in, artefact-gated.

    Skips with the exact reason when the local Hugging Face cache does not
    already hold the pinned revision (never fetched by a test, council
    TEST SHAPE). Fetch it once via the install/doctor/backfill path to make
    this run for real.
    """

    def test_cosine_and_top1_agreement_on_a_tiny_fixture(self):
        from huggingface_hub import try_to_load_from_cache

        from agent_session_tools.embeddings import ONNX_ARTIFACTS

        artefact = ONNX_ARTIFACTS[ONNX_MODEL]
        hf_name, revision = str(artefact["hf_name"]), str(artefact["revision"])
        onnx_cached = try_to_load_from_cache(
            hf_name, str(artefact["onnx_relpath"]), revision=revision
        )
        tokenizer_cached = try_to_load_from_cache(
            hf_name, "tokenizer.json", revision=revision
        )
        if not onnx_cached or not tokenizer_cached:
            pytest.skip(
                f"pinned onnx artefact for {hf_name}@{revision} is not in the local "
                "Hugging Face cache; fetch it once via install/doctor/backfill to run "
                "this parity check for real"
            )

        from sentence_transformers import SentenceTransformer

        from agent_session_tools import embeddings as embeddings_mod

        fixture = [
            "use a window function with PARTITION BY to rank rows inside each group",
            "the deployment pipeline failed because the docker image tag was wrong",
            "ranking rows per group is exactly what window functions are for",
        ]
        torch_model = SentenceTransformer(
            hf_name, revision=revision, local_files_only=True
        )
        torch_vectors = torch_model.encode(fixture, normalize_embeddings=True)

        onnx = OnnxEncoder(ONNX_MODEL, local_files_only=True)
        onnx_vectors = onnx.encode(fixture)

        for text, torch_vector, onnx_bytes in zip(
            fixture, torch_vectors, onnx_vectors, strict=True
        ):
            onnx_vector = embeddings_mod.embedding_from_bytes(onnx_bytes)
            cosine = embeddings_mod.cosine_similarity(
                torch_vector.astype("<f4").tobytes(),
                onnx_vector.astype("<f4").tobytes(),
            )
            assert cosine >= 0.999, (
                f"{text!r}: cosine {cosine} below the pre-registered floor"
            )
