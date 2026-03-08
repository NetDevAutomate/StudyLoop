# Voice Output

`study-speak` is a TTS CLI tool that speaks agent responses aloud using kokoro-onnx — an 82M parameter model with the `am_michael` voice. Designed for AuDHD learners who benefit from auditory reinforcement alongside visual text.

---

## Quick Start

### Install

```bash
uv tool install "./packages/agent-session-tools[tts]" --force
```

### Download Models

Models download automatically on first run. To pre-download:

```bash
mkdir -p ~/.cache/kokoro-onnx && \
  wget -q https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx \
    -O ~/.cache/kokoro-onnx/kokoro-v1.0.onnx && \
  wget -q https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin \
    -O ~/.cache/kokoro-onnx/voices-v1.0.bin
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

When enabled, the agent speaks its full response — **excluding code blocks**.

---

## Configuration

`~/.config/studyctl/config.yaml`:

```yaml
tts:
  backend: kokoro        # kokoro | qwen3 | macos
  voice: am_michael      # kokoro voices: am_michael, af_heart, bf_emma, etc.
  speed: 1.0             # 0.5 = slow, 1.0 = normal, 1.5 = fast, 2.0 = very fast
  macos_voice: Samantha  # fallback voice for macOS say
```

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
