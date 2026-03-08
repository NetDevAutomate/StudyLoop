"""Tests for the exporter registry in exporters/__init__.py.

Validates:
- Every registered exporter satisfies the SessionExporter protocol
  (source_name, is_available, export_all).
- The "bedrock" key is present in EXPORTERS.
- get_exporter raises ValueError for unknown keys.
"""

import pytest

from agent_session_tools.exporters import EXPORTERS, get_all_exporters, get_exporter


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestExporterProtocolConformance:
    """Every exporter in the registry must expose the SessionExporter interface."""

    @pytest.mark.parametrize("key", list(EXPORTERS.keys()))
    def test_has_source_name(self, key: str) -> None:
        exporter = EXPORTERS[key]
        assert hasattr(exporter, "source_name"), f"{key} missing source_name"
        assert isinstance(exporter.source_name, str)
        assert len(exporter.source_name) > 0

    @pytest.mark.parametrize("key", list(EXPORTERS.keys()))
    def test_has_is_available(self, key: str) -> None:
        exporter = EXPORTERS[key]
        assert callable(getattr(exporter, "is_available", None)), (
            f"{key} missing is_available()"
        )

    @pytest.mark.parametrize("key", list(EXPORTERS.keys()))
    def test_has_export_all(self, key: str) -> None:
        exporter = EXPORTERS[key]
        assert callable(getattr(exporter, "export_all", None)), (
            f"{key} missing export_all()"
        )

    @pytest.mark.parametrize("key", list(EXPORTERS.keys()))
    def test_is_available_returns_bool(self, key: str) -> None:
        exporter = EXPORTERS[key]
        result = exporter.is_available()
        assert isinstance(result, bool)

    @pytest.mark.parametrize("key", list(EXPORTERS.keys()))
    def test_export_all_accepts_connection(self, key: str) -> None:
        """export_all signature must accept (conn, incremental, batch_size)."""
        import inspect

        exporter = EXPORTERS[key]
        sig = inspect.signature(exporter.export_all)
        params = list(sig.parameters.keys())
        # First positional param should be 'conn' (after self which is already bound)
        assert "conn" in params, f"{key}.export_all missing 'conn' parameter"


# ---------------------------------------------------------------------------
# Registry contents
# ---------------------------------------------------------------------------


class TestRegistryContents:
    def test_bedrock_key_exists(self) -> None:
        assert "bedrock" in EXPORTERS

    def test_claude_key_exists(self) -> None:
        assert "claude" in EXPORTERS

    def test_kiro_key_exists(self) -> None:
        assert "kiro" in EXPORTERS

    def test_registry_not_empty(self) -> None:
        assert len(EXPORTERS) > 0

    def test_all_keys_are_strings(self) -> None:
        for key in EXPORTERS:
            assert isinstance(key, str)

    def test_source_names_are_unique(self) -> None:
        names = [e.source_name for e in EXPORTERS.values()]
        assert len(names) == len(set(names)), f"Duplicate source_names: {names}"


# ---------------------------------------------------------------------------
# get_exporter / get_all_exporters
# ---------------------------------------------------------------------------


class TestGetExporter:
    def test_valid_key_returns_exporter(self) -> None:
        exporter = get_exporter("bedrock")
        assert exporter.source_name is not None

    def test_invalid_key_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown exporter"):
            get_exporter("invalid")

    def test_empty_key_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown exporter"):
            get_exporter("")

    def test_get_all_returns_copy(self) -> None:
        """get_all_exporters returns a copy so callers cannot mutate the registry."""
        all_exporters = get_all_exporters()
        assert all_exporters == EXPORTERS
        # Must be a different dict object
        assert all_exporters is not EXPORTERS

    def test_get_all_same_instances(self) -> None:
        """The exporter instances in the copy should be the same objects."""
        all_exporters = get_all_exporters()
        for key in EXPORTERS:
            assert all_exporters[key] is EXPORTERS[key]
