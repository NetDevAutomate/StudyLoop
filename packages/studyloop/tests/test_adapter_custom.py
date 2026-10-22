"""Tests for config-driven custom agents."""

from __future__ import annotations

import json
import stat
from unittest.mock import patch


class TestCustomAgentFromConfig:
    def test_cli_flag_strategy(self, tmp_path):
        from studyloop.adapters._custom import build_custom_adapter

        config = {
            "binary": "exampletool",
            "strategy": "cli-flag",
            "launch": "{binary} --read {persona}",
        }
        adapter = build_custom_adapter("exampletool", config)
        assert adapter.name == "exampletool"
        assert adapter.binary == "exampletool"
        path = adapter.setup("# content", tmp_path)
        assert path.exists()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_launch_cmd_interpolation(self, tmp_path):
        from studyloop.adapters._custom import build_custom_adapter

        config = {
            "binary": "exampletool",
            "strategy": "cli-flag",
            "launch": "{binary} --read {persona}",
        }
        adapter = build_custom_adapter("exampletool", config)
        persona = tmp_path / "persona.md"
        persona.touch()
        with patch("shutil.which", return_value="/usr/local/bin/exampletool"):
            cmd = adapter.launch_cmd(persona, False)
        assert "/usr/local/bin/exampletool" in cmd
        assert str(persona) in cmd

    def test_resume_template(self, tmp_path):
        from studyloop.adapters._custom import build_custom_adapter

        config = {
            "binary": "exampletool",
            "strategy": "cli-flag",
            "launch": "{binary} --read {persona}",
            "resume": "{binary} --read {persona} --resume",
        }
        adapter = build_custom_adapter("exampletool", config)
        persona = tmp_path / "p.md"
        persona.touch()
        with patch("shutil.which", return_value="/usr/bin/exampletool"):
            cmd = adapter.launch_cmd(persona, True)
        assert "--resume" in cmd

    def test_env_vars_prepended(self, tmp_path):
        from studyloop.adapters._custom import build_custom_adapter

        config = {
            "binary": "claude",
            "strategy": "cli-flag",
            "launch": "{binary} --prompt {persona}",
            "env": {"ANTHROPIC_BASE_URL": "http://localhost:4000", "MODEL": "qwen3"},
        }
        adapter = build_custom_adapter("my-llm", config)
        persona = tmp_path / "p.md"
        persona.touch()
        with patch("shutil.which", return_value="/usr/bin/claude"):
            cmd = adapter.launch_cmd(persona, False)
        assert "ANTHROPIC_BASE_URL=http://localhost:4000" in cmd
        assert "MODEL=qwen3" in cmd

    def test_cwd_file_strategy(self, tmp_path):
        from studyloop.adapters._custom import build_custom_adapter

        config = {
            "binary": "my-agent",
            "strategy": "cwd-file",
            "filename": ".my-prompt.md",
            "launch": "{binary}",
        }
        adapter = build_custom_adapter("my-agent", config)
        path = adapter.setup("# persona", tmp_path)
        assert path == tmp_path / ".my-prompt.md"
        assert "persona" in path.read_text()

    def test_teardown_cmd(self, tmp_path):
        from studyloop.adapters._custom import build_custom_adapter

        marker = tmp_path / "teardown-ran"
        config = {
            "binary": "agent",
            "strategy": "cli-flag",
            "launch": "{binary}",
            "teardown": f"touch {marker}",
        }
        adapter = build_custom_adapter("agent", config)
        assert adapter.teardown is not None
        adapter.teardown(tmp_path)
        assert marker.exists()

    def test_teardown_idempotent(self, tmp_path):
        from studyloop.adapters._custom import build_custom_adapter

        config = {
            "binary": "agent",
            "strategy": "cli-flag",
            "launch": "{binary}",
            "teardown": "true",
        }
        adapter = build_custom_adapter("agent", config)
        assert adapter.teardown is not None
        adapter.teardown(tmp_path)
        adapter.teardown(tmp_path)  # Must not raise

    def test_mcp_generic(self, tmp_path):
        from studyloop.adapters._custom import build_custom_adapter

        config = {
            "binary": "agent",
            "strategy": "cli-flag",
            "launch": "{binary}",
            "mcp": {"format": "generic"},
        }
        adapter = build_custom_adapter("agent", config)
        assert adapter.mcp_setup is not None
        adapter.mcp_setup(tmp_path)
        assert (tmp_path / ".mcp.json").exists()

    def test_mcp_dev_flag_is_forwarded_to_generated_config(self, tmp_path):
        from studyloop.adapters._custom import build_custom_adapter

        config = {
            "binary": "agent",
            "strategy": "cli-flag",
            "launch": "{binary}",
            "mcp": {"format": "generic", "dev": True},
        }
        adapter = build_custom_adapter("agent", config)
        assert adapter.mcp_setup is not None
        adapter.mcp_setup(tmp_path)
        entry = json.loads((tmp_path / ".mcp.json").read_text())["mcpServers"]["studyloop-mcp"]
        assert entry["args"][-1] == "--dev"

    def test_mcp_bool_true_means_generic(self, tmp_path):
        from studyloop.adapters._custom import build_custom_adapter

        config = {"binary": "agent", "strategy": "cli-flag", "launch": "{binary}", "mcp": True}
        adapter = build_custom_adapter("agent", config)
        assert adapter.mcp_setup is not None
        adapter.mcp_setup(tmp_path)
        assert (tmp_path / ".mcp.json").exists()

    def test_unknown_strategy_raises(self):
        import pytest

        from studyloop.adapters._custom import build_custom_adapter

        with pytest.raises(ValueError, match="Unknown strategy"):
            build_custom_adapter("bad", {"binary": "x", "strategy": "unknown", "launch": "x"})


class TestCustomAdapterQuotesItsBinary:
    """The launch string is shell text (``/bin/sh -c``, or the tmux pane command).

    The built-in adapters ``shlex.quote`` their resolved binary; a custom
    adapter must too, or a harness under a path with a space launches as two
    words. A template that already quotes ``{binary}`` itself keeps working:
    quoting it a second time would put literal quote characters in the path.
    """

    BINARY = "/opt/my tools/exampletool"

    def _launch(self, tmp_path, template: str) -> list[str]:
        import shlex

        from studyloop.adapters._custom import build_custom_adapter

        config = {"binary": "exampletool", "strategy": "cli-flag", "launch": template}
        adapter = build_custom_adapter("exampletool", config)
        persona = tmp_path / "persona.md"
        persona.touch()
        with patch("shutil.which", return_value=self.BINARY):
            return shlex.split(adapter.launch_cmd(persona, False))

    def test_binary_with_a_space_is_one_word(self, tmp_path):
        argv = self._launch(tmp_path, "{binary} --read {persona}")

        assert argv[0] == self.BINARY
        assert argv[1] == "--read"

    def test_a_template_that_double_quotes_the_binary_is_not_quoted_twice(self, tmp_path):
        argv = self._launch(tmp_path, '"{binary}" --read {persona}')

        assert argv[0] == self.BINARY

    def test_a_template_that_single_quotes_the_binary_is_not_quoted_twice(self, tmp_path):
        argv = self._launch(tmp_path, "'{binary}' --read {persona}")

        assert argv[0] == self.BINARY


class TestCustomAdapterQuotesEveryPlaceholderAndEnv:
    """``{persona}``, ``{session_dir}`` and ``env`` values are shell text too.

    Lane B quoted only ``{binary}`` (B5). The persona lives under the session
    directory, whose name is the learner's topic, so a space or a shell
    metacharacter in it is routine, not hostile -- and an ``env`` value is
    whatever the learner typed into config.yaml. Unquoted, a space splits the
    path into two words and ``;`` runs the rest as a second command. The same
    rule as ``{binary}``: a template that already quotes the placeholder
    itself is substituted raw, so existing templates keep working.
    """

    # A space, parentheses and a command separator: every one of these is
    # legal in a topic name.
    SESSION_DIR_NAME = "sql joins (part 1); echo pwned"

    def _launch(self, tmp_path, template: str, env: dict[str, str] | None = None) -> list[str]:
        import shlex

        from studyloop.adapters._custom import build_custom_adapter

        config: dict[str, object] = {
            "binary": "exampletool",
            "strategy": "cli-flag",
            "launch": template,
        }
        if env:
            config["env"] = env
        adapter = build_custom_adapter("exampletool", config)
        session_dir = tmp_path / self.SESSION_DIR_NAME
        session_dir.mkdir()
        persona = session_dir / "persona.md"
        persona.touch()
        with patch("shutil.which", return_value="/usr/bin/exampletool"):
            return shlex.split(adapter.launch_cmd(persona, False))

    def test_persona_with_a_space_and_a_metacharacter_is_one_word(self, tmp_path):
        argv = self._launch(tmp_path, "{binary} --read {persona}")

        assert argv == [
            "/usr/bin/exampletool",
            "--read",
            str(tmp_path / self.SESSION_DIR_NAME / "persona.md"),
        ]

    def test_session_dir_with_a_space_and_a_metacharacter_is_one_word(self, tmp_path):
        argv = self._launch(tmp_path, "{binary} --cwd {session_dir}")

        assert argv == ["/usr/bin/exampletool", "--cwd", str(tmp_path / self.SESSION_DIR_NAME)]

    def test_a_template_that_quotes_the_persona_itself_is_not_quoted_twice(self, tmp_path):
        argv = self._launch(tmp_path, '{binary} --read "{persona}"')

        assert argv[2] == str(tmp_path / self.SESSION_DIR_NAME / "persona.md")

    def test_env_values_are_quoted(self, tmp_path):
        import shlex

        from studyloop.adapters._custom import build_custom_adapter

        value = "http://localhost:4000/v1 (local); echo pwned"
        config: dict[str, object] = {
            "binary": "exampletool",
            "strategy": "cli-flag",
            "launch": "{binary}",
            "env": {"BASE_URL": value},
        }
        adapter = build_custom_adapter("exampletool", config)
        persona = tmp_path / "persona.md"
        persona.touch()
        with patch("shutil.which", return_value="/usr/bin/exampletool"):
            cmd = adapter.launch_cmd(persona, False)

        # ``punctuation_chars`` makes the shell's own ``;`` a token, so the one
        # inside the quoted value and the one joining the two commands are
        # told apart the way /bin/sh tells them apart.
        tokens = list(shlex.shlex(cmd, posix=True, punctuation_chars=True))
        assert tokens == ["export", f"BASE_URL={value}", ";", "/usr/bin/exampletool"]
