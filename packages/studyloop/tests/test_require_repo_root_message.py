"""R-40 guard: require_repo_root()'s error must name the current project.

installers.py:208 said "This command requires a source checkout of
socratic-study-mentor" -- a name that predates even the studyctl -> studyloop
rename (commit bbcb914). Surfaced verbatim to end users running `studyloop
install tools/agents` or `doctor --fix` outside a checkout.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from studyloop.installers import InstallError, require_repo_root


def test_require_repo_root_error_names_studyloop_not_the_old_name() -> None:
    with (
        patch("studyloop.installers.find_repo_root", return_value=None),
        pytest.raises(InstallError) as exc_info,
    ):
        require_repo_root()
    message = str(exc_info.value)
    assert "studyloop" in message.lower()
    assert "socratic-study-mentor" not in message
