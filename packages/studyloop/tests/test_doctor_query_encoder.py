"""``doctor``'s ``query_encoder_artefact`` check (lane A5).

Model-free and extension-free, matching ``test_doctor_embeddings.py``'s
convention: backend resolution and cache probing are both monkeypatched, so
the truth table below is identical on a machine with the semantic extra
installed and one without (the ``find_spec`` probe is patched too).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _semantic_layer_present(monkeypatch: pytest.MonkeyPatch):
    """Every test in this file assumes the semantic extra IS installed;
    the "no semantic layer" skip gets its own dedicated test below with the
    probe patched the other way."""
    monkeypatch.setattr(
        "importlib.util.find_spec",
        lambda name: object() if name == "sentence_transformers" else None,
    )


class TestNoSemanticLayer:
    def test_skips_with_info_when_sentence_transformers_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
        from studyloop.doctor.query_encoder import check_query_encoder_artefact

        (result,) = check_query_encoder_artefact()
        assert result.status == "info"
        assert result.category == "deps"
        assert result.name == "query_encoder_artefact"


class TestTorchConfigured:
    def test_skips_with_info_when_backend_is_torch(self, monkeypatch: pytest.MonkeyPatch):
        from agent_session_tools import query_encoders

        monkeypatch.setattr(query_encoders, "resolve_backend", lambda: "torch")
        from studyloop.doctor.query_encoder import check_query_encoder_artefact

        (result,) = check_query_encoder_artefact()
        assert result.status == "info"
        assert "torch" in result.message


class TestOnnxConfigured:
    def test_pass_when_cached_and_verified(self, monkeypatch: pytest.MonkeyPatch):
        from agent_session_tools import query_encoders
        from agent_session_tools.artefact_fetch import CacheCheck

        monkeypatch.setattr(query_encoders, "resolve_backend", lambda: "onnx")
        monkeypatch.setattr(
            "agent_session_tools.artefact_fetch.check_cached_artefact",
            lambda model=None: CacheCheck(
                model="bge-small-en-v1.5",
                hf_name="BAAI/bge-small-en-v1.5",
                revision="5c38ec7",
                status="pass",
            ),
        )
        from studyloop.doctor.query_encoder import check_query_encoder_artefact

        (result,) = check_query_encoder_artefact()
        assert result.status == "pass"
        assert result.fix_auto is False

    def test_warn_when_backend_resolves_to_onnx_but_artefact_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        from agent_session_tools import query_encoders
        from agent_session_tools.artefact_fetch import FETCH_COMMAND, CacheCheck

        monkeypatch.setattr(query_encoders, "resolve_backend", lambda: "onnx")
        monkeypatch.setattr(
            "agent_session_tools.artefact_fetch.check_cached_artefact",
            lambda model=None: CacheCheck(
                model="bge-small-en-v1.5",
                hf_name="BAAI/bge-small-en-v1.5",
                revision="5c38ec7",
                status="warn",
                detail="not cached: onnx/model.onnx",
            ),
        )
        from studyloop.doctor.query_encoder import check_query_encoder_artefact

        (result,) = check_query_encoder_artefact()
        assert result.status == "warn"
        assert result.fix_auto is True
        assert FETCH_COMMAND in result.fix_hint
        assert "bge-small-en-v1.5" in result.message

    def test_fail_when_cached_but_sha_mismatch(self, monkeypatch: pytest.MonkeyPatch):
        from agent_session_tools import query_encoders
        from agent_session_tools.artefact_fetch import CacheCheck

        monkeypatch.setattr(query_encoders, "resolve_backend", lambda: "onnx")
        monkeypatch.setattr(
            "agent_session_tools.artefact_fetch.check_cached_artefact",
            lambda model=None: CacheCheck(
                model="bge-small-en-v1.5",
                hf_name="BAAI/bge-small-en-v1.5",
                revision="5c38ec7",
                status="fail",
                detail="sha256 mismatch: onnx/model.onnx",
            ),
        )
        from studyloop.doctor.query_encoder import check_query_encoder_artefact

        (result,) = check_query_encoder_artefact()
        assert result.status == "fail"
        assert result.fix_auto is True

    def test_warn_when_onnx_configured_but_model_has_no_pinned_artefact(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """A ``query_encoder: onnx`` config paired with a model that has no
        entry in ``embeddings.ONNX_ARTIFACTS`` (e.g. the default
        all-mpnet-base-v2) must warn with real remediation, not crash the
        checker as an unhandled ValueError (E-A5 finding 4)."""
        from agent_session_tools import query_encoders

        monkeypatch.setattr(query_encoders, "resolve_backend", lambda: "onnx")
        monkeypatch.setattr(
            "agent_session_tools.artefact_fetch.resolve_fetch_model",
            lambda model=None: "all-mpnet-base-v2",
        )

        def _boom(model=None):
            raise ValueError("no pinned ONNX artefact for model 'all-mpnet-base-v2'")

        monkeypatch.setattr("agent_session_tools.artefact_fetch.check_cached_artefact", _boom)
        from studyloop.doctor.query_encoder import check_query_encoder_artefact

        (result,) = check_query_encoder_artefact()
        assert result.status == "warn"
        assert result.fix_auto is False
        assert "all-mpnet-base-v2" in result.message
        assert "Report this bug" not in result.message


class TestAutoBackendConcretisesPerModel:
    """Reconciles this check with wave-1's ``auto`` backend (council finding
    A5-1): ``BACKEND_AUTO``/``_concretise`` do not exist on this lane's base
    ref yet, so these tests add them via monkeypatch to prove the check
    reconciles automatically once that lane lands, instead of comparing the
    un-concretised backend string against ``onnx`` and going silent on
    exactly the shipped-default configuration this lane exists to protect.
    """

    def test_auto_concretising_to_onnx_for_this_model_is_checked(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        from agent_session_tools import query_encoders
        from agent_session_tools.artefact_fetch import FETCH_COMMAND, CacheCheck

        monkeypatch.setattr(query_encoders, "resolve_backend", lambda: "auto")
        monkeypatch.setattr(
            query_encoders, "_concretise", lambda model, backend: "onnx", raising=False
        )
        monkeypatch.setattr(
            "agent_session_tools.artefact_fetch.resolve_fetch_model",
            lambda model=None: "bge-small-en-v1.5",
        )
        monkeypatch.setattr(
            "agent_session_tools.artefact_fetch.check_cached_artefact",
            lambda model=None: CacheCheck(
                model="bge-small-en-v1.5",
                hf_name="BAAI/bge-small-en-v1.5",
                revision="5c38ec7",
                status="warn",
                detail="not cached: onnx/model.onnx",
            ),
        )
        from studyloop.doctor.query_encoder import check_query_encoder_artefact

        (result,) = check_query_encoder_artefact()
        assert result.status == "warn"
        assert result.fix_auto is True
        assert FETCH_COMMAND in result.fix_hint

    def test_auto_concretising_to_torch_for_this_model_is_info(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        from agent_session_tools import query_encoders

        monkeypatch.setattr(query_encoders, "resolve_backend", lambda: "auto")
        monkeypatch.setattr(
            query_encoders, "_concretise", lambda model, backend: "torch", raising=False
        )
        monkeypatch.setattr(
            "agent_session_tools.artefact_fetch.resolve_fetch_model",
            lambda model=None: "all-mpnet-base-v2",
        )
        from studyloop.doctor.query_encoder import check_query_encoder_artefact

        (result,) = check_query_encoder_artefact()
        assert result.status == "info"


class TestDoctorFixInvokesTheFetch:
    def test_apply_fixes_calls_fetch_query_encoder_artefact(self, monkeypatch: pytest.MonkeyPatch):
        from studyloop.cli._doctor import _apply_fixes
        from studyloop.doctor.models import CheckResult

        calls = []

        def fake_fetch(model=None):
            calls.append(model)
            from agent_session_tools.artefact_fetch import FetchResult

            return FetchResult(
                model="bge-small-en-v1.5",
                hf_name="BAAI/bge-small-en-v1.5",
                revision="5c38ec7",
                status="fetched",
            )

        monkeypatch.setattr(
            "agent_session_tools.artefact_fetch.fetch_query_encoder_artefact",
            fake_fetch,
        )

        results = [
            CheckResult(
                "deps",
                "query_encoder_artefact",
                "warn",
                "backend would resolve to onnx but the artefact is absent",
                "session-maint fetch-query-encoder",
                fix_auto=True,
            )
        ]
        actions = _apply_fixes(results)
        assert calls == [None]
        assert any("query encoder artefact" in a for a in actions)

    def test_apply_fixes_raises_install_error_on_verification_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        from studyloop.cli._doctor import _apply_fixes
        from studyloop.doctor.models import CheckResult
        from studyloop.installers import InstallError

        def fake_fetch(model=None):
            from agent_session_tools.artefact_fetch import ArtefactVerificationError

            raise ArtefactVerificationError("sha256 mismatch: onnx/model.onnx")

        monkeypatch.setattr(
            "agent_session_tools.artefact_fetch.fetch_query_encoder_artefact",
            fake_fetch,
        )

        results = [
            CheckResult(
                "deps",
                "query_encoder_artefact",
                "fail",
                "sha mismatch",
                "session-maint fetch-query-encoder",
                fix_auto=True,
            )
        ]
        with pytest.raises(InstallError):
            _apply_fixes(results)
