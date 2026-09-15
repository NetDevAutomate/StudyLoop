"""The explicit ONNX query-encoder artefact fetch path (lane A5).

TEST SHAPE (council A20): every ``hf_hub_download``/``try_to_load_from_cache``
call is patched -- no test here touches the network or a real Hugging Face
cache. ``ONNX_ARTIFACTS`` is monkeypatched with a small fixture entry so a
wrong-sha fixture can prove verification actually runs.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from agent_session_tools import artefact_fetch

FAKE_MODEL = "fake-test-model"
ONNX_BYTES = b"pretend onnx graph bytes"
TOKENIZER_BYTES = b"pretend tokenizer.json bytes"
TOKENIZER_CONFIG_BYTES = b"pretend tokenizer_config.json bytes"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fake_artefact() -> dict[str, object]:
    return {
        "hf_name": "fake-org/fake-model",
        "revision": "deadbeefcafe",
        "onnx_relpath": "onnx/model.onnx",
        "onnx_sha256": _sha(ONNX_BYTES),
        "onnx_size_bytes": len(ONNX_BYTES),
        "tokenizer_sha256": _sha(TOKENIZER_BYTES),
        "tokenizer_config_sha256": _sha(TOKENIZER_CONFIG_BYTES),
        "pooling": "cls",
    }


@pytest.fixture(autouse=True)
def _fake_registry(monkeypatch: pytest.MonkeyPatch):
    from agent_session_tools import embeddings

    monkeypatch.setitem(embeddings.ONNX_ARTIFACTS, FAKE_MODEL, _fake_artefact())


def _content_for(relpath: str) -> bytes:
    return {
        "onnx/model.onnx": ONNX_BYTES,
        "tokenizer.json": TOKENIZER_BYTES,
        "tokenizer_config.json": TOKENIZER_CONFIG_BYTES,
    }[relpath]


def _install_fake_downloader(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    calls: list[dict[str, Any]],
    *,
    content_overrides: dict[str, bytes] | None = None,
) -> None:
    overrides = content_overrides or {}

    def fake_download(
        repo_id, filename, *, revision, local_files_only, force_download=False
    ):
        calls.append(
            {
                "repo_id": repo_id,
                "filename": filename,
                "revision": revision,
                "local_files_only": local_files_only,
                "force_download": force_download,
            }
        )
        content = overrides.get(filename, _content_for(filename))
        dest = tmp_path / filename.replace("/", "_")
        dest.write_bytes(content)
        return str(dest)

    monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_download)


class TestResolveFetchModel:
    def test_explicit_argument_wins(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "agent_session_tools.retrieval._pinned_db_model", lambda: "db-model"
        )
        assert artefact_fetch.resolve_fetch_model("arg-model") == "arg-model"

    def test_falls_back_to_db_pin_when_no_argument(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(
            "agent_session_tools.retrieval._pinned_db_model", lambda: "db-model"
        )
        assert artefact_fetch.resolve_fetch_model(None) == "db-model"

    def test_falls_back_to_configured_model_when_no_db_pin(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(
            "agent_session_tools.retrieval._pinned_db_model", lambda: None
        )
        monkeypatch.setattr(
            "agent_session_tools.config_loader.get_embedding_model",
            lambda: "configured-model",
        )
        assert artefact_fetch.resolve_fetch_model(None) == "configured-model"


class TestFetchQueryEncoderArtefact:
    def test_unknown_model_raises_value_error(self):
        with pytest.raises(ValueError, match="no pinned ONNX artefact"):
            artefact_fetch.fetch_query_encoder_artefact("not-a-real-model")

    def test_fetches_and_verifies_every_pinned_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        calls: list[dict[str, Any]] = []
        _install_fake_downloader(monkeypatch, tmp_path, calls)
        monkeypatch.setattr(
            "huggingface_hub.try_to_load_from_cache", lambda *a, **k: False
        )

        result = artefact_fetch.fetch_query_encoder_artefact(FAKE_MODEL)

        assert result.status == "fetched"
        assert result.model == FAKE_MODEL
        assert result.hf_name == "fake-org/fake-model"
        assert result.revision == "deadbeefcafe"
        assert {f.relpath for f in result.files} == {
            "onnx/model.onnx",
            "tokenizer.json",
            "tokenizer_config.json",
        }
        assert result.total_bytes == len(ONNX_BYTES) + len(TOKENIZER_BYTES) + len(
            TOKENIZER_CONFIG_BYTES
        )
        # argv asserted: every call named the pinned repo/revision and never
        # asked for local-files-only (this function IS the fetch path).
        assert len(calls) == 3
        for call in calls:
            assert call["repo_id"] == "fake-org/fake-model"
            assert call["revision"] == "deadbeefcafe"
            assert call["local_files_only"] is False
        assert {c["filename"] for c in calls} == {
            "onnx/model.onnx",
            "tokenizer.json",
            "tokenizer_config.json",
        }

    def test_already_cached_status_when_every_file_was_cached_before_the_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        calls: list[dict[str, Any]] = []
        _install_fake_downloader(monkeypatch, tmp_path, calls)
        monkeypatch.setattr(
            "huggingface_hub.try_to_load_from_cache", lambda *a, **k: "irrelevant"
        )

        result = artefact_fetch.fetch_query_encoder_artefact(FAKE_MODEL)

        assert result.status == "already_cached"

    def test_wrong_sha_fixture_fails_verification(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # Same length as ONNX_BYTES so this exercises the sha256 check
        # specifically, not the (now earlier-running) size check.
        corrupted = bytes(b ^ 0xFF for b in ONNX_BYTES)
        assert len(corrupted) == len(ONNX_BYTES)
        calls: list[dict[str, Any]] = []
        _install_fake_downloader(
            monkeypatch,
            tmp_path,
            calls,
            content_overrides={"onnx/model.onnx": corrupted},
        )
        monkeypatch.setattr(
            "huggingface_hub.try_to_load_from_cache", lambda *a, **k: False
        )

        with pytest.raises(
            artefact_fetch.ArtefactVerificationError, match="sha256 mismatch"
        ):
            artefact_fetch.fetch_query_encoder_artefact(FAKE_MODEL)
        # Not cached before the call, so the mismatch is a genuine bad
        # download -- no repair retry, and no second call for that file.
        onnx_calls = [c for c in calls if c["filename"] == "onnx/model.onnx"]
        assert len(onnx_calls) == 1

    def test_size_mismatch_is_caught_before_hashing_and_reported_distinctly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """A wrong ``onnx_size_bytes`` registry pin must be caught, and
        reported as a size mismatch rather than silently passing (E-A5
        finding 7): identical sha256 implies identical length, so the size
        check has to run BEFORE the hash to ever be reachable at all.
        """
        from agent_session_tools import embeddings

        bad_artefact = dict(_fake_artefact())
        bad_artefact["onnx_size_bytes"] = len(ONNX_BYTES) + 1
        monkeypatch.setitem(embeddings.ONNX_ARTIFACTS, FAKE_MODEL, bad_artefact)

        calls: list[dict[str, Any]] = []
        _install_fake_downloader(monkeypatch, tmp_path, calls)
        monkeypatch.setattr(
            "huggingface_hub.try_to_load_from_cache", lambda *a, **k: False
        )

        with pytest.raises(
            artefact_fetch.ArtefactVerificationError, match="size mismatch"
        ):
            artefact_fetch.fetch_query_encoder_artefact(FAKE_MODEL)

    def test_stale_cached_file_with_bad_sha_is_repaired_with_force_download(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """A cached blob that no longer matches the registry's sha256 (E-A5
        finding 2) must be repaired, not handed straight back forever:
        ``hf_hub_download`` without ``force_download`` returns the existing
        (stale) pointer path, so the fetch must retry once with
        ``force_download=True`` before giving up.
        """
        calls: list[dict[str, Any]] = []
        corrupted = bytes(b ^ 0xFF for b in ONNX_BYTES)  # same length, wrong content

        def fake_download(
            repo_id, filename, *, revision, local_files_only, force_download=False
        ):
            calls.append({"filename": filename, "force_download": force_download})
            dest = tmp_path / filename.replace("/", "_")
            if filename == "onnx/model.onnx" and not force_download:
                dest.write_bytes(corrupted)
            else:
                dest.write_bytes(_content_for(filename))
            return str(dest)

        monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_download)
        monkeypatch.setattr(
            "huggingface_hub.try_to_load_from_cache", lambda *a, **k: "cached-pointer"
        )

        result = artefact_fetch.fetch_query_encoder_artefact(FAKE_MODEL)

        assert result.status == "fetched"
        onnx = next(f for f in result.files if f.relpath == "onnx/model.onnx")
        assert onnx.sha256 == _sha(ONNX_BYTES)

        onnx_calls = [c for c in calls if c["filename"] == "onnx/model.onnx"]
        assert len(onnx_calls) == 2
        assert onnx_calls[0]["force_download"] is False
        assert onnx_calls[1]["force_download"] is True

    def test_stale_cached_file_still_bad_after_retry_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """If the repair retry ALSO mismatches, that is a genuine
        supply-chain signal -- raise, don't retry forever."""
        corrupted = bytes(b ^ 0xFF for b in ONNX_BYTES)

        def fake_download(
            repo_id, filename, *, revision, local_files_only, force_download=False
        ):
            dest = tmp_path / filename.replace("/", "_")
            content = (
                corrupted if filename == "onnx/model.onnx" else _content_for(filename)
            )
            dest.write_bytes(content)
            return str(dest)

        monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_download)
        monkeypatch.setattr(
            "huggingface_hub.try_to_load_from_cache", lambda *a, **k: "cached-pointer"
        )

        with pytest.raises(
            artefact_fetch.ArtefactVerificationError, match="sha256 mismatch"
        ):
            artefact_fetch.fetch_query_encoder_artefact(FAKE_MODEL)

    def test_offline_env_skips_without_calling_the_downloader(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("HF_HUB_OFFLINE", "1")

        def _blocked(*_a, **_k):
            raise AssertionError("hf_hub_download called while HF_HUB_OFFLINE=1")

        monkeypatch.setattr("huggingface_hub.hf_hub_download", _blocked)

        result = artefact_fetch.fetch_query_encoder_artefact(FAKE_MODEL)

        assert result.status == "offline_skip"
        assert result.files == ()
        assert "HF_HUB_OFFLINE" in result.detail


class TestExitCodesDistinguishOutcomes:
    def test_all_three_non_failure_outcomes_map_to_different_exit_codes(self):
        codes = set(artefact_fetch.EXIT_CODES.values())
        assert len(codes) == 3
        assert artefact_fetch.EXIT_CODES["already_cached"] == 0

    def test_no_success_code_collides_with_clicks_reserved_codes(self):
        # click.UsageError.exit_code == 2 and a hard failure here is 1 --
        # a success/skip outcome must never be mistaken for either.
        codes = set(artefact_fetch.EXIT_CODES.values())
        assert 1 not in codes
        assert 2 not in codes


class TestCheckCachedArtefact:
    def test_pass_when_every_file_cached_and_sha_matches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        for relpath, content in (
            ("onnx/model.onnx", ONNX_BYTES),
            ("tokenizer.json", TOKENIZER_BYTES),
            ("tokenizer_config.json", TOKENIZER_CONFIG_BYTES),
        ):
            (tmp_path / relpath.replace("/", "_")).write_bytes(content)

        def fake_try_cache(repo_id, filename, *, revision):
            return str(tmp_path / filename.replace("/", "_"))

        monkeypatch.setattr("huggingface_hub.try_to_load_from_cache", fake_try_cache)

        check = artefact_fetch.check_cached_artefact(FAKE_MODEL)
        assert check.status == "pass"

    def test_warn_when_absent(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "huggingface_hub.try_to_load_from_cache", lambda *a, **k: None
        )
        check = artefact_fetch.check_cached_artefact(FAKE_MODEL)
        assert check.status == "warn"
        assert "not cached" in check.detail

    def test_fail_when_cached_but_sha_does_not_match(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        corrupted = tmp_path / "corrupted"
        corrupted.write_bytes(b"not the pinned content at all")

        monkeypatch.setattr(
            "huggingface_hub.try_to_load_from_cache", lambda *a, **k: str(corrupted)
        )
        check = artefact_fetch.check_cached_artefact(FAKE_MODEL)
        assert check.status == "fail"
        assert "sha256 mismatch" in check.detail

    def test_never_calls_hf_hub_download(self, monkeypatch: pytest.MonkeyPatch):
        def _blocked(*_a, **_k):
            raise AssertionError("check_cached_artefact must never fetch")

        monkeypatch.setattr("huggingface_hub.hf_hub_download", _blocked)
        monkeypatch.setattr(
            "huggingface_hub.try_to_load_from_cache", lambda *a, **k: None
        )
        artefact_fetch.check_cached_artefact(FAKE_MODEL)


class TestDocsContract:
    """The degradation messages and the docs name the same command.

    No prose is copied here (council TEST SHAPE rule): the onnx_encoder half
    is BEHAVIOURAL -- it forces the real "artefact absent" exception path and
    reads ``artefact_fetch.FETCH_COMMAND`` out of the raised message, so a
    future edit that changes the constant but forgets to interpolate it into
    the f-string fails this test too (a static text-scan for the constant's
    current value would not catch that, since the source only ever holds
    ``{FETCH_COMMAND}``, not its expansion). The docs half is structural: the
    exact command string must appear in the docs that promise it exists.
    """

    def test_onnx_encoder_missing_artefact_message_names_the_fetch_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        import huggingface_hub.constants

        from agent_session_tools.onnx_encoder import _load_tokenizer

        # Same isolation as test_query_encoders.py's _isolate_hf_cache: the
        # cache dir is a module-attribute lookup at call time, not something
        # HF_HOME alone can redirect once huggingface_hub is already imported.
        monkeypatch.setattr(
            huggingface_hub.constants, "HF_HUB_CACHE", str(tmp_path / "empty")
        )
        with pytest.raises(RuntimeError) as excinfo:
            _load_tokenizer(
                "fake-org/fake-model", "deadbeefcafe", local_files_only=True
            )
        assert artefact_fetch.FETCH_COMMAND in str(excinfo.value)

    def test_setup_docs_name_the_fetch_command(self):
        repo_root = Path(__file__).parents[3]
        setup_guide = repo_root / "docs" / "setup-guide.md"
        cli_reference = repo_root / "docs" / "cli-reference.md"
        assert artefact_fetch.FETCH_COMMAND in setup_guide.read_text()
        assert artefact_fetch.FETCH_COMMAND in cli_reference.read_text()
