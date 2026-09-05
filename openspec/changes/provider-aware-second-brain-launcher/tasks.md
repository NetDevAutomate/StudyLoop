## 1. Assistant can retain a safe xTiles destination without changing provider consent

- [ ] 1.1 Add optional validated xTiles destination parsing and redacted validation errors, verified by configuration tests covering accepted hosts, the complete rejection matrix, compatibility, and provider-selection isolation.
- [ ] 1.2 Make every raw configuration mutation serialized, complete-result-validated, file-data-synced, atomic, permission-preserving, and failure-clean, verified by concurrency, reread-after-lock, unrelated-key, invalid-mutator, flush/sync, mode, replacement-failure, and temporary-file tests.
- [ ] 1.3 Add destination set and clear behavior to the brain CLI and migrate brain enable to the shared mutation owner, verified by command discovery, host-only human output, JSON fields for provider/configured/config path, complete-URL exclusion, and unchanged provider consent.

## 2. Configured providers resolve to exact and honest launch targets

- [ ] 2.1 Add the immutable provider-neutral launch target and resolver, verified by the full none/Obsidian/xTiles truth table, the disabled-target invariant, and an import-boundary test proving launch policy has no provider-backend, network, web, or subprocess dependency.
- [ ] 2.2 Enforce exact Obsidian containment, fallback, percent encoding, read-only-vault, and locality behavior, verified by path, symlink, reserved-character, Unicode, and remote/unknown tests.
- [ ] 2.3 Preserve the exact SecondBrain protocol and BrainDescription contracts, verified by the existing protocol and provider factory regression suites.

## 3. Browser clients can read safe launch state without gaining write authority

- [ ] 3.1 Add the non-cacheable launch-target route with direct-peer locality and generic redacted invalid-config fallback, verified by exact-schema, loopback, forwarding-header, provider-state, and disclosure tests.
- [ ] 3.2 Register the route before static handling and keep every mutation method, server-side desktop launch, redirect, subprocess path, and direct xTiles network client absent, verified by application routing, dependency-boundary, and repository web-gate tests.

## 4. Learner can launch one configured provider only from an explicit click

- [ ] 4.1 Extract Today state into an importable module and load launch state without navigation, verified by Node tests for initialization, none, enabled, disabled, and refresh behavior.
- [ ] 4.2 Add one selected-provider Today action with protected xTiles and current-context Obsidian click behavior, verified by unit and marked browser tests for one navigation per click and no automatic opening.
- [ ] 4.3 Add active, muted, disabled, and configuration-guidance states to the Settings Second Brain section without URL disclosure or web saving, verified by Node and marked browser state-matrix tests with a clean console.

## 5. Learner can install and trust the complete 0.3.0 launcher release

- [ ] 5.1 Add an isolated installed-wheel web smoke that starts the packaged application, requests launch state, and loads every launcher asset; wire it into the release gate and verify it cannot import from the checkout.
- [ ] 5.2 Record redacted connector evidence that an accessible xTiles page URL is HTTPS on exact host `xtiles.app`, has a non-home path, and has no userinfo, port, query, or fragment; verify the strict validator accepts that shape while continuing to reject query and fragment.
- [ ] 5.3 Document same-device Obsidian behavior, the assistant destination handoff, honest disabled states, explicit-click navigation, and Settings guidance; update 0.3.0 version and release metadata and verify release consistency.
- [ ] 5.4 Run formatting, lint, Pyright, Python, JavaScript, web, browser, end-to-end, OpenSpec, security, build, and installed-artifact gates; record exact outcomes and repair every failure before release review.
