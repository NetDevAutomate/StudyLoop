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
#: DATABASE_URL is named explicitly because its SHAPE is innocent while its VALUE
#: routinely embeds a password (postgres://user:pw@host/db). No pattern over key
#: names can catch that, and an agent child has no business holding the app's
#: database credentials.
CHILD_ENV_DENY: frozenset[str] = frozenset(
    {
        "STUDYLOOP_TEST_AGENT_CMD",
        "STUDYLOOP_CONFIG",
        "DATABASE_URL",
    }
)

#: Suffix match, for names that END in a credential word.
#:
#: Anchored so an innocent name is not swept up: TOKENIZERS_PARALLELISM does not
#: end in 'token', and TOKEN_BUDGET_HINT names a budget rather than a secret.
#: Over-broad scrubbing is its own failure mode -- it breaks agents for reasons
#: nobody can see, which trains people to disable the protection.
CHILD_ENV_DENY_PAT = re.compile(
    r"(?i)(password|passwd|secret|token|api_key|access_key|credentials|private_key)$"
)

#: Segment match, for credential words that appear MID-NAME.
#:
#: The suffix rule alone was not enough, and the gap was not hypothetical:
#: AWS_BEARER_TOKEN_BEDROCK is the credential this project's own Bedrock
#: generators use on their profile-less fast path, and it ends in BEDROCK, so a
#: suffix-only rule handed it straight to the agent child. GOOGLE_APPLICATION_-
#: CREDENTIALS and AZURE_CLIENT_SECRET_ID have the same shape.
#:
#: Matched on underscore-delimited segments rather than as bare substrings, which
#: is what keeps TOKENIZERS_PARALLELISM: its segments are TOKENIZERS and
#: PARALLELISM, neither of which is TOKEN.
CHILD_ENV_DENY_SEGMENT_PAT = re.compile(
    r"(?i)(^|_)("
    r"bearer_token|auth_token|access_token|refresh_token|id_token"
    r"|api_key|access_key|secret_key|private_key|client_secret"
    r"|secret|password|passwd|credentials"
    r")(_|$)"
)


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
        if CHILD_ENV_DENY_SEGMENT_PAT.search(key):
            continue
        clean[key] = value
    return clean
