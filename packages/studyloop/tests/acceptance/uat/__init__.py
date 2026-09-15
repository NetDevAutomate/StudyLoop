"""Reserved layout for the UAT (sign-off) tier — lane B4's job, not B1's.

The UAT tier gets its OWN additional opt-in on top of acceptance
(``STUDYLOOP_UAT=1``, a later lane's contract) and lives under this
subtree specifically so that a plain ``testacc``-shaped invocation never
collects it — see the ``--ignore`` flag on the ``testacc`` recipe in the
Justfile and ``docs/acceptance-testing.md``. This package is intentionally
empty until B4 lands; its presence alone is what keeps the reservation
real rather than aspirational documentation.
"""

from __future__ import annotations
