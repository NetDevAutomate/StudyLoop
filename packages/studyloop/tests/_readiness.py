"""Readiness-budget scaling — an opt-in diagnostic, never a release configuration.

Browser tests carry 835 explicit ``timeout=`` arguments across 67 files, each
calibrated while running its own file on an idle machine. The full suite runs
~500 browser tests contending for CPU, disk and a fixed set of ports, so a
budget that is generous in isolation can become marginal there.

This module can multiply those budgets. It is switched on ONLY by
``STUDYLOOP_E2E_TIMEOUT_SCALE`` and is a no-op otherwise.

Why it is no longer automatic
-----------------------------
The multiplier used to be chosen from the number of collected tests, which made
a test's meaning depend on a property of the run rather than on the test. Two
measured consequences:

* ``pytest`` with its default selection collects 3599 items and so chose 3.0
  while running zero browser tests -- the patch was installed for nothing.
* ``test_session_ws_grace.py`` is a unit test with no browser at all, yet its
  4s poll silently became 12s because an unrelated selection was large.

A run whose sensitivity varies with how it was invoked cannot be reported
honestly, and printing the multiplier would have made the altered semantics
visible without making them valid. Load allowance now belongs in the budget at
the call site, as a justified fixed ceiling: a generous ceiling costs nothing on
success and is INVARIANT, which is the property the multiplier lacked.

What was NOT the reason
-----------------------
An earlier version of this docstring claimed three failures were "the same
missing allowance". That was not established. The HTTP 500 in
``e2e/test_ws_grace_real_server.py`` was a file-deletion race in the product
(session teardown unlinking IPC files mid-request), reachable with no browser
involved, and that test contains no scaled call. The dialog failure in
``test_web_session_lifecycle.py`` was a 200ms sleep racing an
``x-transition.opacity`` fade measured at 187ms. Both are fixed at the source.

The remaining honest argument for an allowance is narrower: for a POLLING wait,
a wider ceiling grants more retries, so an intermittent server error followed by
a success becomes indistinguishable from clean. That is a masking channel, which
is why the per-test server-error detectors in ``conftest.py`` and ``e2e/_env.py``
exist and must stay independent of any timeout.

Living outside ``conftest.py`` is deliberate: two ``conftest.py`` files exist in
this repo, so ``from conftest import ...`` resolves to whichever one the type
checker finds first -- and a pytest hook file is not a public helper module.
"""

from __future__ import annotations

import functools
import os
from typing import Any

#: Playwright calls whose ``timeout`` is a readiness budget. Deliberately not
#: ``expect(...)`` assertions, ``click`` or ``fill``: those failing on time is a
#: signal about the application, not about how loaded the machine is.
SCALED_CALLS: tuple[tuple[str, str], ...] = (
    ("Page", "wait_for_function"),
    ("Page", "wait_for_selector"),
    ("Locator", "wait_for"),
)

ENV_OVERRIDE = "STUDYLOOP_E2E_TIMEOUT_SCALE"

_scale = 1.0


def configure_scale() -> float:
    """Set the multiplier from the environment. 1.0 unless explicitly asked.

    Takes no argument on purpose. It used to take the collected test count and
    pick 1.0/2.0/3.0 from thresholds, which is what made a test's budget depend
    on how many unrelated tests were selected alongside it.
    """
    global _scale
    override = os.environ.get(ENV_OVERRIDE)
    if not override:
        _scale = 1.0
        return _scale
    try:
        # Never below 1.0: shrinking every budget would invent failures.
        _scale = max(1.0, float(override))
    except ValueError:
        _scale = 1.0
    return _scale


def scale_is_explicit() -> bool:
    """True when a multiplier was requested via the environment."""
    return bool(os.environ.get(ENV_OVERRIDE)) and _scale != 1.0


def readiness_scale() -> float:
    """The current readiness multiplier."""
    return _scale


def scaled_seconds(base: float) -> float:
    """Scale a hand-rolled polling budget, in seconds. Usually a no-op.

    Returns ``base`` unchanged unless ``STUDYLOOP_E2E_TIMEOUT_SCALE`` is set, so
    this is a diagnostic lever rather than a way to size a budget. If a poll
    needs more headroom, raise its base to a justified fixed ceiling instead --
    an invariant number a reader can check against the thing being waited for.

    Prefer a deadline over an iteration count at the call site: ``range(40)``
    with a 0.1s sleep assumes each turn costs only the sleep, which stops being
    true on precisely the loaded machine the budget is for.
    """
    return base * _scale


def install_scaling() -> list[tuple[Any, str, Any]]:
    """Patch the readiness calls to multiply an explicit ``timeout``.

    Returns what to hand back to :func:`remove_scaling`. A no-op at scale 1.0, so
    an isolated run carries no wrapper at all.

    Patches the methods rather than editing 835 call sites: the call sites are not
    individually wrong, they are collectively calibrated for a quieter machine than
    the full suite provides. Calls passing no ``timeout`` are left alone -- they
    already inherit Playwright's 30s default, more headroom than anything scaled
    here. ``timeout`` is keyword-only on all three, so a positional cannot slip
    past the wrapper; a test asserts that.
    """
    if _scale == 1.0:
        return []
    try:
        import playwright.sync_api as pw
    except ImportError:  # pragma: no cover - browser extra not installed
        return []

    def scaled(original):
        @functools.wraps(original)
        def wrapper(*args, **kwargs):
            given = kwargs.get("timeout")
            if given:
                kwargs["timeout"] = given * _scale
            return original(*args, **kwargs)

        return wrapper

    patched: list[tuple[Any, str, Any]] = []
    for class_name, method_name in SCALED_CALLS:
        cls = getattr(pw, class_name, None)
        if cls is None:
            continue
        original = getattr(cls, method_name, None)
        if original is None:
            continue
        patched.append((cls, method_name, original))
        setattr(cls, method_name, scaled(original))
    return patched


def remove_scaling(patched: list[tuple[Any, str, Any]]) -> None:
    """Put back everything :func:`install_scaling` borrowed."""
    for cls, method_name, original in patched:
        setattr(cls, method_name, original)
