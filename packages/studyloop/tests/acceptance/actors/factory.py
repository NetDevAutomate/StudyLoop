"""``get_actor`` -- the factory keyed off ``STUDYLOOP_ACC_ACTOR``.

Same idiom as ``content/generators/get_generator`` (council D-15): a known
name maps to a concrete backend; an unknown name is a loud
:class:`~acceptance.actors.protocol.ActorError`, never a silent no-op or a
skip.

:func:`skip_reason` is the OTHER half of the contract, kept separate on
purpose: "credentials/config via env with clear skip reasons when absent
(no key -> skip naming the variable; never fail, never prompt)" (council
D-15) only applies to a KNOWN actor missing its config -- an unknown name
is still a hard failure even from this function (docs/acceptance-testing.md,
"Rules that keep the tier honest": "unknown selection value -> loud
failure").
"""

from __future__ import annotations

import os
import shutil
from typing import TYPE_CHECKING

from acceptance.actors.protocol import ActorError, LearnerActor

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from acceptance.actors.budget import BudgetGuard
    from acceptance.turn_script import TurnScript

#: Every ``STUDYLOOP_ACC_ACTOR`` value this package answers to. The single
#: source of truth ``tests/acceptance/conftest.py`` imports for its own gate
#: (docs/acceptance-testing.md's "unknown selection value -> loud failure"
#: rule applies at that layer too, before an actor is ever constructed).
KNOWN_ACTORS = frozenset({"scripted", "gateway", "direct", "harness"})


def skip_reason(
    actor: str,
    *,
    env: Mapping[str, str] | None = None,
    turn_script: TurnScript | None = None,
) -> str | None:
    """Return a named skip reason if ``actor`` cannot run right now, else ``None``.

    Only classifies a KNOWN actor's availability -- never fails for a
    missing key or binary, always naming the specific variable or binary
    that is missing. Raises :class:`ActorError` for an unknown actor name
    (that is a typo, not something to skip past -- see the module
    docstring).
    """
    if actor not in KNOWN_ACTORS:
        raise ActorError(f"unknown actor {actor!r}; known actors: {sorted(KNOWN_ACTORS)}")

    resolved_env: Mapping[str, str] = os.environ if env is None else env

    if actor == "scripted":
        if turn_script is None:
            return "scripted actor requires a turn_script (no env variable names this)"
        return None

    if actor == "gateway":
        from acceptance.actors.gateway import ENV_API_KEY, ENV_MODEL

        missing = [name for name in (ENV_API_KEY, ENV_MODEL) if not resolved_env.get(name)]
        if missing:
            return f"missing {', '.join(missing)}"
        return None

    if actor == "direct":
        from acceptance.actors.direct import (
            DEFAULT_PROVIDER,
            ENV_PROVIDER,
            resolve_direct_profile,
        )

        provider = (resolved_env.get(ENV_PROVIDER) or DEFAULT_PROVIDER).strip()
        # An unknown/unsupported provider slug is a loud failure (a typo),
        # not a skip -- let ActorError propagate.
        profile = resolve_direct_profile(provider)
        if not resolved_env.get(profile.auth_env):
            return f"missing {profile.auth_env}"
        return None

    if actor == "harness":
        from acceptance.actors.harness import ENV_COMMAND

        if shutil.which("tmux") is None:
            return "tmux binary not found on PATH"
        if not resolved_env.get(ENV_COMMAND):
            return f"missing {ENV_COMMAND}"
        return None

    msg = f"actor {actor!r} is in KNOWN_ACTORS but skip_reason forgot it"
    raise AssertionError(msg)  # pragma: no cover


def get_actor(
    actor: str,
    *,
    turn_script: TurnScript | None = None,
    budget: BudgetGuard | None = None,
    system_prompt: str | None = None,
    env: Mapping[str, str] | None = None,
    harness_command: Sequence[str] | None = None,
    harness_socket_dir: Path | None = None,
) -> LearnerActor:
    """Build the concrete :class:`LearnerActor` for ``actor``.

    Raises :class:`ActorError` for an unknown actor name, or if a KNOWN
    actor's required config is missing -- callers should call
    :func:`skip_reason` first and skip by name rather than let this
    function raise for an absent credential.
    """
    if actor not in KNOWN_ACTORS:
        raise ActorError(f"unknown actor {actor!r}; known actors: {sorted(KNOWN_ACTORS)}")

    resolved_env: Mapping[str, str] = os.environ if env is None else env

    if actor == "scripted":
        from acceptance.actors.scripted import ScriptedActor

        if turn_script is None:
            raise ActorError("scripted actor requires turn_script=")
        return ScriptedActor(turn_script, budget=budget)

    if actor == "gateway":
        from acceptance.actors.gateway import GatewayActor

        return GatewayActor.from_env(resolved_env, budget=budget, system_prompt=system_prompt)

    if actor == "direct":
        from acceptance.actors.direct import DirectActor

        return DirectActor.from_env(resolved_env, budget=budget, system_prompt=system_prompt)

    if actor == "harness":
        from acceptance.actors.harness import HarnessActor

        if harness_socket_dir is None:
            raise ActorError(
                "harness actor requires harness_socket_dir= (its OWN tmux socket, D-11)"
            )
        return HarnessActor.from_env(
            resolved_env,
            socket_dir=harness_socket_dir,
            harness_command=harness_command,
            budget=budget,
        )

    msg = f"actor {actor!r} is in KNOWN_ACTORS but get_actor forgot it"
    raise AssertionError(msg)  # pragma: no cover


__all__ = ["KNOWN_ACTORS", "get_actor", "skip_reason"]
