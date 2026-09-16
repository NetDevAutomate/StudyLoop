"""Every agent transport must strip credentials from its child.

An agent subprocess is a third-party binary chosen by the learner and driven by a
model, and on the ACP path it is granted filesystem read and write. Anything left
in its environment is available to it and to whatever it launches.

This file exists because the rule was enforced in exactly one of two
transports that both existed at the time. ``pty.py`` built a scrubbed env;
``session_runtime/acp.py`` (a fully dead, parallel transport implementation,
deleted in R-04) passed ``os.environ.copy()``, and the LIVE
``session/transports/acp.py`` passed no ``env=`` at all, which inherits
everything. Each file looked reasonable on its own, which is how the
asymmetry survived. The tests below are written against the SHARED rule so a
future third transport cannot quietly opt out.
"""

from __future__ import annotations

import inspect

import pytest

from studyloop.session.child_env import (
    CHILD_ENV_DENY,
    CHILD_ENV_DENY_PAT,
    build_child_env,
    build_scratch_child_env,
)


class TestScrubbing:
    #: Credential names taken from tools this project actually integrates with,
    #: not invented shapes. Every one of these must be stripped.
    #: Annotated tuple[str, ...] rather than left inferred: an un-annotated
    #: string-literal tuple infers as tuple[Literal[...], ...], which makes
    #: dict.fromkeys(...) below a dict[Literal[...], str] -- invariant in its
    #: key type and therefore not assignable to build_child_env's
    #: dict[str, str] parameter.
    MUST_STRIP: tuple[str, ...] = (
        # Ends in a credential word — caught by the suffix rule.
        "AWS_SECRET_ACCESS_KEY",
        "OPENAI_API_KEY",
        "GITHUB_TOKEN",
        "ANTHROPIC_AUTH_TOKEN",
        "LITELLM_API_KEY",
        "MY_PASSWORD",
        "CLIENT_SECRET",
        "GOOGLE_APPLICATION_CREDENTIALS",
        # Credential word MID-name — these defeated the suffix-only rule.
        # AWS_BEARER_TOKEN_BEDROCK is not hypothetical: it is the credential this
        # project's own Bedrock generators use on their profile-less fast path,
        # and it reached the agent child until the segment rule was added.
        "AWS_BEARER_TOKEN_BEDROCK",
        "AZURE_CLIENT_SECRET_ID",
        "GCP_PRIVATE_KEY_ID",
        "SOME_ACCESS_TOKEN_V2",
        # Innocent shape, dangerous value.
        "DATABASE_URL",
        # Bare `_KEY` suffix and AUTHORIZATION/JWT/COOKIE — R-11. A live probe
        # (agents/02-security.md) found these surviving the pre-fix patterns,
        # which only caught the compounds api_key/access_key/secret_key/
        # private_key, not a bare KEY suffix or these bare/segment words.
        "ENCRYPTION_KEY",
        "SIGNING_KEY",
        "MASTER_KEY",
        "AUTHORIZATION",
        "JWT",
        "SESSION_COOKIE",
        # Bare `oauth` segment — R-11b. No existing pattern covered `oauth`
        # at all; LEAKED_OAUTH has no OTHER credential-shaped segment, so it
        # only reaches the child if `oauth` itself is a recognised word.
        "LEAKED_OAUTH",
        # Already caught by the existing `client_secret` segment even before
        # this fix — kept here as a named regression case since it is the
        # shape the finding cited, not because it demonstrates the new
        # pattern alone.
        "OAUTH_CLIENT_SECRET",
        # No underscore at all between the two credential-shaped words —
        # R-11c. Every pattern above is underscore-anchored, so a name that
        # joins two words with no separator defeated all of them.
        "SERVICE_APIKEY",
        "GOOGLE_APIKEY",
        "SESSIONCOOKIE",
    )

    #: Ordinary environment that MUST survive. Keep-controls matter as much as the
    #: strip list: a scrubber that removed these would break agents for reasons
    #: nobody can see, which is how protections get switched off.
    #: Annotated tuple[str, ...] for the same reason as MUST_STRIP above.
    MUST_KEEP: tuple[str, ...] = (
        "PATH",
        "HOME",
        "LANG",
        "TERM",
        "XDG_CONFIG_HOME",
        "HTTPS_PROXY",
        "TOKENIZERS_PARALLELISM",
        "TOKEN_BUDGET_HINT",
        "AWS_REGION",
        "AWS_PROFILE",
        "EDITOR",
        # False positives the bare `_KEY` suffix pattern (R-11) must not catch:
        # anchoring on `(^|_)key$` rather than a bare `key` alternative is what
        # keeps these -- the credential word must be the whole name or a
        # underscore-delimited final segment, not merely a trailing substring.
        "MONKEY",
        "DONKEY",
        "KEYBOARD_LAYOUT",
        "SSH_AUTH_SOCK",
        "MONKEYPATCH_MODE",
        "TURKEY_DATA",
        # R-11b: no entry in this keep-list contains "oauth" as a substring,
        # so the new `oauth` segment word has no false positive to guard
        # against here. Checked directly, not just asserted by omission.
        #
        # R-11c: none of these entries, underscore-stripped and lowercased,
        # contain any of CHILD_ENV_DENY_SQUASHED's compound words either.
        # MONKEY -> "monkey" (literally ends in "key", the classic false
        # positive the anchored suffix pattern above already handles) does
        # NOT contain "apikey"/"accesskey"/"secretkey"/... as a substring,
        # which is exactly why CHILD_ENV_DENY_SQUASHED is a curated list of
        # COMPOUNDS rather than the bare words themselves.
    )

    #: R-11c (ARBITRATION.md A6): stripping these two is a DELIBERATE,
    #: accepted trade-off of the bare `authorization`/`cookie` segment words
    #: added for R-11, not a new false positive introduced here and not
    #: something to "fix" by narrowing the pattern. A deny-list errs toward
    #: over-stripping; documented here so a future reader does not mistake
    #: this for a regression or move these into MUST_KEEP.
    KNOWN_INTENDED_STRIPS: tuple[str, ...] = (
        "AUTHORIZATION_ENDPOINT",
        "COOKIE_FILE",
    )

    def test_every_known_credential_shape_is_removed(self) -> None:
        env: dict[str, str] = dict.fromkeys(self.MUST_STRIP, "sensitive")
        clean = build_child_env(env)
        leaked = sorted(k for k in self.MUST_STRIP if k in clean)
        assert leaked == [], f"these credentials reached the agent child: {leaked}"

    def test_known_intended_strips_are_stripped(self) -> None:
        """R-11c: AUTHORIZATION_ENDPOINT and COOKIE_FILE are an ACCEPTED
        false-positive trade-off of the bare authorization/cookie segment
        words, not something this fix should try to avoid."""
        env: dict[str, str] = dict.fromkeys(self.KNOWN_INTENDED_STRIPS, "value")
        clean = build_child_env(env)
        assert clean == {}

    def test_ordinary_environment_survives(self) -> None:
        """Deny-list, not allow-list.

        An allowlist would strip XDG paths, proxy settings, locale and editor
        configuration, and every breakage would be reported as 'the agent does
        not work' long after the cause was forgotten.
        """
        env: dict[str, str] = dict.fromkeys(self.MUST_KEEP, "fine")
        assert build_child_env(env) == env

    def test_the_two_lists_do_not_overlap(self) -> None:
        """Guards the test itself: a name in both lists makes one assertion a lie."""
        assert not (set(self.MUST_STRIP) & set(self.MUST_KEEP))

    def test_named_keys_are_removed_regardless_of_shape(self) -> None:
        env = {
            "STUDYLOOP_TEST_AGENT_CMD": "fake",
            "STUDYLOOP_TEST_ACP_CMD": "fake-acp",
            "STUDYLOOP_CONFIG": "/tmp/c.yaml",
        }
        assert build_child_env(env) == {}

    def test_a_name_merely_containing_token_is_kept(self) -> None:
        """The rules work on underscore segments, so innocent names survive.

        TOKENIZERS_PARALLELISM splits to TOKENIZERS + PARALLELISM, neither of
        which is TOKEN. Over-broad scrubbing is its own failure: it breaks agents
        invisibly, which trains people to disable the protection.
        """
        env = {"TOKENIZERS_PARALLELISM": "false", "TOKEN_BUDGET_HINT": "8000"}
        assert build_child_env(env) == env


class TestSecurityReviewProbeTable:
    """Regression test for the exact live probe in agents/02-security.md (R-11/S3).

    That probe ran ``build_child_env`` against one synthetic dict and recorded,
    per key, whether it was stripped or survived. This reproduces the same
    dict and the same per-key verdicts so the probe cannot silently regress.
    """

    #: (key, value, expect_stripped) — transcribed from the probe table.
    PROBE_ROWS: tuple[tuple[str, str, bool], ...] = (
        ("AWS_BEARER_TOKEN_BEDROCK", "x", True),
        ("GOOGLE_APPLICATION_CREDENTIALS", "x", True),
        ("AZURE_CLIENT_SECRET_ID", "x", True),
        ("AWS_ACCESS_KEY_ID", "x", True),
        ("ENCRYPTION_KEY", "x", True),
        ("SIGNING_KEY", "x", True),
        ("MASTER_KEY", "x", True),
        ("AUTHORIZATION", "Bearer x", True),
        ("JWT", "x", True),
        ("SESSION_COOKIE", "x", True),
        ("TOKENIZERS_PARALLELISM", "false", False),
        ("TOKEN_BUDGET_HINT", "1000", False),
    )

    @pytest.mark.parametrize(
        "key,value,expect_stripped",
        PROBE_ROWS,
        ids=[row[0] for row in PROBE_ROWS],
    )
    def test_probe_row(self, key: str, value: str, expect_stripped: bool) -> None:
        synthetic = {row[0]: row[1] for row in self.PROBE_ROWS}
        clean = build_child_env(synthetic)
        if expect_stripped:
            assert key not in clean, f"{key} leaked into the agent child's env"
        else:
            assert key in clean, f"{key} was wrongly stripped (false positive)"

    def test_probe_matches_agents_02_security_md(self) -> None:
        """One shot: reproduce the whole probe dict at once and diff both sides."""
        synthetic = {row[0]: row[1] for row in self.PROBE_ROWS}
        clean = build_child_env(synthetic)
        expected_stripped = {row[0] for row in self.PROBE_ROWS if row[2]}
        expected_kept = {row[0] for row in self.PROBE_ROWS if not row[2]}
        actually_stripped = set(synthetic) - set(clean)
        actually_kept = set(clean)
        assert actually_stripped == expected_stripped
        assert actually_kept == expected_kept


class TestScratchChildEnv:
    """(e) the acceptance-tier sanitized env: scratch HOME, no real-home XDG leak.

    ``build_scratch_child_env`` is what tests/acceptance/isolation.py hands to
    every subprocess an acceptance test drives — see docs/acceptance-testing.md.
    """

    def test_home_and_state_dir_point_at_scratch(self, tmp_path) -> None:
        home = tmp_path / "home"
        state_dir = home / ".local" / "share" / "studyloop"
        env = build_scratch_child_env(home=home, state_dir=state_dir, caller_env={})
        assert env["HOME"] == str(home)
        assert env["STUDYLOOP_STATE_DIR"] == str(state_dir)

    def test_real_home_xdg_vars_never_survive(self, tmp_path) -> None:
        home = tmp_path / "home"
        state_dir = home / ".local" / "share" / "studyloop"
        real_home_leak = "/Users/real-learner"
        caller_env = {
            "XDG_CONFIG_HOME": f"{real_home_leak}/.config",
            "XDG_DATA_HOME": f"{real_home_leak}/.local/share",
            "XDG_CACHE_HOME": f"{real_home_leak}/.cache",
            "XDG_STATE_HOME": f"{real_home_leak}/.local/state",
            "XDG_RUNTIME_DIR": f"{real_home_leak}/.run",
        }
        env = build_scratch_child_env(home=home, state_dir=state_dir, caller_env=caller_env)
        for value in env.values():
            assert real_home_leak not in value, (
                f"a real-home path leaked into the scratch child env: {value!r}"
            )
        # The four base dirs are overridden to point under scratch, not merely
        # deleted -- a harness that reads XDG_CONFIG_HOME directly must still
        # land under `home`, never fall through to ITS OWN default resolution.
        assert env["XDG_CONFIG_HOME"] == str(home / ".config")
        assert env["XDG_DATA_HOME"] == str(home / ".local/share")
        assert env["XDG_CACHE_HOME"] == str(home / ".cache")
        assert env["XDG_STATE_HOME"] == str(home / ".local/state")
        # XDG_RUNTIME_DIR has no scratch equivalent defined -- scrubbed clean,
        # not merely left holding the real leak.
        assert "XDG_RUNTIME_DIR" not in env

    def test_still_scrubs_credentials(self, tmp_path) -> None:
        home = tmp_path / "home"
        state_dir = home / ".local" / "share" / "studyloop"
        env = build_scratch_child_env(
            home=home,
            state_dir=state_dir,
            caller_env={"OPENAI_API_KEY": "sk-live-secret"},  # pragma: allowlist secret
        )
        assert "OPENAI_API_KEY" not in env

    def test_test_acp_cmd_hatch_never_reaches_the_scratch_child(self, tmp_path) -> None:
        """A stale ``STUDYLOOP_TEST_ACP_CMD`` in the developer's shell must
        never reach an acceptance-test child: it overrides the ACP argv
        entirely (web/routes/session/_transport.py) and bypasses the binary
        check (web/routes/session/_start.py), so it can silently swap a real
        kiro-cli mentor for the stub agent -- the exact thing council D-16
        forbids for a live acceptance test. See test_web_acp_dogfood_kiro.py's
        own ``env.pop("STUDYLOOP_TEST_ACP_CMD", None)  # belt-and-braces``."""
        home = tmp_path / "home"
        state_dir = home / ".local" / "share" / "studyloop"
        env = build_scratch_child_env(
            home=home,
            state_dir=state_dir,
            caller_env={"STUDYLOOP_TEST_ACP_CMD": "python -m tests._stub_acp_agent"},
        )
        assert "STUDYLOOP_TEST_ACP_CMD" not in env

    def test_parent_studyloop_pointers_never_reach_the_scratch_child(self, tmp_path) -> None:
        """Every inherited ``STUDYLOOP_*`` pointer is a leak past the scratch HOME.

        Found 2026-09-16 by the first live harness-evidence run: the unit
        suite's root conftest sets ``STUDYLOOP_SESSION_DIR`` (autouse),
        ``STUDYLOOP_DB`` and ``SESSION_CONTEXT_SCOPE`` in the pytest process,
        and the acceptance lane built its scratch env from that process's
        ``os.environ`` -- so ``studyloop study`` in the child wrote
        ``session-state.json`` into the SUITE's throwaway session dir, the lane
        waited for it under the scratch config dir, and every harness timed
        out before its binary was even looked at. The scratch HOME is the
        isolation boundary: the only ``STUDYLOOP_*`` variable a child may see
        is the one this builder sets itself.
        """
        home = tmp_path / "home"
        state_dir = home / ".local" / "share" / "studyloop"
        env = build_scratch_child_env(
            home=home,
            state_dir=state_dir,
            caller_env={
                "STUDYLOOP_SESSION_DIR": "/tmp/pytest-of-someone/suite-session-dir0",
                "STUDYLOOP_DB": "/tmp/pytest-of-someone/state/sessions.db",
                "STUDYLOOP_STATE_DIR": "/tmp/pytest-of-someone/state",
                "STUDYLOOP_ACC": "1",
                "STUDYLOOP_ACC_HARNESS": "pi",
                "SESSION_CONTEXT_SCOPE": "unclassified",
                "PATH": "/usr/bin:/bin",
            },
        )
        assert {k for k in env if k.startswith("STUDYLOOP_")} == {"STUDYLOOP_STATE_DIR"}
        assert env["STUDYLOOP_STATE_DIR"] == str(state_dir)
        # The child must resolve its context scope from the SCRATCH config the
        # same way production does, not from a test-only override.
        assert "SESSION_CONTEXT_SCOPE" not in env
        assert env["PATH"] == "/usr/bin:/bin"


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
