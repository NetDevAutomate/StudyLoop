"""Prove the live xTiles checks cannot run unguarded — without running them.

``test_xtiles_live.py`` touches the owner's real xTiles account and reuses a saved
browser session. Its safety properties therefore have to hold on every commit, not
only on the rare run where someone opts in. A `live_xtiles` test is deselected by
default, so nothing in CI would ever notice if a gate were deleted.

This file is the part that does notice. It reads the live module as text and as an
AST rather than importing and running it, so the guarantees are checked by the
ordinary suite on every change.

The guarantees, and why each one matters:

* **Deselected by default, in both pyproject files.** The root and the package
  each carry their own ``addopts``; a marker added to one is a marker the other
  still runs. A live test that runs in a normal `pytest` invocation would open a
  browser onto someone's account during a routine change.
* **Never writes.** The module must contain no create/update/delete verb against
  xTiles. Its job is to look.
* **No credential in the repository.** The saved session lives under the user's
  cache directory. A default inside the working tree would eventually be
  committed.
* **A probe prefix is mandatory, and its absence FAILS rather than skips.** A skip
  on a missing prefix would let a run assert against whatever happened to be on
  the page — passing by accident, or reading real content into a log.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_REPO = _TESTS.parents[2]
LIVE_MODULE = _TESTS / "test_xtiles_live.py"
AUTH_SCRIPT = _REPO / "scripts" / "xtiles-live-auth.py"
PYPROJECTS = (_REPO / "pyproject.toml", _REPO / "packages" / "studyloop" / "pyproject.toml")


@pytest.fixture(scope="module")
def source() -> str:
    return LIVE_MODULE.read_text(encoding="utf-8")


def test_the_live_module_and_its_auth_script_exist() -> None:
    """If either is renamed, every guard below would silently pass on nothing."""
    assert LIVE_MODULE.is_file(), f"missing {LIVE_MODULE}"
    assert AUTH_SCRIPT.is_file(), f"missing {AUTH_SCRIPT}"


@pytest.mark.parametrize("pyproject", PYPROJECTS, ids=lambda p: p.parent.name)
def test_live_xtiles_is_deselected_by_default(pyproject: Path) -> None:
    """Both files, because they each have their own addopts.

    The root adds ``--import-mode=importlib`` and the package adds ``--tb=short``,
    so they are genuinely two expressions rather than one shared string, and a
    marker added to one is a marker the other still runs.
    """
    text = pyproject.read_text(encoding="utf-8")
    addopts = re.search(r"^addopts = \"(.*)\"$", text, flags=re.MULTILINE)
    assert addopts, f"no addopts line in {pyproject}"
    assert "not live_xtiles" in addopts.group(1), (
        f"{pyproject} does not deselect live_xtiles: a routine `pytest` run would "
        "open a browser onto the owner's real xTiles account"
    )
    assert '"live_xtiles:' in text, f"{pyproject} does not register the marker"


def test_the_module_is_marked_live(source: str) -> None:
    assert "pytestmark = pytest.mark.live_xtiles" in source, (
        "the module-level marker is what keeps every test in the file deselected; "
        "a per-function marker would be one forgotten decorator away from running"
    )


def test_the_live_checks_never_act_on_xtiles_content(source: str) -> None:
    """Read-only with respect to CONTENT, structurally.

    Refined once credentials arrived: signing in is genuinely an interaction — it
    fills two boxes and clicks a button — so a blanket ban on ``fill``/``click``
    was wrong, and would have been "fixed" by deleting the guard. The property
    that actually matters is narrower and stronger: interactions are confined to
    the sign-in helper, and no test body or content fixture may touch anything.

    Parsed rather than grepped. These verbs appear in this file's own prose and in
    the live module's docstrings, which is exactly the false positive that made the
    equivalent second-brain guard useless the first time it was written.
    """
    banned = {
        "fill",
        "click",
        "type",
        "press",
        "check",
        "uncheck",
        "select_option",
        "set_input_files",
        "drag_to",
    }
    allowed_scope = "_sign_in"

    tree = ast.parse(source, filename=str(LIVE_MODULE))
    offenders: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name == allowed_scope:
            continue
        offenders += [
            f"{node.name}() line {call.lineno}: .{call.func.attr}()"
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr in banned
        ]

    assert offenders == [], (
        "outside the sign-in helper, the live xTiles checks look — they do not act. "
        "Interactions found:\n" + "\n".join(offenders)
    )
    assert f"def {allowed_scope}(" in source, (
        f"the one allowed interaction site {allowed_scope!r} no longer exists, so "
        "this guard is checking nothing"
    )


def test_no_saved_session_path_defaults_inside_the_repository(source: str) -> None:
    """A credential with a default path in the working tree gets committed."""
    assert "Path.home()" in source, "the default session path is not under the user's home"
    assert ".cache" in source, "the default session path is not under a cache directory"

    tree = ast.parse(source, filename=str(LIVE_MODULE))
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert not [
        value for value in literals if value.startswith(("packages/", "reviews/auth", "./"))
    ], "a session path literal points inside the repository"

    # The auth script refuses it outright rather than relying on the default.
    auth = AUTH_SCRIPT.read_text(encoding="utf-8")
    assert "refusing to write a session credential inside the repository" in auth


def test_a_missing_probe_prefix_fails_rather_than_skips(source: str) -> None:
    """The one gate that must not be a skip.

    Opting in is the owner's choice, so a missing opt-in is a skip. But once opted
    in, a missing or too-short probe prefix means the assertions have no scope --
    they would match anything on the page. Skipping there hides a mistake that
    could read the owner's real workspace into a log; failing names it.
    """
    tree = ast.parse(source, filename=str(LIVE_MODULE))
    probe = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "probe"
        ),
        None,
    )
    assert probe is not None, "no probe fixture"

    calls = [
        node.func.attr
        for node in ast.walk(probe)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    assert "fail" in calls, "a missing probe prefix does not fail the run"

    assert "MIN_PROBE_LENGTH" in source, "no minimum length for the probe prefix"
    module_globals: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    module_globals[target.id] = node.value.value
    assert isinstance(module_globals.get("MIN_PROBE_LENGTH"), int)
    minimum = module_globals["MIN_PROBE_LENGTH"]
    assert isinstance(minimum, int)
    assert minimum >= 8, "a prefix this short is a substring, not a scope"


def test_the_probe_gate_is_evaluated_before_anything_can_skip(source: str) -> None:
    """The bug this file exists to prevent, found by running it rather than reading it.

    Pytest resolves fixtures in signature order. With ``signed_in_page(target_url)``
    declared without the probe, a missing saved session skipped the run before the
    too-short-prefix check was ever reached — so the one gate that must fail was,
    in practice, a skip. A guard that only checked "``pytest.fail`` appears in the
    probe fixture" passed happily throughout.

    Every fixture that can skip must therefore depend on ``probe``, directly or
    through another fixture that does, and ``probe`` must come first in the
    signature.
    """
    tree = ast.parse(source, filename=str(LIVE_MODULE))
    fixtures = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and any(
            (isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "fixture")
            or getattr(d, "attr", "") == "fixture"
            for d in node.decorator_list
        )
    }
    assert "probe" in fixtures, "no probe fixture"

    can_skip = {
        name
        for name, node in fixtures.items()
        if name != "probe"
        and any(
            isinstance(call, ast.Call) and getattr(call.func, "attr", "") == "skip"
            for call in ast.walk(node)
        )
    }
    assert can_skip, "expected at least one fixture that skips"

    for name in sorted(can_skip):
        args = [arg.arg for arg in fixtures[name].args.args]
        assert args and args[0] == "probe", (
            f"fixture {name!r} can skip but does not take `probe` first "
            f"(signature: {args}). Its skip would pre-empt the probe gate, and a "
            "run with no scope would report as skipped rather than failed."
        )


def test_the_url_under_test_must_be_https(source: str) -> None:
    assert 'startswith("https://")' in source, (
        "a live check that would follow a plain-http URL invites a session cookie onto the wire"
    )


def test_only_the_two_xtiles_keys_are_read_from_the_env_file(source: str) -> None:
    """A shared ``.env`` is a drawer, not a keyring.

    The file this defaults to also holds a GitHub token, a cloud bearer token and
    another service's password. A browser-driving test process has no business
    being able to see any of them, so the reader lifts exactly two keys by name.
    Sourcing the file — or handing it to ``dotenv`` — would put all of it into the
    environment of a process that then launches Chromium and talks to a third
    party.
    """
    assert 'CREDENTIAL_KEYS = ("XTILES_USERNAME", "XTILES_PASSWORD")' in source, (
        "the allowed key list is not a literal pair; a wider read is a wider leak"
    )

    tree = ast.parse(source, filename=str(LIVE_MODULE))

    # Imported, not merely mentioned. The module's own docstring says it
    # deliberately does NOT use dotenv, so a text search for the word failed on
    # the sentence promising the thing it was checking for -- the third time that
    # exact mistake has been made in this repo, hence the AST.
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert "dotenv" not in imported, "dotenv would load the whole file, not two keys"

    exported = [
        f"line {node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"update", "setdefault", "putenv"}
        and "environ" in ast.dump(node.func.value)
    ]
    assert exported == [], f"credentials are exported into the environment: {exported}"
    reader = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_credentials"
        ),
        None,
    )
    assert reader is not None, "no _credentials reader"
    # It must filter against the allow-list, not against a prefix or a regex --
    # `startswith("XTILES")` would happily pick up an XTILES_API_KEY nobody
    # reviewed.
    assert "CREDENTIAL_KEYS" in ast.dump(reader), (
        "_credentials does not filter against the explicit key list"
    )


def test_credentials_never_reach_an_artefact_or_a_message(source: str) -> None:
    """Evidence files and failure messages are read by other people.

    The live checks write screenshots and a text record into the review tree. A
    password interpolated into any of that would be a credential committed to a
    machine's disk in plain sight, and a failure message is the most likely place
    for it to end up — the value is right there in the frame.
    """
    tree = ast.parse(source, filename=str(LIVE_MODULE))
    leaks: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        for part in node.values:
            if not isinstance(part, ast.FormattedValue):
                continue
            rendered = ast.dump(part.value)
            if any(
                token in rendered for token in ("password", "PASSWORD", "credentials", "username")
            ):
                leaks.append(f"line {node.lineno}")
    assert leaks == [], (
        "a credential is interpolated into an f-string that could become a failure "
        f"message or an artefact: {', '.join(leaks)}"
    )


def test_the_host_under_test_is_explicit(source: str) -> None:
    """A dev instance is a different host, and guessing is how you sign the wrong
    credentials into the wrong box.

    The owner's assistant holds an MCP connection to one account; a dev instance
    with its own username and password is somewhere else entirely. The host is
    therefore configurable and https-checked, rather than derived from whatever
    URL happens to be passed in.
    """
    assert "STUDYLOOP_LIVE_XTILES_HOST" in source, "the host is not configurable"
    assert 'DEFAULT_HOST = "https://xtiles.app"' in source
    assert source.count('startswith("https://")') >= 2, (
        "both the host and the target URL must be https-checked; a session cookie "
        "on a plain-http request is a session cookie on the wire"
    )
