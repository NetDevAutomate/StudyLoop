# Voice Output

StudyLoop has two complementary neural-TTS paths for AuDHD learners who benefit from auditory reinforcement alongside visual text:

- **`study-speak` CLI** (this page, below) — speaks agent responses aloud during terminal sessions via OpenVox, `kokoro-onnx`, Qwen3/ltts, or macOS `say`.
- **Web PWA in-browser TTS** ([jump to section](#web-pwa-voice-in-browser-neural-tts)) — synthesises speech entirely in the browser via WebGPU/WASM, no remote API. Same model, runs on-device.

`study-speak` is a TTS CLI tool that speaks agent responses aloud. Kokoro remains the safest default because it is controlled directly by StudyLoop; OpenVox is an optional terminal/agent backend when you already have its local API enabled.

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

Optional OpenVox profile:

```yaml
tts:
  backend: openvox
  openvox_base_url: http://127.0.0.1:8000/v1
  openvox_model: kokoro
  openvox_voice: af_bella
  openvox_language: en
  openvox_response_format: wav
  openvox_timeout: 30

  # Existing fallback settings still apply.
  voice: am_michael      # kokoro voices: am_michael, af_heart, bf_emma, etc.
  speed: 1.0             # 0.5 = slow, 1.0 = normal, 1.5 = fast, 2.0 = very fast
  macos_voice: Samantha  # fallback voice for macOS say
```

### OpenVox Local API Backend

[OpenVox](https://openvoxai.com/) runs a local macOS API server with low-latency voices. This is best treated as an optional backend for terminal/MCP sessions, not as the primary Web PWA voice engine. StudyLoop calls the documented local endpoint at `http://127.0.0.1:8000/v1/audio/speech`, saves the returned WAV to a temporary file, plays it with `afplay`, and then removes the temporary file.

Smoke test:

```bash
study-speak "Explain this back in your own words." -b openvox
studyloop recap today --audio-file recap.wav
```

`studyloop recap today --audio-file` saves the same compact daily recap that
`--speak` reads aloud. It prefers OpenVox when `tts.backend: openvox` is
configured, and falls back to macOS `say` when OpenVox is unavailable.

Manual API check:

```bash
curl -X POST "http://127.0.0.1:8000/v1/audio/speech" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kokoro",
    "input": "StudyLoop is speaking through OpenVox.",
    "language": "en",
    "voice": "af_bella",
    "response_format": "wav"
  }' \
  --output openvox-test.wav
afplay openvox-test.wav
```

If OpenVox is closed, busy, unreachable, or its Local API toggle is off, `study-speak` continues through the existing fallback chain instead of blocking the study session.

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

## Web PWA Voice (in-browser neural TTS)

The study web app (`studyloop web`) synthesises speech **entirely in the browser** with a neural model — the same Kokoro-82M voice quality as the `study-speak` CLI, running locally via WebGPU/WASM. **No text is ever sent to a remote API.** This replaces the old Web Speech API path, which depended on the OS's built-in voices (poor quality on macOS without manual voice downloads).

### How it works

`tts-engine.js` loads [Kokoro-82M](https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX) via [transformers.js](https://github.com/huggingface/transformers.js) and runs inference on-device. It auto-selects the best available tier:

| Tier | Engine | When |
|---|---|---|
| **`neural-webgpu`** | Kokoro on WebGPU | Browser exposes `navigator.gpu` (Chrome/Edge, recent Safari) |
| **`neural-wasm`** | Kokoro on single-thread WASM | No WebGPU, but device is fast enough (passes a warm-up speed probe) |
| **`web-speech`** | Web Speech API (OS voices) | Neural unavailable or device too slow — graceful fallback |

There is **no COOP/COEP requirement** — the engine forces single-thread WASM (`numThreads=1`) and prefers WebGPU, so it never needs `SharedArrayBuffer`. That keeps the page's cross-origin isolation headers off, which matters because isolating the origin would break the same-origin embeds and WebSocket the session dashboard relies on.

### First-run download

On first use the model downloads **once** (~92 MB: the q8-quantised Kokoro weights + tokenizer + voice embeddings) from Hugging Face, with a progress indicator in the header. The compiled model is cached in the browser's **IndexedDB** (by ONNX Runtime Web) and the voice embeddings in **Cache Storage** (`kokoro-voices`), and reused on every subsequent load — **subsequent loads are offline and fast** (init drops from ~30 s to ~4 s). This caching is managed by the TTS libraries directly and needs no service worker.

> **First run needs internet** to fetch the weights. After that, voice works fully offline.

### Future: fully-offline (cold-start) voice

The current design needs internet **once** (the first-run fetch). Making voice work with *zero* internet from a cold install is possible but deliberately **not** done yet — and notably, it **cannot** be solved by the install script.

**Why the install script can't help:** the model is downloaded *by the browser* into the browser's per-origin **Cache Storage**. `scripts/install.sh` runs in the shell, server-side — it has no path to write into a browser's Cache Storage (unlike the `study-speak` CLI, which reads weights from `~/.cache/kokoro-onnx/` on the filesystem and *can* be pre-warmed by a shell `curl`). A shell download would land the bytes somewhere the web engine can't read.

**The only real cold-offline path is to self-host the weights:**

1. Vendor the ~92 MB Kokoro model under `web/static/` (tracked via Git LFS, like the ORT WASM already is).
2. Point `KOKORO_MODEL_ID` / the transformers.js model path at that same-origin location instead of the Hugging Face hub.
3. The browser then fetches the model from `localhost` on first load — no internet, ever. (It still populates Cache Storage once; that's a local fetch.)

**Why deferred:** it adds 92 MB to the repo/LFS for a one-time-internet saving that most LAN/desktop users don't need. A lighter middle-ground is a "warm voice cache" button in settings that calls `ttsEngine.init()` on demand, so the download happens deliberately (with progress) rather than on first card-read — still internet-once, but user-controlled.

### Controls

- **Voice selector dropdown** — choose a Kokoro voice (e.g. `am_michael`, `af_heart`, `bf_emma`). Appears in the header; selection persists across sessions. (Falls back to listing OS voices if the engine is on the `web-speech` tier.)
- **Read once** — tap the speaker icon on a card, or press `T`. Reads the current content once. This works whether or not the header voice toggle is on.
- **Voice toggle** — the header speaker button. It enables the app's own spoken announcements (Pomodoro transitions and confirmations such as "voice enabled") and reveals the voice selector and engine badge. Persists to `localStorage` under `voice`. **Click-only — no key is bound to it, and it does not read cards to you automatically.**
- **Stop** — a stop button appears in the header while audio is playing; click it (or it clears automatically when playback ends) to interrupt mid-utterance. The stop control halts neural WebGPU/WASM playback, not just Web Speech API output.

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
| `openvox` | Depends on selected OpenVox model | Low | Optional local macOS API backend for terminal/MCP voice when the OpenVox Local API is enabled. Falls back gracefully if unavailable. |
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

**OpenVox does not speak**
:   Start the OpenVox app/local API server, then run `studyloop doctor --category voice` and `study-speak "test" -b openvox`. If OpenVox returns `429`, it is already generating or preloading a model; wait a moment and retry. StudyLoop will fall back automatically for normal agent sessions.

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
