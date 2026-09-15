"""``session-maint fetch-query-encoder`` CLI wiring (lane A5).

The fetch/verify mechanics are ``artefact_fetch.fetch_query_encoder_artefact``,
tested directly in ``test_artefact_fetch.py``. This file only proves the CLI
command calls through and maps each outcome to its own exit code -- the
underlying function is monkeypatched so no test here touches the network.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from agent_session_tools import artefact_fetch
from agent_session_tools.maintenance import app

runner = CliRunner()


def _fake_result(status, files=()):
    return artefact_fetch.FetchResult(
        model="bge-small-en-v1.5",
        hf_name="BAAI/bge-small-en-v1.5",
        revision="5c38ec7",
        status=status,
        files=files,
        detail=""
        if status != "offline_skip"
        else "HF_HUB_OFFLINE=1 is set; not fetching.",
    )


class TestFetchQueryEncoderCommand:
    def test_already_cached_exits_zero(self, monkeypatch):
        monkeypatch.setattr(
            "agent_session_tools.artefact_fetch.fetch_query_encoder_artefact",
            lambda model=None: _fake_result("already_cached"),
        )
        result = runner.invoke(app, ["fetch-query-encoder"])
        assert result.exit_code == 0
        assert "Already cached" in result.output

    def test_fetched_exits_three(self, monkeypatch):
        fetched_file = artefact_fetch.FetchedFile(
            relpath="onnx/model.onnx",
            path=Path("/fake/hf/cache/onnx_model.onnx"),
            sha256="abc",
            size_bytes=1024,
        )
        monkeypatch.setattr(
            "agent_session_tools.artefact_fetch.fetch_query_encoder_artefact",
            lambda model=None: _fake_result("fetched", files=(fetched_file,)),
        )
        result = runner.invoke(app, ["fetch-query-encoder"])
        assert result.exit_code == 3
        assert "Fetched" in result.output
        assert "onnx/model.onnx" in result.output
        # what/where/size, not just what/size (E-A5 finding 5): the local
        # cache path the artefact actually landed at must be printed too.
        assert "/fake/hf/cache/onnx_model.onnx" in result.output

    def test_offline_skip_exits_four(self, monkeypatch):
        monkeypatch.setattr(
            "agent_session_tools.artefact_fetch.fetch_query_encoder_artefact",
            lambda model=None: _fake_result("offline_skip"),
        )
        result = runner.invoke(app, ["fetch-query-encoder"])
        assert result.exit_code == 4
        assert "HF_HUB_OFFLINE" in result.output

    def test_verification_failure_exits_one(self, monkeypatch):
        def _boom(model=None):
            raise artefact_fetch.ArtefactVerificationError(
                "sha256 mismatch: onnx/model.onnx"
            )

        monkeypatch.setattr(
            "agent_session_tools.artefact_fetch.fetch_query_encoder_artefact", _boom
        )
        result = runner.invoke(app, ["fetch-query-encoder"])
        assert result.exit_code == 1
        assert "sha256 mismatch" in result.output

    def test_unknown_model_exits_one(self, monkeypatch):
        def _boom(model=None):
            raise ValueError("no pinned ONNX artefact for model 'nope'")

        monkeypatch.setattr(
            "agent_session_tools.artefact_fetch.fetch_query_encoder_artefact", _boom
        )
        result = runner.invoke(app, ["fetch-query-encoder", "--model", "nope"])
        assert result.exit_code == 1
        assert "no pinned ONNX artefact" in result.output

    def test_model_option_is_passed_through(self, monkeypatch):
        received = {}

        def fake(model=None):
            received["model"] = model
            return _fake_result("already_cached")

        monkeypatch.setattr(
            "agent_session_tools.artefact_fetch.fetch_query_encoder_artefact", fake
        )
        runner.invoke(app, ["fetch-query-encoder", "--model", "bge-small-en-v1.5"])
        assert received["model"] == "bge-small-en-v1.5"
