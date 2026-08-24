# Voice Output

StudyLoop has two neural-TTS surfaces for AuDHD learners who benefit from auditory reinforcement alongside visual text:

- **`study-speak` CLI** (this page, below) — speaks agent responses aloud during terminal sessions via `kokoro-onnx` on the local filesystem, a Kokoro server, Qwen3/ltts, or macOS `say`.
- **Web app voice** ([jump to section](#web-app-voice-server-side-kokoro)) — the browser posts text to StudyLoop's own server, which proxies it to a Kokoro server you run. The device only plays the audio it gets back.

Both surfaces read the same `tts:` block in `~/.config/studyloop/config.yaml`. `tts.backend` is **not** CLI-only: the web app's server-side path uses the same `openvox_*` connection settings.

Voice is **off by default** on both surfaces. You turn it on deliberately — a toggle in the web header, a command in an agent session.

---

## Quick Start

### Install

```bash
uv tool install "./packages/agent-session-tools[tts]" --force
```

### Download Models

Models download automatically on first run. If you want to pre-download them, fetch the files manually:

To download manually:

```bash
mkdir -p ~/.cache/kokoro-onnx && \
  curl -fsSL https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx \
    -o ~/.cache/kokoro-onnx/kokoro-v1.0.onnx && \
  curl -fsSL https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin \
    -o ~/.cache/kokoro-onnx/voices-v1.0.bin
```

### Test

```bash
study-speak "Hello, can you hear me?"
```

---

## Agent Integration

Voice is **off by default**. Toggle it during a session:

=== "Kiro CLI"

    ```
    @speak-start    # enable voice
    @speak-stop     # disable voice
    ```

    Kiro uses a native MCP tool for speech.

=== "Claude Code"

    ```
    /speak-start    # enable voice
    /speak-stop     # disable voice
    ```

    Uses shell command `~/.local/bin/study-speak`.

=== "Gemini / OpenCode / Amp"

    ```
    @speak-start    # enable voice
    @speak-stop     # disable voice
    ```

    Uses shell command `~/.local/bin/study-speak`.

When enabled, the agent speaks core questions, answers, key principles, and teaching moments — **excluding code blocks, scaffolding, and long explanations**.

---

## Configuration

`~/.config/studyloop/config.yaml`:

```yaml
tts:
  backend: kokoro        # kokoro | openvox | qwen3 | macos
  voice: am_michael      # kokoro voices: am_michael, af_heart, bf_emma, etc.
  speed: 1.0             # 0.5 = slow, 1.0 = normal, 1.5 = fast, 2.0 = very fast
  macos_voice: Samantha  # fallback voice for macOS say
```

Kokoro server profile — used by the CLI **and** by the web app:

```yaml
tts:
  backend: openvox
  openvox_base_url: http://127.0.0.1:8000/v1   # or :8880/v1 for VoiceMode / the container
  openvox_fallback_base_urls:                   # tried in order if the primary fails
    - http://127.0.0.1:8880/v1                  # VoiceMode default; [] disables fallback
  openvox_model: kokoro
  openvox_voice: bf_emma
  openvox_language: en
  openvox_response_format: wav
  openvox_timeout: 30

  # Existing fallback settings still apply.
  voice: am_michael      # kokoro voices: am_michael, af_heart, bf_emma, etc.
  speed: 1.0             # 0.5 = slow, 1.0 = normal, 1.5 = fast, 2.0 = very fast
  macos_voice: Samantha  # fallback voice for macOS say
```

!!! note "The keys are named `openvox_*` for historical reasons only"
    They accept **any** OpenAI-compatible Kokoro endpoint — OpenVox was simply
    the first one wired up. Nothing about the name restricts you to that
    product, and no code path is specific to it. Only the URL changes between
    servers.

### Overriding the server for a single command

`STUDYLOOP_TTS_BASE_URL`, `STUDYLOOP_TTS_FALLBACK_BASE_URLS`,
`STUDYLOOP_TTS_VOICE` and `STUDYLOOP_TTS_MODEL` override
the config file without editing it — the quickest way to compare two servers back
to back:

```bash
STUDYLOOP_TTS_BASE_URL=http://127.0.0.1:8880/v1 \
  STUDYLOOP_TTS_VOICE=bf_lily studyloop recap today --speak
```

They override the config **file** only. Code that names its own endpoint is never
silently repointed by a stray variable. The `STUDYLOOP_` prefix is deliberate:
VoiceMode namespaces its equivalents as `VOICEMODE_TTS_BASE_URLS` and friends, and
two voice tools sharing an unprefixed `TTS_BASE_URL` would fight over the same
shell.

### Kokoro Server Backends

StudyLoop does not depend on a particular provider. It POSTs to the configured
primary and then each fallback URL, so anything exposing an OpenAI-compatible
`/v1/audio/speech` will do. Three are known to work with a byte-identical request
and the same voice ids:

| Server | Port | Warm latency per sentence | Notes |
|---|---|---|---|
| **[VoiceMode](https://github.com/mbailey/voicemode)** | 8880 | 0.37–1.8 s | `voicemode service install kokoro`. Native, no Docker. On Apple Silicon its `mlx-audio` service (:8890) bundles an MPS-accelerated Kokoro alongside Whisper. **Binds to your LAN — see the trade-off below.** |
| **[OpenVox](https://openvoxai.com/)** | 8000 | 2.4–2.5 s | A macOS app. Binds `127.0.0.1` only. |
| **Container** | 8880 | not measured | `docker/kokoro/docker-compose.yml` in this repo, pinned to `127.0.0.1`. Correct for amd64 but **untested** there; the arm64 image is broken upstream (ships a CUDA PyTorch, fails with `libcublasLt.so not found`, crash-loops). On Apple Silicon use a native server. |

On macOS prefer a native server — no Docker, no image to track. On Linux and
Windows the container is the intended route.

!!! warning "VoiceMode's Kokoro is reachable from your whole network"
    Measured, not inferred: it runs uvicorn with `--host 0.0.0.0`, and a separate
    tablet on the same network fetched `http://<host>:8880/v1/models`
    successfully **with no credentials**. It is not configurable — VoiceMode
    exposes port, models dir, cache dir, default voice and max-requests settings,
    but no host setting, and the address is hardcoded in a git-tracked start
    script that the next install or pull reverts.

    **The trade-off, stated plainly, because it is a real choice and not a defect
    to route around.** Kokoro is CPU-intensive, so an open TTS port lets anything
    on the network spend your host's CPU, and it is the one component here with no
    authentication. Against that, it is the only route that gives a tablet a good
    voice at all — the alternative on such a device is the system voices, or
    silence. On a home network that is usually a fine trade; on a shared, office
    or public network it is not.

    StudyLoop itself never needs the port reachable: tablets get speech through
    StudyLoop's own password-protected `/api/tts/speak`, so firewalling 8880 costs
    you nothing. OpenVox and the container both bind loopback and raise none of
    this.

Smoke test:

```bash
study-speak "Explain this back in your own words." -b openvox
studyloop recap today --audio-file recap.wav
```

`studyloop recap today --audio-file` saves the same compact daily recap that
`--speak` reads aloud. It prefers the configured server when `tts.backend:
openvox` is set, and falls back to macOS `say` when the server is unavailable.

Manual API check — the same request works against any of the three servers, with
only the port changed:

```bash
curl -X POST "http://127.0.0.1:8000/v1/audio/speech" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kokoro",
    "input": "StudyLoop is speaking through a Kokoro server.",
    "language": "en",
    "voice": "bf_emma",
    "response_format": "wav"
  }' \
  --output kokoro-test.wav
afplay kokoro-test.wav
```

If the server is closed, busy or unreachable, `study-speak` continues through the existing fallback chain instead of blocking the study session.

### Available Kokoro Voices

| Voice | Description |
|-------|-------------|
| `am_michael` | American male (default) |
| `af_heart` | American female |
| `bf_emma` | British female |

Pass any kokoro voice name with `-v` or set in config. See [kokoro-onnx voices](https://github.com/thewh1teagle/kokoro-onnx#voices) for the full list.

---

## MCP Server Setup

The study-speak MCP server lets AI agents call the TTS tool directly. The standalone server lives at `agents/mcp/study-speak-server.py`.

### Kiro CLI

Configured automatically via `agents/kiro/study-mentor.json`. No manual setup needed — the install script handles it.

### Claude Code / Gemini / OpenCode / Amp

Each agent has an `mcp.json` in its `agents/` directory. The server command uses `uvx` to run the standalone MCP server:

```json
{
  "mcpServers": {
    "speaker": {
      "command": "uvx",
      "args": ["--from", "mcp[cli]", "mcp", "run", "/absolute/path/to/agents/mcp/study-speak-server.py"]
    }
  }
}
```

Replace the path with your actual clone location. The `scripts/install-agents.sh` script sets this up automatically for detected AI tools.

---

## Web App Voice (server-side Kokoro)

The study web app (`studyloop web`) speaks through a **server-side** Kokoro. The browser POSTs the text to StudyLoop's own authenticated route `/api/tts/speak`, which first tries `tts.openvox_base_url`, then each `tts.openvox_fallback_base_urls` entry, and returns the first successful audio. VoiceMode on `127.0.0.1:8880/v1` is the default fallback. If every server fails, the browser visibly degrades to its operating-system voice. The device only has to play a response, which is why this works on a tablet where in-browser synthesis could not.

Set it up in the [Kokoro Server Backends](#kokoro-server-backends) section above — the web app needs no separate configuration.

### The fallback ladder

Three tiers, in order. This is **not** a chain of servers: StudyLoop points at **one** server URL, and the ladder is what happens when that one is absent or unreachable.

| Tier | Engine | When |
|---|---|---|
| **`server-openvox`** | Kokoro on the server you configured | A reachable `openvox_base_url`. The best tier, not a degraded one. |
| **`web-speech`** | Web Speech API — your operating system's own voices | No server configured, or it cannot be reached |
| **`silent`** | Nothing speaks | No server and no OS speech support |

The middle rung matters: with no Kokoro server at all, the app still talks, using voices the device already has. They need no install and work everywhere, they are simply not as good.

### Why synthesis is not in the browser

An earlier tier ran Kokoro-82M in the page itself, via transformers.js on WebGPU or WASM. It has been removed, along with the vendored ONNX Runtime, the phonemiser and ~27 MB of model runtime. The reasons, in order of how badly each hurt:

- **It could not run at all over `studyloop web --lan`.** That serves plain HTTP, which is not a secure context, so the browser hides both `navigator.gpu` and Cache Storage. The tablets voice was mostly *for* were exactly the devices it could not reach.
- **6.6x real time on a warmed WebGPU tier** — slower than reading the card.
- **It self-downgraded to a silent tier** rather than failing visibly.
- **It occasionally spoke Mandarin**, for reasons never established.

A server has none of those limits. The design notes for the removed tier are kept at `docs/archive/browser-neural-tts-design.md`.

### English voices only, deliberately

StudyLoop filters the server's voice list to English. One real server offered 67 voices; the picker showed 41.

This is not tidiness. The same Kokoro model speaks Mandarin, Japanese, Spanish, French, Hindi, Italian and Portuguese, and a stray voice id is **a valid request that speaks that language** rather than an error you would notice. Filtering is what stops a mistyped voice reading your flashcards in Mandarin.

The default voice is `bf_emma`, British female.

### Verified devices

An iPad (both Brave and Chrome) and an Android tablet all speak through the server tier over the LAN.

### Controls

- **Voice selector dropdown** — choose a voice offered by your Kokoro server (e.g. `bf_emma`, `am_michael`, `af_heart`). Appears in the header; selection persists across sessions. On the `web-speech` tier it lists the OS voices instead.
- **Read once** — tap the speaker icon on a card, or press `T`. Reads the current content once. This works whether or not the header voice toggle is on.
- **Voice toggle** — the header speaker button. It enables the app's own spoken announcements (Pomodoro transitions and confirmations such as "voice enabled") and reveals the voice selector and engine badge. Persists to `localStorage` under `voice`. **Click-only — no key is bound to it, and it does not read cards to you automatically.**
- **Engine badge** — names the tier actually speaking (`server-openvox`, `web-speech`, `silent`), shown whenever voice is on rather than only on failure. A badge that appears only when something breaks teaches nobody what working looks like.
- **Stop** — a stop button appears in the header while audio is playing; click it (or it clears automatically when playback ends) to interrupt mid-utterance. It halts server-audio playback, not just Web Speech API output.

!!! warning "There is no auto-voice, and `V` is unbound"
    This page previously described pressing `V` to "read everything automatically as you navigate". No such feature exists in the web app — there is no auto-read mode, and `V` is not bound to anything. Reading is always one deliberate action: `T`, or the speaker icon.

---

## CLI Reference

```bash
study-speak "text"                                        # Speak text
study-speak -                                              # Read from stdin
study-speak "text" -v af_heart                            # Different voice
study-speak "text" -s 1.2                                 # Faster speed
study-speak "text" -b openvox -v af_bella                 # Use OpenVox local API
study-speak "text" -b macos                               # Force macOS fallback
study-speak "text" -b qwen3 --instruct "speak warmly"    # Qwen3 with emotion
```

---

## Backends

| Backend | Model Size | Latency | Notes |
|---------|-----------|---------|-------|
| `kokoro` (default) | 82M params | ~1.5s | ONNX runtime on CPU. Best balance of quality, speed, and StudyLoop-controlled reliability. |
| `openvox` | Depends on the server's model | 0.37–2.5s warm, by server | A Kokoro server over HTTP — OpenVox, VoiceMode, or the container. Also the engine behind web-app voice. Falls back gracefully if unreachable. |
| `qwen3` (via ltts) | 1.7B params | 30–60s | Highest quality. Emotional control via `--instruct`. Apple Silicon MPS. Only use when quality matters more than speed. |
| `macos` (say) | Built-in | Instant | Low quality. Last resort fallback. |

!!! tip "When to use qwen3"
    The 30–60s latency on Apple Silicon makes qwen3 impractical for live sessions. Use it for generating audio files or when you want emotional expression and don't mind waiting.

---

## Troubleshooting

**Crackling audio**
:   Automatic 24kHz→48kHz resampling should fix this. If it persists, check your audio output device settings.

**No sound**
:   Check for errors: `study-speak "test" 2>&1`. Verify models exist in `~/.cache/kokoro-onnx/`.

**The Kokoro server does not speak**
:   Start the server, then run `studyloop doctor --category voice` and `study-speak "test" -b openvox`. Check `/v1/models` answers on the port you configured — every OpenAI-compatible Kokoro server implements it, whereas the voice-listing path differs between implementations. If OpenVox returns `429`, it is already generating or preloading a model; wait a moment and retry. StudyLoop falls back automatically for normal agent sessions.

**The web app uses the OS voices instead of Kokoro**
:   The engine badge reads `web-speech`, which means `/api/tts/speak` could not reach your server. Check `openvox_base_url` and that the server is running. Nothing is broken — you are on the middle rung of the ladder.

**AirPlay latency**
:   Short clips (<2s) may not play through AirPlay due to buffer timing. Use longer text or switch to local speakers.

---

## Why Voice Matters for AuDHD Learners

!!! energy-check "Dual coding = better retention"
    Hearing information while reading it activates two processing channels simultaneously. For AuDHD brains, this redundancy helps compensate for attention drift.

- **Auditory reinforcement** — dual coding (visual + auditory) improves retention
- **Processing support** — hearing questions spoken aloud helps with comprehension and focus
- **Reduces overwhelm** — breaks up the "wall of text" experience
- **Maintains engagement** — natural voice (not robotic) avoids sensory irritation
