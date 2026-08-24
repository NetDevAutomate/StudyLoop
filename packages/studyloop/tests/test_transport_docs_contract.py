"""Keep public transport architecture aligned with the v0.1 runtime contract."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _normalized(path: str) -> str:
    return " ".join(_read(path).split())


def test_public_docs_keep_tmux_default_and_herdr_explicit() -> None:
    architecture = _normalized("docs/architecture.md")
    overview = _normalized("docs/system-overview.md")

    assert "The Herdr server must already be running" in architecture
    assert "does not change the default" in architecture
    assert "until its journey suite is green" not in architecture
    assert "once its journey suite is green" not in overview


def test_public_docs_keep_acp_dev_only_and_ttyd_out_of_browser_release() -> None:
    target = _normalized("docs/architecture/target.md")
    protocol = _normalized("docs/session-protocol.md")
    overview = _normalized("docs/system-overview.md")

    assert "ACP remains dev-only" in target
    assert "ttyd still used for Claude/Codex/OpenCode" not in target
    assert "experimental and available only with `studyloop web --dev`" in protocol
    assert "ACP chat only with `studyloop web --dev`" in overview
