## Why

StudyLoop can project learning records to an explicitly configured Second Brain provider, but it gives the learner no safe, provider-aware way to return to that destination from the web interface. Learners must locate the destination manually, and xTiles destinations are not retained, so the configured-provider experience ends at publication instead of supporting the next learning action.

## What Changes

- Add one provider-aware launch affordance that opens the configured provider's exact destination only after an explicit learner click.
- Support exact local Obsidian destinations and exact validated xTiles destinations while preserving explicit provider consent.
- Allow an authorized assistant workflow to retain or clear an exact validated xTiles destination without selecting xTiles or storing xTiles credentials.
- Show honest enabled and disabled launch states on Today and provider status/configuration guidance in Settings.
- Treat missing, invalid, unsafe, or device-incompatible destinations as disabled states with actionable explanations rather than generic fallbacks.
- Preserve the existing Second Brain publication protocol and provider capability contract.
- Exclude direct xTiles API access, web-based configuration mutation, server-side application launching, automatic navigation, remote-device Obsidian support, destination history, and multiple destinations.
- Release the additive capability as StudyLoop 0.3.0 with installed-package, browser, and security evidence.

## Capabilities

### New Capabilities
- `second-brain-launcher`: Provider-aware destination retention, launch-state resolution, read-only web exposure, explicit learner navigation, honest Today and Settings states, and installed-package/security guarantees for Obsidian and xTiles.

### Modified Capabilities
- `configuration-and-secrets`: Extend the existing Second Brain configuration contract with optional validated xTiles destination retention and serialized, atomic, permission-preserving mutation that does not discard unrelated settings.
## Impact

- Second Brain configuration and its CLI management workflow gain exact xTiles destination retention with stronger write-safety guarantees.
- The web API, Today surface, and Settings surface gain provider launch state without gaining configuration-write authority.
- Obsidian navigation is limited to same-device browser sessions; xTiles navigation is limited to reviewed destination hosts.
- Package contents, release validation, user documentation, and version metadata expand to cover the launcher capability.
