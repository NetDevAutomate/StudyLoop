# Voice Output

StudyLoop has two complementary neural-TTS paths, both built on Kokoro-82M for natural voice quality (designed for AuDHD learners who benefit from auditory reinforcement alongside visual text):

- **`study-speak` CLI** (this page, below) — speaks agent responses aloud during terminal sessions via `kokoro-onnx` (server-side, on CPU).
- **Web PWA in-browser TTS** ([jump to section](#web-pwa-voice-in-browser-neural-tts)) — synthesises speech entirely in the browser via WebGPU/WASM, no remote API. Same model, runs on-device.

`study-speak` is a TTS CLI tool that speaks agent responses aloud using kokoro-onnx — an 82M parameter model with the `am_michael` voice.

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
  backend: kokoro        # kokoro | qwen3 | macos
  voice: am_michael      # kokoro voices: am_michael, af_heart, bf_emma, etc.
  speed: 1.0             # 0.5 = slow, 1.0 = normal, 1.5 = fast, 2.0 = very fast
  macos_voice: Samantha  # fallback voice for macOS say
```

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

There is **no COOP/COEP requirement** — the engine forces single-thread WASM (`numThreads=1`) and prefers WebGPU, so it never needs `SharedArrayBuffer`. This keeps the same-origin ttyd terminal iframe working.

### First-run download

On first use the model downloads **once** (~92 MB: the q8-quantised Kokoro weights + tokenizer + voice embeddings) from Hugging Face, with a progress indicator in the header. It is then cached in the browser's **Cache Storage** (`transformers-cache`) and reused on every subsequent load — **subsequent loads are offline and fast** (init drops from ~30 s to ~4 s). The PWA service worker is specifically configured to spare this cache when it clears app-shell assets.

> **First run needs internet** to fetch the weights. After that, voice works fully offline.

### Controls

- **Voice selector dropdown** — choose a Kokoro voice (e.g. `am_michael`, `af_heart`, `bf_emma`). Appears in the header; selection persists across sessions. (Falls back to listing OS voices if the engine is on the `web-speech` tier.)
- **Read once** — tap the speaker icon on a card, or press `T`. Reads the current content once.
- **Auto-voice** — toggle the header speaker icon, or press `V`. Reads everything automatically as you navigate.
- **Stop** — a stop button appears in the header while audio is playing; click it (or it clears automatically when playback ends) to interrupt mid-utterance. The stop control halts neural WebGPU/WASM playback, not just Web Speech API output.

---

## CLI Reference

```bash
study-speak "text"                                        # Speak text
study-speak -                                              # Read from stdin
study-speak "text" -v af_heart                            # Different voice
study-speak "text" -s 1.2                                 # Faster speed
study-speak "text" -b macos                               # Force macOS fallback
study-speak "text" -b qwen3 --instruct "speak warmly"    # Qwen3 with emotion
```

---

## Backends

| Backend | Model Size | Latency | Notes |
|---------|-----------|---------|-------|
| `kokoro` (default) | 82M params | ~1.5s | ONNX runtime on CPU. Best balance of quality and speed. |
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
