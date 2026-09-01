"""Readiness-budget scaling — absorbs full-suite load without editing 835 waits.

Browser tests are full of fixed readiness budgets: 835 explicit ``timeout=``
arguments across 67 files. Every one was calibrated while running its own file,
where the machine is idle. The full suite runs ~500 browser tests that contend for
CPU, disk and a fixed set of ports, and a budget that is generous in isolation
becomes marginal there.

Three separate tests failed that way in one afternoon -- a 5s wait in the live
session banner, a 20s wait in the representative user journey, and a 4s poll loop
in the WebSocket grace tests -- each passing on every isolated re-run. They were
not the same bug three times; they were the same missing allowance.

The allowance is nearly free, which is the point. A readiness wait that resolves in
200ms costs 200ms whether its ceiling is 5s or 20s: raising the ceiling costs
nothing on success and only lengthens the report of a genuine failure. That is the
right trade for a safety net and the wrong one for an assertion -- a test asserting
"this must appear within 300ms for the UX to be acceptable" is measuring, not
waiting, and scaling it would destroy what it measures. Nothing here touches
``wait_for_timeout``, which is a fixed sleep rather than a budget.

Scaling by collected test count rather than a flag keeps both honest: run one file
and the budgets stay exactly as written, so a real hang still fails fast; run the
suite and they widen.

This lives outside ``conftest.py`` deliberately. Two ``conftest.py`` files exist in
this repo, so ``from conftest import ...`` resolves to whichever one the type
checker finds first -- and a pytest hook file is not a public helper module anyway.
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


def set_scale_for_run(collected: int) -> float:
    """Choose the multiplier from the size of the run, or the env override."""
    global _scale
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        try:
            # Never below 1.0: shrinking every budget would invent failures.
            _scale = max(1.0, float(override))
        except ValueError:
            _scale = 1.0
        return _scale
    if collected < 50:
        _scale = 1.0
    elif collected < 300:
        _scale = 2.0
    else:
        _scale = 3.0
    return _scale


def readiness_scale() -> float:
    """The current readiness multiplier."""
    return _scale


def scaled_seconds(base: float) -> float:
    """Scale a hand-rolled polling budget, in seconds.

    The Playwright patch only reaches Playwright's own waits. A test that polls an
    asyncio condition itself -- ``while not released: await sleep(0.1)`` -- has the
    same load sensitivity and none of the coverage, so it must ask explicitly.

    Prefer a deadline over an iteration count at the call site: ``range(40)`` with a
    0.1s sleep assumes each turn costs only the sleep, which stops being true on
    precisely the loaded machine the budget is for.
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
