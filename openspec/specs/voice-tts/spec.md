## Purpose

Provide text-to-speech for study review and recap narration across two
distinct surfaces: a browser-only neural TTS engine (the web default) and
an optional local macOS OpenVox backend for terminal/MCP contexts. There is
deliberately no server-side TTS for the web path.

## Requirements

### Requirement: Browser TTS is the default and only web-path backend
The system SHALL synthesize speech entirely client-side in the browser via
`tts-engine.js`, tiered `neural-webgpu → neural-wasm → web-speech`, using
Kokoro-82M via `transformers.js`/`onnxruntime-web`. The FastAPI server
SHALL only serve the static engine module and vendored ONNX-runtime WASM;
it SHALL NOT proxy or synthesize audio server-side for the web review
surface.

#### Scenario: Reviewing a flashcard with voice enabled in the browser
- **WHEN** a user presses the speaker button / `T` key on a review card
- **THEN** synthesis happens on-device via the tiered engine; no request
  is sent to the StudyLoop server for audio generation

#### Scenario: First page load, no cached model
- **WHEN** the browser has never fetched the Kokoro model before
- **THEN** the model (~92 MB, quantized ONNX) downloads once from Hugging
  Face and is cached in IndexedDB; subsequent loads (including fully
  offline) reuse the cached model with no further network dependency

### Requirement: Terminal/CLI/MCP voice defaults to local kokoro-onnx
`study-speak` and the CLI's `--speak`/`--audio-file` paths SHALL default
`tts.backend` to `kokoro` (local `kokoro-onnx`, measured ~1.5s
time-to-first-audio), keeping `openvox` as an explicit opt-in
(`tts.backend: openvox`) rather than an automatic preference — measured
OpenVox warm latency (2.9–3.8s) is too slow for the live-narration default
path, though acceptable for recap/teaching-moment narration when
explicitly configured.

#### Scenario: User has not configured a tts.backend
- **WHEN** `studyloop recap today --speak` runs with no `tts.backend`
  override in `config.yaml`
- **THEN** local `kokoro-onnx` is used, not OpenVox

#### Scenario: User explicitly sets tts.backend: openvox
- **WHEN** `tts.backend: openvox` is set and the OpenVox app is running on
  `localhost:8000`
- **THEN** `_speak_openvox()` (`speak.py`) calls OpenVox's
  OpenAI-compatible `/v1/audio/speech` endpoint and plays the returned WAV
  via `afplay`

### Requirement: doctor reports voice backend health
`doctor/voice.py` SHALL report a `voice` category check that inspects
`tts.backend`: for `kokoro`, it checks for the cached ONNX model and
voices file under `~/.cache/kokoro-onnx/`; for `openvox`, it probes
reachability of the configured `openvox_base_url`.

#### Scenario: openvox backend configured but app not running
- **WHEN** `tts.backend: openvox` is set and nothing is listening on the
  configured base URL
- **THEN** `studyloop doctor` reports the `openvox_api` check as failing
  with a repair hint to start OpenVox or set `backend: kokoro` under the
  `tts:` section (hint rephrased as nested YAML in `a7eabb6`; see below)

### Requirement: load_raw_config expands dotted top-level keys before any consumer reads tts.backend
`settings.load_raw_config()` SHALL expand top-level dotted keys (for
example `tts.backend: openvox`) into nested mappings (`tts: {backend:
openvox}`) via `_expand_dotted_keys()` before returning, so that every
consumer of `raw.get("tts", {})` — `doctor/voice.py::_tts_config()` and
`learning/voice.py:57` — sees the same shape regardless of whether the
user's config uses the flat or nested form. On conflict between a dotted
key and an explicit nested mapping for the same path, the nested mapping
SHALL win.

This closes a defect (fixed in `a7eabb6`) where two of `doctor/voice.py`'s
own repair messages were worded as a flat dotted key
(`"Set tts.backend: openvox to enable this check"`) — a user following
them literally would write a top-level `tts.backend: openvox` scalar key,
which `raw.get("tts", {})` could not see (there was no `"tts"` key, only a
literal key named `"tts.backend"`), silently keeping `backend` at its
`"kokoro"` default and skipping the `openvox_api` check the hint promised
to enable. `a7eabb6` fixes this at the loader level (`_expand_dotted_keys()`
in `settings.py`, benefiting all 6 `raw.get("tts", ...)`-style consumers at
once) and rephrases both `doctor/voice.py` repair hints to describe the
nested form (`"Set backend: openvox under the tts: section of
config.yaml..."`, `doctor/voice.py:105-106`) so new users are no longer
taught the broken flat form, while the loader still accepts it from
existing configs. Regression tests in `test_settings_custom.py`
(`test_dotted_top_level_key_expands_to_nested`,
`test_nested_wins_over_dotted_on_conflict`,
`test_doctor_voice_honors_flat_tts_backend`, and others) lock the fix;
full suite 2872 passed, 0 failed per the commit message.

#### Scenario: A user's config has the flat form from before the hint was rephrased
- **WHEN** a user's `config.yaml` contains a top-level
  `tts.backend: openvox` key (written before `a7eabb6`, when the doctor's
  own hint suggested exactly this flat form)
- **THEN** `load_raw_config()` expands the flat key into
  `tts: {backend: openvox}`, `_tts_config()` returns that nested mapping,
  and `check_voice_readiness()` correctly probes `openvox_api`
  reachability instead of silently falling back to the `"kokoro"` default

#### Scenario: Both the dotted and nested forms are present for the same key
- **WHEN** a config contains both `tts: {backend: kokoro}` and a
  top-level `tts.backend: openvox` key
- **THEN** the explicit nested value (`kokoro`) wins; the dotted key is
  dropped rather than overwriting it

### Requirement: No PWA service worker exists for offline TTS caching
The system SHALL NOT ship a service worker (`sw.js`) for the web app.
A prior `sw.js` was removed (`03cd5bd`, 2026-07-12) after being identified
as permanently broken (a top-level `return;` SyntaxError) and never
registered by any code path; model/voice caching for offline use is
handled entirely by ONNX Runtime Web (IndexedDB) and `transformers.js`
(Cache Storage), neither of which requires a service worker.

#### Scenario: Someone attempts to reintroduce sw.js
- **WHEN** a future change adds a service worker file back to
  `web/static/`
- **THEN** it must implement real cache-versioning and a
  `navigator.serviceWorker.register()` call path (currently absent
  everywhere in the JS) — reintroducing the file without both is
  regressing to the documented dead-code state
