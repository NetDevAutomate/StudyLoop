"""Tests for agent_session_tools.utils — stable_id, content_hash, file_fingerprint."""

import hashlib
from pathlib import Path

import pytest

from agent_session_tools.utils import content_hash, file_fingerprint, stable_id


# ---------------------------------------------------------------------------
# stable_id
# ---------------------------------------------------------------------------


class TestStableId:
    """Tests for deterministic ID generation."""

    def test_returns_prefixed_string(self):
        result = stable_id("sess", "/some/path")
        assert result.startswith("sess_")

    def test_hash_portion_is_12_hex_chars(self):
        result = stable_id("x", "/any/key")
        _, hex_part = result.split("_", 1)
        assert len(hex_part) == 12
        # Verify it is valid hex
        int(hex_part, 16)

    def test_deterministic_same_inputs(self):
        a = stable_id("sess", "/project/alpha")
        b = stable_id("sess", "/project/alpha")
        assert a == b

    def test_different_keys_produce_different_ids(self):
        a = stable_id("sess", "/project/alpha")
        b = stable_id("sess", "/project/beta")
        assert a != b

    def test_different_prefixes_produce_different_ids(self):
        a = stable_id("sess", "/project/alpha")
        b = stable_id("msg", "/project/alpha")
        assert a != b

    def test_normalises_path_case(self):
        """Key is lowercased before hashing, so case variants collide."""
        a = stable_id("s", "/Foo/Bar")
        b = stable_id("s", "/foo/bar")
        assert a == b

    def test_normalises_path_resolution(self):
        """Path.resolve() collapses '..' and '.', so equivalent paths match."""
        a = stable_id("s", "/tmp/x/../x/file")
        b = stable_id("s", "/tmp/x/file")
        assert a == b

    def test_matches_manual_sha256(self):
        """Verify the implementation matches a hand-rolled SHA256 computation."""
        key = "/some/test/key"
        normalised = str(Path(key).resolve()).lower()
        expected_hex = hashlib.sha256(normalised.encode()).hexdigest()[:12]
        assert stable_id("pfx", key) == f"pfx_{expected_hex}"

    def test_empty_key(self):
        """Empty string is a valid key — should not raise."""
        result = stable_id("p", "")
        assert result.startswith("p_")

    def test_empty_prefix(self):
        result = stable_id("", "/key")
        assert result.startswith("_")


# ---------------------------------------------------------------------------
# content_hash
# ---------------------------------------------------------------------------


class TestContentHash:
    """Tests for content-based change detection hashing."""

    def test_returns_16_hex_chars(self):
        result = content_hash("hello world")
        assert len(result) == 16
        int(result, 16)

    def test_deterministic(self):
        assert content_hash("same") == content_hash("same")

    def test_different_content_different_hash(self):
        assert content_hash("alpha") != content_hash("beta")

    def test_matches_manual_sha256(self):
        text = "test content"
        expected = hashlib.sha256(text.encode()).hexdigest()[:16]
        assert content_hash(text) == expected

    def test_empty_string(self):
        result = content_hash("")
        assert len(result) == 16

    def test_unicode_content(self):
        result = content_hash("cafe\u0301")  # e with combining acute
        assert len(result) == 16
        # Different normalisation forms should produce different hashes
        assert content_hash("cafe\u0301") != content_hash("caf\u00e9")

    def test_whitespace_sensitivity(self):
        """Trailing whitespace changes the hash — no silent stripping."""
        assert content_hash("hello") != content_hash("hello ")

    def test_multiline_content(self):
        result = content_hash("line1\nline2\nline3")
        assert len(result) == 16


# ---------------------------------------------------------------------------
# file_fingerprint
# ---------------------------------------------------------------------------


class TestFileFingerprint:
    """Tests for file metadata fingerprinting."""

    def test_format_is_mtime_colon_size(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        result = file_fingerprint(f)

        stat = f.stat()
        assert result == f"{stat.st_mtime}:{stat.st_size}"

    def test_size_reflects_content_length(self, tmp_path: Path):
        f = tmp_path / "sized.txt"
        f.write_bytes(b"12345")
        result = file_fingerprint(f)

        _, size_str = result.split(":")
        assert int(size_str) == 5

    def test_fingerprint_changes_when_content_changes(self, tmp_path: Path):
        f = tmp_path / "mutable.txt"
        f.write_text("version 1")
        fp1 = file_fingerprint(f)

        f.write_text("version 2 is longer")
        fp2 = file_fingerprint(f)

        assert fp1 != fp2

    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        result = file_fingerprint(f)

        _, size_str = result.split(":")
        assert int(size_str) == 0

    def test_nonexistent_file_raises(self, tmp_path: Path):
        f = tmp_path / "missing.txt"
        with pytest.raises(FileNotFoundError):
            file_fingerprint(f)

    def test_returns_string(self, tmp_path: Path):
        f = tmp_path / "type_check.txt"
        f.write_text("data")
        assert isinstance(file_fingerprint(f), str)
