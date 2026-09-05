# Second Brain Model Council Results

**Date:** 2026-09-04
**Brief:** [2026-09-04-second-brain-council-brief.md](./2026-09-04-second-brain-council-brief.md)
**Models:** Claude Opus 5, GPT-5.6 Sol, Qwen3 Coder Next
**Coordinator:** Kiro GPT-5.6 Sol

## Council execution

Three different model families reviewed the same written brief independently with read-only repository access:

| Model | Assigned lens | Session |
|---|---|---|
| Claude Opus 5 | Architecture and product invariants | `kiro_e590184e-1616-4899-a830-1e917408499a` |
| GPT-5.6 Sol | Release governance, sequencing, orchestration risk | `kiro_097240b8-dd0b-45ee-bcf4-c7e02a8a59e2` |
| Qwen3 Coder Next | Code feasibility, TDD decomposition, parallel safety | `kiro_eb60f2f9-847b-4a7e-b472-c266e25d0f4e` |

The LiteLLM gateway at `localhost:4040` was unavailable, so direct Kiro model selection provided the family diversity. The original model sessions were exported to the shared session database before arbitration.

## What all three models agreed on

Agreement on these open questions is adopted as evidence:

1. **Release cleanup comes first.** The canonical Second Brain spec and CHANGELOG contradict shipped `0.2.1` behavior. No tag movement or version rewrite is required.
2. **Launch state is not provider capability.** Do not add launch fields to the pinned `BrainDescription` JSON shape and do not add a seventh method to the six-method `SecondBrain` protocol.
3. **Use a separate pure launch resolver.** A new `second_brain/launch.py` module should own target selection, validation, labels, and disabled reasons.
4. **Obsidian exact-path behavior is deterministic.** Prefer the generated `Today.md`, fall back to the vault root, use the official absolute-path URI, and do not gate launching on writability.
5. **xTiles requires an exact persisted destination.** No generic home-page fallback and no direct xTiles client or credentials in StudyLoop.
6. **The server returns inert state.** A read-only GET endpoint returns the launch target. The browser opens it only from an explicit click. No server-side `open`, AppleScript, subprocess, redirect, or launch POST.
7. **The UI has one action on Today.** Settings can show both providers, with inactive providers muted and still offering configuration.
8. **Tests travel with behavior.** No implementation-first wave followed by a test-only cleanup wave.
9. **Parallelism is narrower than it first appears.** Today and Settings share HTML/JS; config and resolver/API contracts must freeze before frontend work.
10. **Installed-wheel behavior is a release gate.** Static assets, API registration, and resolver behavior must be exercised outside an editable checkout.

## What the brief got wrong or omitted

The council corrected the following points:

1. The UI file is `packages/studyloop/src/studyloop/web/static/index.html`, not `web/templates/index.html`.
2. Settings behavior is in `web/static/js/components/settings-panel.js`; Today behavior is in `web/static/components.js`.
3. `write_raw_config()` truncates and rewrites the complete file. Independent CLI and web writers can lose updates. Configuration mutation needs one owner, atomic replacement, and serialization.
4. `BasicAuthMiddleware` is conditional. An HTTP endpoint that writes an xTiles destination could become an unauthenticated LAN configuration mutation. The first release must not add one.
5. Source-checkout installation is already documented. The unresolved artifact question is policy, not missing installation instructions.
6. The archived `0.2.1` OpenSpec change is historical evidence and must not be rewritten. Only the canonical spec is reconciled.
7. Device locality cannot be inferred perfectly behind arbitrary proxies. The safe first release treats direct loopback as local and everything else as remote or unknown; it does not trust forwarding headers.
8. Constraint “one configured-provider action” does not mean an enabled action. xTiles without a validated target correctly has a disabled action and explanation.

## Model positions

### Claude Opus 5

Strongest contributions:

- Kept launch state outside provider capability contracts.
- Separated writability from launchability.
- Proposed `Today.md` then vault-root fallback for Obsidian.
- Favored a standalone xTiles URL sidecar and an MCP persistence tool.
- Favored an Obsidian-first alpha cut, with xTiles persistence following later.

Rejected points:

- A second sidecar duplicates configuration ownership and creates another lifecycle to secure and migrate.
- A new StudyLoop MCP mutation tool is unnecessary when an existing CLI handoff can preserve the assistant-mediated boundary.
- An Obsidian-only release does not satisfy the agreed provider-aware `0.3.0` outcome.

### GPT-5.6 Sol

Strongest contributions:

- Found the whole-file truncating config writer and made configuration mutation a single-owner serial task.
- Found the conditional web authentication risk and rejected an HTTP write endpoint.
- Corrected the actual static file and Settings component paths.
- Required loopback-based locality protection for Obsidian.
- Identified the safe parallel waves: release/spec first; frontend/packaging/docs only after config-resolver-API contracts freeze.
- Required full xTiles persistence in the honest `0.3.0` cut.

Adopted with one adjustment:

- The resolver should consume `SecondBrainConfig` plus explicit locality, not the full `Settings`, to keep its interface narrow and prevent accidental dependency on unrelated configuration.

### Qwen3 Coder Next

Strongest contributions:

- Produced the clearest TDD task slicing and warned that Today and Settings cannot be parallel because they share HTML and JS.
- Required exact byte-level Obsidian URI tests, URL rejection matrices, no-auto-open browser tests, and installed-wheel proof.
- Correctly treated xTiles persistence as a security slice, not merely UI configuration.
- Proposed an Obsidian-first minimum cut when the xTiles contract remains unsettled.

Rejected point:

- The final public cut remains full provider-aware `0.3.0`. Obsidian-first is an internal implementation checkpoint, not a release candidate, because the user explicitly requires both opted-in providers to have honest launch states.

## Arbitration decisions

### A1 — Release cleanup scope

Adopt:

- Update `openspec/specs/second-brain/spec.md` with the shipped wind-down command, connector truth table, exact offer behavior, decline/silence behavior, and plan-first learning record.
- Correct only the false “not written back” CHANGELOG statement.
- Correct the stale active-change link/evidence wording in `docs/architecture/second-brain.md`.
- Add one sentence to `releases/v0.2.1.md` stating that the release is distributed through the documented source-checkout flow; CI artifacts are validation artifacts, not an advertised binary channel.
- Do not change version numbers, the tag, or archived change artifacts. Do not attach assets retroactively.

Cost: keeps `0.2.1` source-only. A future distribution-policy change remains separate work.

### A2 — Launch type and module seam

Adopt:

```python
Provider = Literal["none", "obsidian", "xtiles"]
DeviceLocality = Literal["local", "remote", "unknown", "not_applicable"]

@dataclass(frozen=True)
class LaunchTarget:
    provider: Provider
    label: str
    href: str | None
    enabled: bool
    disabled_reason: str | None
    device_locality: DeviceLocality


def resolve_launch_target(
    config: SecondBrainConfig,
    *,
    locality: DeviceLocality,
) -> LaunchTarget: ...
```

Place it in `packages/studyloop/src/studyloop/second_brain/launch.py`. It imports configuration types but no provider backend.

Cost: a small amount of policy duplication is preferable to coupling navigation to publish availability.

### A3 — Obsidian target policy

Adopt:

1. Require provider `obsidian` and an absolute existing vault directory.
2. For `local` locality, use contained regular file `<vault>/<folder>/Today.md` when present.
3. Otherwise use the vault root.
4. Reject symlink escape and non-regular `Today.md`.
5. Do not require writability.
6. Disable for `remote` or `unknown` locality with an explicit same-device explanation.
7. Produce exactly `obsidian://open?path=` plus `quote(str(path), safe="")`.

Cost: reverse-proxy users receive a conservative false negative until a separately designed trusted-locality override exists.

### A4 — xTiles persistence and validation

Adopt one optional config field under the existing namespace:

```yaml
second_brain:
  provider: xtiles
  xtiles_destination_url: https://xtiles.app/...
```

The field does not select the provider. One atomic mutation service owns all writes. The assistant handoff is:

```bash
studyloop brain destination set --provider xtiles --url '<connector-returned-url>'
```

No HTTP write endpoint and no new xTiles client.

Initial URL policy:

- HTTPS only.
- Exact host allowlist derived from repository evidence: `xtiles.app` and `app.xtiles.app`.
- No userinfo or non-default port.
- Require a non-home path.
- Never log the complete URL.
- Before freezing query/fragment rules, validate one real connector-returned project URL in an opt-in test. Default to rejecting query and fragment unless that evidence proves one is required.

Cost: the assistant performs one extra StudyLoop CLI call after creating or locating the xTiles project.

### A5 — Configuration write safety

Adopt a single configuration mutation service that:

- acquires one process-visible lock;
- rereads the current file after locking;
- validates before mutation;
- preserves unrelated keys;
- writes a sibling temporary file;
- flushes and atomically replaces the destination;
- retains existing permissions;
- cleans temporary files after failure.

Both `brain enable` and `brain destination set` use this service. No frontend config writes ship in `0.3.0`; Settings displays configuration and provides CLI guidance.

Cost: Settings cannot save the URL directly in the first release, avoiding an unauthenticated LAN write path.

### A6 — Web API and UI

Adopt `GET /api/second-brain/launch-target` with `Cache-Control: no-store`. It returns the `LaunchTarget` fields only. The endpoint derives locality from the direct request peer and does not trust forwarding headers.

Today:

- no provider: no launch action;
- selected provider: one visible action, enabled or disabled with a reason;
- xTiles opens in a new tab with `noopener,noreferrer`;
- Obsidian uses direct custom-URI navigation without an empty new tab.

Settings:

- selected provider active;
- inactive provider muted with Configure guidance;
- xTiles without destination explains the CLI handoff;
- no secret or full destination URL displayed.

### A7 — Release cut

Ship only when both provider paths are honest:

- Obsidian exact-path launch works locally.
- xTiles has validated exact destination persistence and launch.
- Missing target, missing vault, and remote/unknown locality have explicit disabled states.
- Today and Settings are complete.
- Installed-wheel and security validation pass.

Defer automatic URL capture, multiple destinations, destination history, per-plan deep links, remote-device support, trusted reverse-proxy locality, and a Settings write endpoint.

Version: `0.3.0`.

## Final execution DAG

```text
Wave 1 (parallel)
  R: v0.2.1 release-story reconciliation
  S: 0.3.0 OpenSpec artifacts

Serial contract spine
  C: atomic config mutation + destination CLI
      |
  O: LaunchTarget + Obsidian/xTiles resolver
      |
  A: read-only launch-target API

Wave 2 (parallel after C/O/A freeze)
  F: Today + Settings UI and JS tests
  P: installed-wheel/security/integration coverage
  D: launcher and locality documentation

Final spine
  I: integration, full deterministic validation, coherent commits
      |
  Council 2: same three families review claims vs code/tests/history
      |
  Fix findings -> rerun validation -> commit/push
```

The config task precedes the resolver because the final config field and mutation API are inputs to the resolver contract. Frontend has one owner because Today and Settings share static files.

## Deterministic validation spine

1. Release cleanup: OpenSpec validation, contradiction search, release consistency.
2. Config tests: atomicity, preservation, concurrent writers, failure cleanup, permissions, URL validation, no full URL in logs.
3. Resolver tests: all provider states, exact URI bytes, Unicode/reserved characters, containment, symlink escape, read-only vault, missing target, locality.
4. API tests: exact schema, `no-store`, no mutation route, direct-peer locality, disabled states.
5. Protocol regression: exact six-method set and pinned `BrainDescription` JSON unchanged.
6. JS tests: action visibility, disabled reasons, one navigation per click, no automatic opening.
7. Browser tests: Today/Settings matrix, exact hrefs, xTiles new-tab protections, Obsidian custom URI, clean console.
8. Installed-wheel smoke: package assets, start app, call route, run resolver outside source checkout.
9. Ruff lint/format, typecheck, Python suite, JS suite, web tests, browser smoke, e2e.
10. Build wheel/sdist and run release consistency/security gates.
11. Record commands, exit codes, pass/skip counts, artifact names, and failing-case assertions.

## Second council review protocol

After implementation, the same three model families receive a new written brief containing:

- this arbitration record and final plans;
- merge base and HEAD;
- ordered commits and each commit's claimed behavior;
- complete changed-file inventory and diff;
- deterministic validation transcript;
- built artifact names and installed-wheel evidence;
- URL security matrix;
- known deviations from the plan.

Each model independently answers:

1. Does code implement every claimed requirement?
2. Are protocol and `BrainDescription` contracts unchanged?
3. Is any server-side launch, direct xTiles client, credential storage, or HTTP config mutation present?
4. Can any untrusted URL escape the allowlist or appear in logs?
5. Can concurrent config writers lose changes?
6. Are all launches explicit user gestures?
7. Do installed-wheel and browser evidence substantiate the claims?
8. Are commits coherent and bisectable?
9. What did all previous reviewers miss?

The coordinator reports agreement and disagreement separately, chooses findings with reasons, fixes every accepted blocker, reruns the deterministic spine, and only then declares delivery complete.