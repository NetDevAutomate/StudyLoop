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
  with a repair hint to start OpenVox or switch back to `tts.backend:
  kokoro`

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
