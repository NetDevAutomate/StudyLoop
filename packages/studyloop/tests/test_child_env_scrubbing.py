"""Every agent transport must strip credentials from its child.

An agent subprocess is a third-party binary chosen by the learner and driven by a
model, and on the ACP path it is granted filesystem read and write. Anything left
in its environment is available to it and to whatever it launches.

This file exists because the rule was enforced in exactly one of the two
transports. ``pty.py`` built a scrubbed env; ``session_runtime/acp.py`` passed
``os.environ.copy()`` and ``session/transports/acp.py`` passed no ``env=`` at all,
which inherits everything. Each file looked reasonable on its own, which is how
the asymmetry survived. The tests below are written against the SHARED rule so a
future third transport cannot quietly opt out.
"""

from __future__ import annotations

import inspect

from studyloop.session.child_env import (
    CHILD_ENV_DENY,
    CHILD_ENV_DENY_PAT,
    build_child_env,
)


class TestScrubbing:
    def test_credential_shaped_keys_are_removed(self) -> None:
        env = {
            "AWS_SESSION_TOKEN": "t",
            "GITHUB_TOKEN": "t",
            "MY_PASSWORD": "p",
            "CLIENT_SECRET": "s",
            "OPENAI_API_KEY": "k",
            "AWS_SECRET_ACCESS_KEY": "k",
            "PATH": "/usr/bin",
            "HOME": "/home/x",
        }
        clean = build_child_env(env)
        for leaked in (
            "AWS_SESSION_TOKEN",
            "GITHUB_TOKEN",
            "MY_PASSWORD",
            "CLIENT_SECRET",
            "OPENAI_API_KEY",
            "AWS_SECRET_ACCESS_KEY",
        ):
            assert leaked not in clean, f"{leaked} reached the child"

    def test_ordinary_environment_survives(self) -> None:
        """Deny-list, not allow-list.

        An allowlist would strip XDG paths, proxy settings, locale and editor
        configuration, and every breakage would be reported as 'the agent does
        not work' long after the cause was forgotten.
        """
        env = {
            "PATH": "/usr/bin",
            "HOME": "/home/x",
            "LANG": "en_GB.UTF-8",
            "XDG_CONFIG_HOME": "/home/x/.config",
            "HTTPS_PROXY": "http://proxy:3128",
            "TERM": "xterm-256color",
        }
        assert build_child_env(env) == env

    def test_named_keys_are_removed_regardless_of_shape(self) -> None:
        env = {"STUDYLOOP_TEST_AGENT_CMD": "fake", "STUDYLOOP_CONFIG": "/tmp/c.yaml"}
        assert build_child_env(env) == {}

    def test_a_name_merely_containing_token_is_kept(self) -> None:
        """The pattern is anchored, so it does not sweep up innocent names.

        Over-broad scrubbing is its own failure: it breaks agents for reasons
        nobody can see, which trains people to disable the protection.
        """
        env = {"TOKENIZERS_PARALLELISM": "false", "TOKEN_BUDGET_HINT": "8000"}
        assert build_child_env(env) == env


class TestEveryTransportUsesIt:
    """Structural: a transport must not hand its child a raw environment."""

    @staticmethod
    def _code_only(module: object) -> str:
        """Source with comment lines removed.

        These assertions are about what the code DOES. Matching raw source would
        also match a comment describing the very thing being forbidden -- and it
        did, on the comment explaining why os.environ.copy() is not used here.
        """
        lines = inspect.getsource(module).splitlines()  # type: ignore[arg-type]
        return "\n".join(ln for ln in lines if not ln.lstrip().startswith("#"))

    def test_acp_runtime_does_not_copy_os_environ(self) -> None:
        from studyloop.session_runtime import acp as runtime_acp

        code = self._code_only(runtime_acp)
        assert "os.environ.copy()" not in code, (
            "session_runtime/acp.py is handing the child the parent environment"
        )
        assert "build_child_env" in code

    def test_acp_transport_passes_env_explicitly(self) -> None:
        """Omitting env= inherits everything, so its ABSENCE is the bug."""
        from studyloop.session.transports import acp as transport_acp

        code = self._code_only(transport_acp)
        assert "env=build_child_env()" in code, (
            "session/transports/acp.py must pass a scrubbed env= explicitly; "
            "omitting env= inherits the whole parent environment"
        )

    def test_pty_shares_the_rule_rather_than_copying_it(self) -> None:
        """One definition. The duplicate is how the two paths diverged."""
        from studyloop.session.transports import pty

        assert pty._CHILD_ENV_DENY is CHILD_ENV_DENY
        assert pty._CHILD_ENV_DENY_PAT is CHILD_ENV_DENY_PAT
        source = inspect.getsource(pty._build_child_env)
        assert "build_child_env(caller_env)" in source
