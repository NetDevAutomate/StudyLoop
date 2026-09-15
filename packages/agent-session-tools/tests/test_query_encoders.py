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

import huggingface_hub.constants
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


def _isolate_hf_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point every already-imported HF cache lookup at an empty directory.

    ``HF_HUB_CACHE`` is computed from ``HF_HOME`` at *import* time
    (``huggingface_hub.constants``), and ``huggingface_hub`` is already
    imported by the time these tests run -- so ``monkeypatch.setenv("HF_HOME",
    ...)`` alone is a no-op: ``hf_hub_download`` and
    ``AutoTokenizer.from_pretrained`` both resolve their cache directory via
    ``constants.HF_HUB_CACHE`` (a qualified module-attribute lookup at call
    time, verified against the installed huggingface_hub/transformers), so
    patching the constant itself is what actually isolates them from the
    owner's real cache (repo TEST SHAPE rule: patch the constant the code
    reads, not the environment variable it was computed from).
    """
    empty_cache = tmp_path / "hf-empty"
    monkeypatch.setattr(huggingface_hub.constants, "HF_HUB_CACHE", str(empty_cache))


class TestOfflineRule:
    def test_constructing_with_the_artefact_absent_raises_and_never_touches_the_network(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        _isolate_hf_cache(monkeypatch, tmp_path)
        monkeypatch.setenv("HF_HUB_OFFLINE", "0")  # even if this says "go online"...

        def _blocked(*_args, **_kwargs):
            raise AssertionError("network attempted during an offline construction")

        monkeypatch.setattr(socket.socket, "connect", _blocked)

        with pytest.raises(RuntimeError, match="not in the local Hugging Face cache"):
            OnnxEncoder(ONNX_MODEL, local_files_only=True)

    def test_a_hybrid_query_degrades_to_lexical_when_onnx_is_selected_and_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        pytest.importorskip("sqlite_vec")
        import sqlite3
        from importlib.resources import files

        from agent_session_tools import retrieval
        from agent_session_tools.migrations import migrate

        _isolate_hf_cache(monkeypatch, tmp_path)
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

    def test_importing_embeddings_never_imports_an_ml_runtime(self):
        """The ONNX ctor reads ``embeddings.ONNX_ARTIFACTS``; an eager
        sentence-transformers probe there measured 2.1 s -- the whole load
        budget. Availability is probed with ``find_spec``, never by importing.
        """
        script = (
            "import sys; "
            "import agent_session_tools.embeddings as e; "
            "assert 'torch' not in sys.modules, 'torch imported at import time'; "
            "assert 'sentence_transformers' not in sys.modules, "
            "'sentence_transformers imported at import time'; "
            "assert 'transformers' not in sys.modules, "
            "'transformers imported at import time'; "
            "assert isinstance(e.is_available(), bool); "
            "assert 'sentence_transformers' not in sys.modules, "
            "'is_available() must probe without importing'; "
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

    def test_cosine_of_a_vector_with_itself_is_one(self):
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

    @staticmethod
    def _rank_by_cosine(query: bytes, corpus: dict[str, bytes]) -> list[str]:
        from agent_session_tools import embeddings as embeddings_mod

        return sorted(
            corpus,
            key=lambda text: -embeddings_mod.cosine_similarity(query, corpus[text]),
        )

    def test_ranking_by_cosine_is_identical_between_a_reference_and_a_perturbed_arm(
        self,
    ):
        """The ranking half of parity smoke (d), missing until now: a per-text
        perturbation that stays above the pre-registered cosine floor
        (>= 0.999) -- the torch-vs-onnx worst case this lane exists to bound
        -- must not change the ranked order over the fixture corpus. This is
        the exact asymmetry risk the parity gate exists to catch: a query
        vector from a different runtime than the corpus vectors changes
        ranking even when every individual vector still "agrees".
        """
        from agent_session_tools import embeddings as embeddings_mod

        query = struct.pack("<4f", 1.0, 0.0, 0.0, 0.0)
        reference_arm = {
            "closest text": struct.pack("<4f", 0.98, 0.20, 0.0, 0.0),
            "middle text": struct.pack("<4f", 0.70, 0.71, 0.0, 0.0),
            "farthest text": struct.pack("<4f", 0.10, 0.99, 0.10, 0.0),
        }
        # Stand-in for a second backend's output on the same texts: each
        # vector nudged just enough to probe the floor, not to define it.
        perturbed_arm = {
            "closest text": struct.pack("<4f", 0.981, 0.194, 0.001, 0.0),
            "middle text": struct.pack("<4f", 0.699, 0.712, -0.002, 0.001),
            "farthest text": struct.pack("<4f", 0.101, 0.988, 0.101, -0.001),
        }

        for text in reference_arm:
            cosine = embeddings_mod.cosine_similarity(
                reference_arm[text], perturbed_arm[text]
            )
            assert cosine >= 0.999, f"{text!r}: perturbation floor violated ({cosine})"

        reference_ranking = self._rank_by_cosine(query, reference_arm)
        perturbed_ranking = self._rank_by_cosine(query, perturbed_arm)
        assert reference_ranking == perturbed_ranking
        assert reference_ranking == ["closest text", "middle text", "farthest text"]


@pytest.mark.integration
class TestOnnxTorchParityAcceptance:
    """Real torch vs real onnx on the pinned artefact -- opt-in, artefact-gated.

    Skips with the exact reason when the local Hugging Face cache does not
    already hold the pinned revision (never fetched by a test, council
    TEST SHAPE). Fetch it once via the install/doctor/backfill path to make
    this run for real.
    """

    def test_cosine_and_ranking_agree_between_torch_and_onnx_on_a_tiny_fixture(self):
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
        query = "how do I rank rows within each group using a window function"
        torch_model = SentenceTransformer(
            hf_name, revision=revision, local_files_only=True
        )
        torch_vectors = torch_model.encode(fixture, normalize_embeddings=True)
        torch_query_vector = torch_model.encode([query], normalize_embeddings=True)[0]

        onnx = OnnxEncoder(ONNX_MODEL, local_files_only=True)
        onnx_vectors = onnx.encode(fixture)
        (onnx_query_bytes,) = onnx.encode([query])

        torch_corpus: dict[str, bytes] = {}
        onnx_corpus: dict[str, bytes] = {}
        for text, torch_vector, onnx_bytes in zip(
            fixture, torch_vectors, onnx_vectors, strict=True
        ):
            torch_bytes = torch_vector.astype("<f4").tobytes()
            onnx_vector = embeddings_mod.embedding_from_bytes(onnx_bytes)
            cosine = embeddings_mod.cosine_similarity(
                torch_bytes,
                onnx_vector.astype("<f4").tobytes(),
            )
            assert cosine >= 0.999, (
                f"{text!r}: cosine {cosine} below the pre-registered floor"
            )
            torch_corpus[text] = torch_bytes
            onnx_corpus[text] = onnx_bytes

        # The ranking half of parity (deliverable 3.iii's CI-safe proxy): the
        # two arms must agree on the ORDER of the fixture corpus against a
        # query, not just per-text cosine -- that is the asymmetry risk a
        # cosine-only check cannot see.
        torch_ranking = TestParitySmokeMachinery._rank_by_cosine(
            torch_query_vector.astype("<f4").tobytes(), torch_corpus
        )
        onnx_ranking = TestParitySmokeMachinery._rank_by_cosine(
            onnx_query_bytes, onnx_corpus
        )
        assert torch_ranking == onnx_ranking, (
            f"ranked order diverged: torch={torch_ranking!r} onnx={onnx_ranking!r}"
        )


class TestRustTokenizerAdapter:
    """The tokenizer rides the Rust ``tokenizers`` library, not transformers.

    ``AutoTokenizer`` construction measured ~2.0 s of the encoder's ~2.2 s
    cold load -- the bulk of the very cost lane A2 exists to kill (the signed
    load gate is < 0.5 s). The adapter wraps the pinned ``tokenizer.json``
    (whose sha256 the registry records) and speaks just enough of the
    transformers call convention that ``OnnxEncoder`` and the injected test
    fakes are unchanged.
    """

    def _tiny_tokenizer(self):
        from tokenizers import Tokenizer
        from tokenizers.models import WordPiece
        from tokenizers.pre_tokenizers import Whitespace

        vocab = {
            "[UNK]": 0,
            "[CLS]": 1,
            "[SEP]": 2,
            "[PAD]": 3,
            "rank": 4,
            "rows": 5,
            "group": 6,
            "window": 7,
        }
        tokenizer = Tokenizer(WordPiece(vocab, unk_token="[UNK]"))
        tokenizer.pre_tokenizer = Whitespace()
        return tokenizer

    def _adapter(self):
        from agent_session_tools.onnx_encoder import _RustTokenizer

        return _RustTokenizer(self._tiny_tokenizer())

    def test_batch_call_returns_int64_arrays_padded_to_equal_length(self):
        import numpy as np

        encoded = self._adapter()(
            ["rank rows", "rank"],
            padding=True,
            truncation=True,
            max_length=8,
            return_tensors="np",
        )
        assert set(encoded) >= {"input_ids", "attention_mask"}
        for key in ("input_ids", "attention_mask"):
            value = encoded[key]
            assert isinstance(value, np.ndarray) and value.dtype == np.int64
            assert value.shape[0] == 2
        ids = encoded["input_ids"]
        mask = encoded["attention_mask"]
        assert ids.shape == mask.shape
        # The shorter text is padded and its padding is masked out.
        assert int(mask[0].sum()) > int(mask[1].sum())

    def test_truncation_cuts_to_max_length(self):
        encoded = self._adapter()(
            ["rank rows group window rank rows group window"],
            padding=True,
            truncation=True,
            max_length=4,
            return_tensors="np",
        )
        assert encoded["input_ids"].shape[1] == 4

    def test_single_string_path_serves_count_tokens(self):
        encoded = self._adapter()("rank rows group")
        assert len(encoded["input_ids"]) == 3

    def test_load_tokenizer_never_imports_transformers(self):
        """Cache-gated like the parity acceptance test: skip without the pin."""
        from huggingface_hub import try_to_load_from_cache

        from agent_session_tools.embeddings import ONNX_ARTIFACTS

        artefact = ONNX_ARTIFACTS[ONNX_MODEL]
        hf_name, revision = str(artefact["hf_name"]), str(artefact["revision"])
        if not try_to_load_from_cache(hf_name, "tokenizer.json", revision=revision):
            pytest.skip(
                f"pinned tokenizer for {hf_name}@{revision} is not in the local "
                "Hugging Face cache; fetch it once via install/doctor/backfill"
            )
        code = (
            "import sys\n"
            "from agent_session_tools.onnx_encoder import _load_tokenizer\n"
            f"tok = _load_tokenizer({hf_name!r}, {revision!r}, local_files_only=True)\n"
            "ids = tok('a small parity check sentence')['input_ids']\n"
            "assert len(ids) > 0\n"
            "assert 'transformers' not in sys.modules, 'transformers was imported'\n"
            "print('OK')\n"
        )
        import os

        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env={**os.environ, "HF_HUB_OFFLINE": "1"},
        )
        assert done.returncode == 0 and "OK" in done.stdout, done.stderr
