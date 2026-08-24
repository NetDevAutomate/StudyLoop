"""Keep public voice guidance aligned with the released fallback chain."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _normalise(text: str) -> str:
    return " ".join(text.casefold().split())


def test_public_quick_guides_name_the_default_voicemode_fallback() -> None:
    for path in ("README.md", "docs/setup-guide.md", "docs/web-ui-guide.md"):
        guide = _normalise(_read(path))
        assert "voicemode" in guide, path
        assert "8880" in guide, path
        assert "operating system" in guide or "os voice" in guide, path


def test_voice_guide_distinguishes_server_candidates_from_browser_tiers() -> None:
    guide = _normalise(_read("docs/voice-output.md"))

    assert "server candidate chain" in guide
    assert "primary, then each configured fallback" in guide
    assert "voicemode on port 8880 is the default fallback" in guide
    assert "this is not a chain of servers" not in guide
    assert "studyloop points at one server url" not in guide


def test_public_docs_do_not_claim_a_v_auto_voice_shortcut() -> None:
    cli_reference = _normalise(_read("docs/cli-reference.md"))
    web_guide = _normalise(_read("docs/web-ui-guide.md"))

    assert "toggle auto-voice" not in cli_reference
    assert "`v` is unbound" in cli_reference
    assert "`v` is unbound" in web_guide
    assert "`space`/`enter`" not in cli_reference
    assert "`a`-`d`" not in cli_reference
    assert "`1`-`4`" in cli_reference


def test_current_roadmap_does_not_describe_retired_browser_local_kokoro() -> None:
    roadmap = _normalise(_read("docs/audhd-deep-technical-learning-roadmap.md"))

    assert "browser-local kokoro/web speech" not in roadmap
    assert "without affecting the web ui" not in roadmap
    assert "server-side kokoro" in roadmap
    assert "voicemode" in roadmap
