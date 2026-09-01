"""One credential-scrubbing rule for every agent child process.

An agent subprocess is not a trusted peer. It is a third-party binary the
learner chose, driven by a model, and in the ACP case it is explicitly granted
filesystem read and write. Whatever is in its environment is available to it,
and to anything it runs.

This lived inside the PTY transport, which meant the PTY child had its
credentials stripped while the ACP child inherited the whole environment --
``os.environ.copy()`` in one place, and no ``env=`` at all in the other, which
inherits by default. Two transports doing the same job with opposite postures is
the kind of gap that survives review precisely because each file looks
reasonable alone.

Deny, not allow: an allowlist of environment keys would break agents that need
XDG paths, proxy settings, locale, editor configuration or their own
provider-specific variables, and each breakage would be reported as "the agent
does not work" long after the cause. The pattern catches the shape credential
variables actually take.
"""

from __future__ import annotations

import os
import re

#: Keys never passed to a child regardless of shape.
#:
#: STUDYLOOP_TEST_AGENT_CMD is the test harness's escape hatch for substituting a
#: fake agent; a real child inheriting it could re-enter the harness path.
#: STUDYLOOP_CONFIG would point the child at the parent's config, including its
#: configured paths.
CHILD_ENV_DENY: frozenset[str] = frozenset(
    {
        "STUDYLOOP_TEST_AGENT_CMD",
        "STUDYLOOP_CONFIG",
    }
)

#: Suffix match on the shape credentials are conventionally named.
#:
#: Anchored at the end so AWS_SECRET_ACCESS_KEY-style names are caught by the
#: KEY-bearing rule below rather than by accident, and so a legitimate name like
#: TOKENIZERS_PARALLELISM is not swept up -- it does not END in 'token'.
CHILD_ENV_DENY_PAT = re.compile(r"(?i)(password|secret|token|api_key|access_key)$")


def build_child_env(caller_env: dict[str, str] | None = None) -> dict[str, str]:
    """Return the environment for an agent child, with credentials removed.

    Pass ``caller_env`` to scrub something other than the current process
    environment; the default is ``os.environ``.
    """
    source = os.environ if caller_env is None else caller_env
    clean: dict[str, str] = {}
    for key, value in source.items():
        if key in CHILD_ENV_DENY:
            continue
        if CHILD_ENV_DENY_PAT.search(key):
            continue
        clean[key] = value
    return clean
