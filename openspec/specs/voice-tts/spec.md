## Purpose

Provide text-to-speech for study review and recap narration across two
distinct surfaces: the web app, where speech is synthesised on the StudyLoop
host by an OpenAI-compatible Kokoro server and the browser only plays the
audio it is handed; and the terminal/CLI/MCP path, where `tts.backend`
selects an in-process `kokoro-onnx` by default or a Kokoro server as an
explicit opt-in. There is deliberately no in-browser synthesis for the web
path.

## Requirements

### Requirement: Web-path speech is synthesised on the host, never in the browser
The FastAPI server SHALL expose same-origin routes `/api/tts/health`,
`/api/tts/warm` and `/api/tts/speak` that proxy to the OpenAI-compatible
speech server at `tts.openvox_base_url` and return playable audio. They
SHALL read only the `openvox_*` keys of the `tts:` block, never
`tts.backend`. `tts-engine.js` SHALL contain no synthesis tier; its ladder
is `server-openvox → web-speech → silent`. `/api/tts/speak` SHALL answer
503, not 500, when the speech server is unreachable or busy.

#### Scenario: Choosing which server speaks for the web app
- **WHEN** `tts.openvox_base_url` names OpenVox (`127.0.0.1:8000/v1`),
  VoiceMode's Kokoro, or the Kokoro-FastAPI container in `docker/kokoro/`
  (`:8880`), optionally overridden by `STUDYLOOP_TTS_BASE_URL`
- **THEN** that server synthesises every web utterance, using
  `openvox_model`, `openvox_voice`, `openvox_response_format` and
  `openvox_timeout` (`learning/voice.py::_openvox_settings`); setting
  `tts.backend` changes nothing on this path

#### Scenario: The app is served with `--lan` Basic auth
- **WHEN** a device on the LAN has authenticated to the page
- **THEN** the browser replays the same credentials to the same-origin
  `/api/tts/*` routes (`web/auth.py` answers 401 without them), and
  responses are `Cache-Control: no-store`. StudyLoop never needs the
  speech server's own port reachable from the device: OpenVox and the
  container bind `127.0.0.1`, and VoiceMode's native Kokoro — which binds
  `0.0.0.0` and is the one unauthenticated route onto the LAN, a trade-off
  stated in `docker/kokoro/docker-compose.yml` — can be firewalled at no
  cost to web voice

#### Scenario: Reviewing a flashcard with voice enabled and the speech server reachable
- **WHEN** a user presses the speaker button / `T` key on a review card
- **THEN** the browser POSTs the text to `/api/tts/speak`
  (`web/routes/tts.py`), the host synthesises it, and the page plays the
  returned audio through an `<audio>` element; no model is downloaded to
  the device and no `AudioContext`, WebGPU or secure context is required

#### Scenario: No speech server is configured or reachable
- **WHEN** `/api/tts/health` reports `available: false`, or
  `/api/tts/speak` answers 503
- **THEN** the engine adopts the `web-speech` tier (the device's own
  system voices), or `silent` when the device has none, and the engine
  badge names the tier actually speaking rather than staying quiet

#### Scenario: The page is served over `studyloop web --lan`
- **WHEN** the app is opened from a tablet over plain HTTP, which is not a
  secure context, so the browser withholds `navigator.gpu` and Cache
  Storage
- **THEN** the server tier still speaks, because synthesis happens on the
  host and the device only plays a same-origin audio response

#### Scenario: A non-English voice id is requested
- **WHEN** `/api/tts/speak` is asked for a voice outside the English set
  that `/api/tts/health` offers (for example `zf_xiaobei`)
- **THEN** the request is refused with 503 naming the voice and nothing is
  spoken — to the same Kokoro model it is a valid request that would read
  the card in that language, not an error anyone would notice

#### Scenario: The engine badge names the tier, not a product
- **WHEN** voice is on and the server tier is speaking
- **THEN** the badge reads `Kokoro (server)` for tier id `server-openvox`
  (`components.js`; `System voices` and `No audio` for the other two),
  because the same URL slot serves OpenVox, VoiceMode and the container —
  showing the raw id once reported "OpenVox is down but it still says
  server-openvox" to a learner who was not running OpenVox

### Requirement: Terminal/CLI/MCP voice defaults to local kokoro-onnx
`study-speak` and the CLI's `--speak`/`--audio-file` paths SHALL default
`tts.backend` to `kokoro` (local `kokoro-onnx`, measured ~1.5s
time-to-first-audio), keeping `openvox` as an explicit opt-in
(`tts.backend: openvox`) rather than an automatic preference — measured
OpenVox warm latency (2.9–3.8s) is too slow for the live-narration default
path, though acceptable for recap/teaching-moment narration when
explicitly configured. `tts.backend` SHALL govern these surfaces only.

#### Scenario: tts.backend is set and the web app is used
- **WHEN** `tts.backend` is `kokoro`, `qwen3` or `macos` and a learner
  turns voice on in `studyloop web`
- **THEN** the web app still speaks through the server at
  `tts.openvox_base_url` — it always behaves like `openvox` and shares only
  the `openvox_*` keys, so one configured Kokoro server serves both
  surfaces whatever `backend` says

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
registered by any code path. Since the in-browser synthesis tier was
removed there is nothing to cache on the device: the browser downloads no
model, and `/api/tts/speak` responses are `Cache-Control: no-store` because
a cached utterance would pin a voice the learner has since changed.

#### Scenario: Someone attempts to reintroduce sw.js
- **WHEN** a future change adds a service worker file back to
  `web/static/`
- **THEN** it must implement real cache-versioning and a
  `navigator.serviceWorker.register()` call path (currently absent
  everywhere in the JS) — reintroducing the file without both is
  regressing to the documented dead-code state
