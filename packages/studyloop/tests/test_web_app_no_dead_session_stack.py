"""The web app must not construct machinery nothing reads.

``AgentSessionManager`` was instantiated on every web boot and assigned to
``app.state.agent_session_manager``. That attribute had no reader anywhere in the
source tree -- a third session stack alongside the two real ones
(``session/active.py`` for web, ``session_state.py`` for the CLI), carrying the
implication that it was load-bearing.

Dead code that looks alive is worse than dead code that looks dead: it makes the
session-lifecycle question harder to answer for anyone auditing which authority
owns a live session.
"""

from __future__ import annotations

import inspect


def _code_only(module: object) -> str:
    """Source with comment lines stripped, so prose cannot satisfy an assertion."""
    lines = inspect.getsource(module).splitlines()  # type: ignore[arg-type]
    return "\n".join(ln for ln in lines if not ln.lstrip().startswith("#"))


def test_web_app_does_not_construct_agent_session_manager() -> None:
    from studyloop.web import app as web_app

    code = _code_only(web_app)
    assert "AgentSessionManager" not in code, (
        "web/app.py is constructing AgentSessionManager again; nothing reads "
        "app.state.agent_session_manager, so this is a third session stack that "
        "only looks load-bearing"
    )


def test_no_source_file_reads_the_removed_app_state_attribute() -> None:
    """If a reader appears, the construction should come back deliberately.

    Asserted across the package rather than one module: the failure this guards
    is someone adding a consumer of app.state.agent_session_manager and getting
    an AttributeError at runtime instead of a test failure here.
    """
    from pathlib import Path

    import studyloop

    root = Path(studyloop.__file__).parent
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "app.state.agent_session_manager" in text:
            offenders.append(str(path.relative_to(root)))
    assert offenders == [], f"these files read a removed app.state attribute: {offenders}"
