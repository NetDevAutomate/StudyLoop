## Purpose

Provide one safe, provider-aware path from StudyLoop back to the learner's exact configured Second Brain destination without changing publication contracts or opening anything without an explicit learner gesture.

## ADDED Requirements

### Requirement: `studyloop.second_brain.launch` resolves one inert provider launch target
`studyloop.second_brain.launch.resolve_launch_target()` SHALL return a launch
target containing exactly `provider`, `label`, `href`, `enabled`,
`disabled_reason`, and `device_locality`. A disabled target SHALL have no
`href`, and an enabled target SHALL have an `href` and no disabled reason.
The resolver SHALL NOT extend `SecondBrain` or `BrainDescription`.

#### Scenario: No provider is selected
- **GIVEN** `second_brain.provider` is `none`
- **WHEN** the launch target is resolved
- **THEN** the target provider is `none`
- **AND** the target is disabled with no `href`

#### Scenario: Stable publication contracts are inspected
- **GIVEN** the launcher capability is installed
- **WHEN** the `SecondBrain` protocol and `BrainDescription` serialization are inspected
- **THEN** the protocol still exposes exactly six methods
- **AND** the serialized description still exposes its pinned keys only

### Requirement: `resolve_launch_target()` selects a contained Obsidian path deterministically
For a selected Obsidian provider and local device, the resolver SHALL prefer the
contained regular file `<vault_path>/<folder>/Today.md` when it exists. If that
path is absent, non-regular, or resolves outside the vault, the resolver SHALL
fall back to the existing absolute vault directory. It SHALL encode the chosen
absolute path as `obsidian://open?path=` followed by percent encoding with no
safe characters.

#### Scenario: Today projection exists
- **GIVEN** the configured Obsidian vault exists
- **AND** `<vault_path>/<folder>/Today.md` is a contained regular file
- **WHEN** the local launch target is resolved
- **THEN** the target is enabled for the percent-encoded absolute `Today.md` path

#### Scenario: Today projection is unavailable or unsafe
- **GIVEN** the configured Obsidian vault exists
- **AND** `Today.md` is missing, non-regular, or escapes through a symlink
- **WHEN** the local launch target is resolved
- **THEN** the target is enabled for the percent-encoded absolute vault root
- **AND** no escaping path appears in the target

#### Scenario: Reserved and Unicode characters occur in the path
- **GIVEN** the chosen absolute path contains spaces, Unicode, `#`, `?`, or `%`
- **WHEN** the local launch target is resolved
- **THEN** every non-URI-prefix character is percent encoded exactly once

### Requirement: Obsidian launchability is local and independent of writability
`resolve_launch_target()` SHALL enable Obsidian only when the direct browser
device locality is `local` and the configured absolute vault directory exists.
It SHALL NOT require the vault or target to be writable. Locality `remote` or
`unknown` SHALL produce no `href` and SHALL explain that Obsidian can open only
on the device running StudyLoop.

#### Scenario: Read-only local vault exists
- **GIVEN** the configured absolute Obsidian vault exists and is read-only
- **AND** device locality is `local`
- **WHEN** the launch target is resolved
- **THEN** the target is enabled

#### Scenario: Browser is remote or locality is unknown
- **GIVEN** Obsidian is selected
- **AND** device locality is `remote` or `unknown`
- **WHEN** the launch target is resolved
- **THEN** the target is disabled with no `href`
- **AND** the disabled reason states the same-device limitation

#### Scenario: Configured vault is unavailable
- **GIVEN** Obsidian is selected
- **AND** the configured vault is missing, relative, or not a directory
- **WHEN** the launch target is resolved
- **THEN** the target is disabled without exposing another filesystem path

### Requirement: xTiles launches only an exact retained destination
`resolve_launch_target()` SHALL enable xTiles only when xTiles is the selected
provider and `SecondBrainConfig.xtiles_destination_url` contains a validated
exact destination. A retained destination SHALL NOT select xTiles. Missing or
invalid destinations SHALL produce no `href` and SHALL provide configuration
guidance rather than a generic xTiles home fallback.

#### Scenario: Selected xTiles provider has an exact destination
- **GIVEN** xTiles is selected
- **AND** a validated exact xTiles destination is retained
- **WHEN** the launch target is resolved
- **THEN** the target is enabled with that exact destination as its `href`
- **AND** device locality is `not_applicable`

#### Scenario: Selected xTiles provider has no destination
- **GIVEN** xTiles is selected
- **AND** no destination is retained
- **WHEN** the launch target is resolved
- **THEN** the target is disabled with no generic fallback `href`
- **AND** the disabled reason names the destination configuration command

#### Scenario: Destination exists while provider is not xTiles
- **GIVEN** an xTiles destination is retained
- **AND** the selected provider is `none` or `obsidian`
- **WHEN** the launch target is resolved
- **THEN** no xTiles launch target is enabled

### Requirement: The brain destination commands retain xTiles URLs without changing consent
`studyloop brain destination set --provider xtiles --url URL` and
`studyloop brain destination clear --provider xtiles` in
`studyloop.cli._brain` SHALL retain or clear the destination through the
configuration mutation contract without changing `second_brain.provider`.
Human output SHALL show only the host; JSON output SHALL show provider,
configured state, and config path but not the complete URL.

#### Scenario: Assistant retains a destination before provider selection
- **GIVEN** `second_brain.provider` is `none`
- **WHEN** a valid xTiles destination is set
- **THEN** the destination is retained
- **AND** the provider remains `none`

#### Scenario: Destination output is machine-readable and redacted
- **GIVEN** a destination containing a sensitive path is set with `--json`
- **WHEN** command output and logs are captured
- **THEN** the complete URL is absent
- **AND** output reports xTiles as configured with the config path

#### Scenario: Assistant clears a retained destination
- **GIVEN** xTiles is selected and an exact destination is retained
- **WHEN** the destination is cleared with `--json`
- **THEN** the destination becomes absent and xTiles remains selected
- **AND** redacted output reports xTiles as not configured with the config path

### Requirement: The launch-target API is read-only, direct-peer-aware, and non-cacheable
`GET /api/second-brain/launch-target` SHALL return exactly the launch-target
fields with `Cache-Control: no-store`. The route SHALL derive Obsidian locality
from the direct request peer, treating loopback as local and all other or missing
peers as remote or unknown, without trusting forwarding headers. Invalid Second
Brain configuration SHALL return a generic disabled target with no `href` and
reason `Second Brain configuration is invalid.` When the raw provider is a
recognized value, the fallback SHALL retain that provider and its label; an
unrecognized provider SHALL return provider `none`, label `Second Brain`, and
locality `unknown`. Neither response nor logs SHALL include an invalid value. No
mutation method SHALL exist at this route.

#### Scenario: Loopback browser requests Obsidian state
- **GIVEN** a valid Obsidian configuration
- **AND** the direct request peer is loopback
- **WHEN** the launch-target endpoint is requested
- **THEN** the response is HTTP 200 with locality `local`
- **AND** `Cache-Control` is `no-store`

#### Scenario: Forwarded headers claim loopback
- **GIVEN** the direct request peer is non-loopback
- **AND** a forwarding header claims a loopback client
- **WHEN** the launch-target endpoint is requested
- **THEN** the forwarding header is ignored
- **AND** the Obsidian target is disabled

#### Scenario: Configuration contains an invalid destination
- **GIVEN** the retained Second Brain destination is invalid
- **AND** the raw provider is the recognized value `xtiles`
- **WHEN** the launch-target endpoint is requested
- **THEN** the response contains a generic disabled xTiles state with no `href`
- **AND** neither response nor logs contain the invalid value

#### Scenario: Configuration contains an unrecognized provider
- **GIVEN** the raw Second Brain provider is not recognized
- **WHEN** the launch-target endpoint is requested
- **THEN** the response is disabled with provider `none`, label `Second Brain`, and locality `unknown`
- **AND** the disabled reason is `Second Brain configuration is invalid.`
- **AND** neither response nor logs contain the invalid value

#### Scenario: Client attempts configuration mutation
- **GIVEN** the launch-target route exists
- **WHEN** a client sends POST, PUT, PATCH, or DELETE to that route
- **THEN** no configuration mutation handler accepts the request

### Requirement: Today and Settings show honest provider-aware launcher states
The Today surface SHALL render at most one action for the selected provider and
no launcher action for provider `none`. A disabled action SHALL display the API
reason and SHALL not navigate. The Settings Second Brain section SHALL highlight
the selected provider, mute inactive providers with configuration guidance, and
show the xTiles destination command pattern when the destination is missing. It
SHALL NOT display the complete xTiles URL or offer a web save control.

#### Scenario: Today has an enabled configured provider
- **GIVEN** the launch API returns one enabled provider target
- **WHEN** Today renders
- **THEN** exactly one enabled Second Brain action is visible

#### Scenario: Today has a disabled configured provider
- **GIVEN** the launch API returns one disabled provider target
- **WHEN** Today renders
- **THEN** exactly one disabled action and its explanation are visible
- **AND** activating it performs no navigation

#### Scenario: Settings shows selected and inactive providers
- **GIVEN** one Second Brain provider is selected
- **WHEN** Settings renders
- **THEN** the selected provider is active and the other provider is muted
- **AND** guidance is visible without a complete retained URL or save control

### Requirement: Every provider navigation originates from one explicit browser gesture
The browser SHALL perform no Second Brain navigation during initialization,
refresh, publication, wind-down, or launch-state loading. An enabled xTiles click
SHALL open the exact destination once in a new tab with `noopener,noreferrer`.
An enabled Obsidian click SHALL navigate the current context to the custom URI
without creating an empty tab. No server module SHALL invoke a subprocess,
desktop command, redirect, or direct xTiles network client for launching.

#### Scenario: Page loads with an enabled target
- **GIVEN** the launch API returns an enabled target
- **WHEN** the page initializes or refreshes
- **THEN** no provider navigation occurs

#### Scenario: Learner clicks enabled xTiles action
- **GIVEN** the enabled target provider is xTiles
- **WHEN** the learner clicks the action once
- **THEN** the exact destination opens once in a new protected tab

#### Scenario: Learner clicks enabled Obsidian action
- **GIVEN** the enabled target provider is Obsidian
- **WHEN** the learner clicks the action once
- **THEN** the current browser context navigates once to the custom URI
- **AND** no empty tab is created

### Requirement: Installed StudyLoop packages contain and serve the complete launcher
The built StudyLoop 0.3.0 wheel with web dependencies SHALL provide the resolver,
registered launch-target route, Today and Settings markup, and every JavaScript
module required by the launcher when installed into an isolated environment that
does not import from the source checkout.

#### Scenario: Fresh environment installs the built wheel
- **GIVEN** a newly built StudyLoop 0.3.0 wheel
- **AND** an isolated environment outside the repository checkout
- **WHEN** the wheel with web dependencies is installed and the web app starts
- **THEN** the launch-target route responds successfully
- **AND** packaged static assets contain and load the launcher behavior
