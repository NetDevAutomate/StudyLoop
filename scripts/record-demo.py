#!/usr/bin/env python3
"""Capture README media from the real StudyLoop Web UI and Kiro CLI.

The capture runs the production StudyLoop server with fresh, isolated config,
database, plans, notes, and session directories. It does not import the test
harness, seed fixture data, use a fake agent, or mock an API response.

It does use the current Kiro login, installed StudyLoop mentor, and model, so
recording can consume provider credits. The Kiro adapter restores any existing
mentor definition when the session ends.

Usage:
    uv run python scripts/record-demo.py --topic "..." --answer "..."

Output:
    docs/images/studyloop-study-session.png
    docs/images/studyloop-body-double.png
    docs/images/studyloop-kiro-demo.gif
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import suppress
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "images"

_TERMINAL_TEXT_JS = """
(selector) => {
  const el = document.querySelector(selector);
  if (!el || !window.Alpine) return '';
  const data = window.Alpine.$data(el);
  const term = data && data._term;
  if (!term || !term.buffer) return '';
  const buffer = term.buffer.active;
  const lines = [];
  for (let index = 0; index < buffer.length; index += 1) {
    const line = buffer.getLine(index);
    if (line) lines.push(line.translateToString(true));
  }
  return lines.join('\\n');
}
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_capture_config(config_path: Path, root: Path) -> None:
    """Write a fresh production config containing paths, not fixture data."""
    notes = root / "notes"
    materials = root / "study-materials"
    notes.mkdir(parents=True, exist_ok=True)
    materials.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        f"""notes_path: {json.dumps(str(notes))}
session_db: {json.dumps(str(root / "sessions.db"))}
state_dir: {json.dumps(str(root / "state"))}
content:
  base_path: {json.dumps(str(materials))}
  study_paths:
    - {json.dumps(str(materials))}
agents:
  priority: [kiro]
""",
        encoding="utf-8",
    )


def _write_capture_agent_template(root: Path) -> Path:
    """Create a tool-free Kiro profile; the production adapter adds the persona."""
    template = root / "kiro-capture-agent.json"
    template.write_text(
        json.dumps(
            {
                "name": "study-mentor",
                "description": "StudyLoop public mentor demonstration.",
                "prompt": "",
                "tools": [],
                "allowedTools": [],
                "resources": [],
                "mcpServers": {},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return template


def _capture_environment(
    root: Path, config_path: Path, kiro_binary: Path, agent_template: Path
) -> dict[str, str]:
    """Return an isolated production environment while retaining Kiro auth."""
    capture_env = os.environ.copy()
    capture_env.update(
        {
            "PATH": os.pathsep.join(
                (str(Path(sys.executable).parent), str(kiro_binary.parent), os.defpath)
            ),
            "TMPDIR": str(root / "tmp"),
            "XDG_CONFIG_HOME": str(root / "xdg-config"),
            "XDG_STATE_HOME": str(root / "xdg-state"),
            "XDG_CACHE_HOME": str(root / "xdg-cache"),
            "STUDYLOOP_CONFIG": str(config_path),
            "STUDYLOOP_DB": str(root / "sessions.db"),
            "STUDYLOOP_STATE_DIR": str(root / "state"),
            "STUDYLOOP_SESSION_DIR": str(root / "session-ipc"),
            "STUDYLOOP_PLANS_DIR": str(root / "study-plans"),
            "STUDYLOOP_AGENT": "kiro",
            "STUDYLOOP_KIRO_AGENT_TEMPLATE": str(agent_template),
        }
    )
    capture_env.pop("STUDYLOOP_TEST_AGENT", None)
    capture_env.pop("STUDYLOOP_TEST_AGENT_CMD", None)
    for directory in (
        root / "tmp",
        root / "xdg-config",
        root / "xdg-state",
        root / "xdg-cache",
        root / "state",
        root / "session-ipc",
        root / "study-plans",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return capture_env


def _start_server(root: Path, port: int, capture_env: dict[str, str]) -> subprocess.Popen:
    """Start the production CLI and wait until its Web UI responds."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "studyloop.cli", "web", "--port", str(port)],
        cwd=root,
        env=capture_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return proc
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                return proc
        except OSError:
            pass
        time.sleep(0.25)
    proc.kill()
    proc.wait(timeout=5)
    raise RuntimeError(f"StudyLoop Web UI did not start on port {port}")


def _stop_server(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _end_active_session(base_url: str) -> None:
    """End any capture session so the Kiro adapter restores user state."""
    request = urllib.request.Request(f"{base_url}/api/session/end", method="POST")
    with suppress(urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        urllib.request.urlopen(request, timeout=5).close()


def _wait_for_terminal(page, selector: str, needle: str, timeout: int = 30_000) -> None:
    page.wait_for_function(
        "([selector, needle]) => {"
        " const el = document.querySelector(selector);"
        " if (!el || !window.Alpine) return false;"
        " const data = window.Alpine.$data(el);"
        " const term = data && data._term;"
        " if (!term || !term.buffer) return false;"
        " const buffer = term.buffer.active;"
        " const lines = [];"
        " for (let index = 0; index < buffer.length; index += 1) {"
        "   const line = buffer.getLine(index);"
        "   if (line) lines.push(line.translateToString(true));"
        " }"
        " return lines.join('\\n').includes(needle);"
        "}",
        arg=[selector, needle],
        timeout=timeout,
    )


def _wait_for_terminal_count(
    page, selector: str, needle: str, count: int, timeout: int = 120_000
) -> None:
    page.wait_for_function(
        "([selector, needle, count]) => {"
        " const el = document.querySelector(selector);"
        " if (!el || !window.Alpine) return false;"
        " const data = window.Alpine.$data(el);"
        " const term = data && data._term;"
        " if (!term || !term.buffer) return false;"
        " const buffer = term.buffer.active;"
        " const lines = [];"
        " for (let index = 0; index < buffer.length; index += 1) {"
        "   const line = buffer.getLine(index);"
        "   if (line) lines.push(line.translateToString(true));"
        " }"
        " return lines.join('\\n').split(needle).length - 1 >= count;"
        "}",
        arg=[selector, needle, count],
        timeout=timeout,
    )


def _select_kiro(page, selector: str) -> None:
    page.wait_for_function(
        "selector => {"
        " const select = document.querySelector(selector);"
        " return select && [...select.options].some(option => "
        "   option.value === 'kiro' && !option.disabled);"
        "}",
        arg=selector,
        timeout=30_000,
    )
    page.select_option(selector, value="kiro")


def _ask_kiro_to_start(page, terminal_selector: str, topic: str) -> None:
    _wait_for_terminal(page, terminal_selector, "ask a question or describe a task")
    terminal = page.locator(terminal_selector)
    terminal.click()
    page.keyboard.type(
        f"Energy 6/10, steady mood, setup ready. I want to study {topic}. "
        "Ask one short diagnostic question to discover what I understand.",
        delay=18,
    )
    page.keyboard.press("Enter")


def _capture_study_session(
    page, base_url: str, output_dir: Path, topic: str, learner_answer: str
) -> None:
    page.goto(f"{base_url}/#study-session")
    page.wait_for_function("() => !!window.Alpine", timeout=15_000)
    page.locator("#topic-input").fill(topic)
    _select_kiro(page, "#agent-select")
    page.locator(".start-session-btn").click()

    terminal_area = ".session-active-layout .session-terminal-area"
    page.wait_for_selector(f"{terminal_area} .xterm-mount", state="visible", timeout=30_000)
    terminal = page.locator(f"{terminal_area} .xterm-mount")
    _ask_kiro_to_start(page, f"{terminal_area} .xterm-mount", topic)
    _wait_for_terminal_count(page, terminal_area, "Credits:", 1)
    page.wait_for_timeout(900)

    terminal.click()
    page.keyboard.type(learner_answer, delay=28)
    page.keyboard.press("Enter")
    _wait_for_terminal_count(page, terminal_area, "Credits:", 2)
    page.wait_for_timeout(1_200)
    page.screenshot(path=str(output_dir / "studyloop-study-session.png"))

    page.locator(".status-btn.end-btn").click()
    page.get_by_test_id("study-end-confirm-yes").click()
    page.wait_for_selector(".study-start-picker", state="visible", timeout=15_000)


def _capture_body_double(page, base_url: str, output_dir: Path, topic: str) -> None:
    page.evaluate("() => window.Alpine.store('nav').go('body-double')")
    page.wait_for_selector(".body-double-view", state="visible", timeout=15_000)
    page.locator("#bd-activity-input").fill(topic)
    _select_kiro(page, "#bd-agent-select")
    page.get_by_role("button", name="Start Pomodoro").click()
    page.locator("#bd-start-session").click()

    terminal_area = ".bd-console-panel .session-terminal-area"
    page.wait_for_selector(f"{terminal_area} .xterm-mount", state="visible", timeout=30_000)
    _ask_kiro_to_start(page, f"{terminal_area} .xterm-mount", topic)
    _wait_for_terminal_count(page, terminal_area, "Credits:", 1)
    page.wait_for_timeout(1_500)
    page.screenshot(path=str(output_dir / "studyloop-body-double.png"))
    page.get_by_role("button", name="End body double session").click()


def _encode_video(source: Path, output_dir: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required to create the public Kiro GIF")

    mp4 = output_dir / "studyloop-kiro-demo.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "24",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(mp4),
        ],
        check=True,
        capture_output=True,
    )

    gif = output_dir / "studyloop-kiro-demo.gif"
    filters = (
        "fps=8,scale=960:-1:flags=lanczos,split[frames][palette_source];"
        "[palette_source]palettegen=max_colors=128[palette];"
        "[frames][palette]paletteuse=dither=bayer:bayer_scale=4"
    )
    subprocess.run(
        [ffmpeg, "-y", "-i", str(source), "-vf", filters, "-loop", "0", str(gif)],
        check=True,
        capture_output=True,
    )
    source.unlink(missing_ok=True)
    mp4.unlink(missing_ok=True)


def capture(output_dir: Path, topic: str, learner_answer: str) -> None:
    """Capture screenshots and video, then convert the video when possible."""
    from playwright.sync_api import sync_playwright

    output_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "studyloop-study-session.png",
        "studyloop-body-double.png",
        "studyloop-kiro-demo.webm",
        "studyloop-kiro-demo.mp4",
        "studyloop-kiro-demo.gif",
    ):
        (output_dir / name).unlink(missing_ok=True)

    with tempfile.TemporaryDirectory(prefix="studyloop-readme-") as tmp:
        root = Path(tmp)
        kiro_binary = shutil.which("kiro-cli")
        if kiro_binary is None:
            raise RuntimeError("kiro-cli is required to record the public demo")
        config_path = root / "config.yaml"
        _write_capture_config(config_path, root)
        agent_template = _write_capture_agent_template(root)
        capture_env = _capture_environment(root, config_path, Path(kiro_binary), agent_template)
        port = _free_port()
        server = _start_server(root, port, capture_env)
        base_url = f"http://127.0.0.1:{port}"
        kiro_target = Path.home() / ".kiro" / "agents" / "study-mentor.json"
        kiro_backup = kiro_target.with_suffix(kiro_target.suffix + ".studyloop-backup")

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                video_dir = root / "video"
                video_dir.mkdir()
                context = browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    record_video_dir=str(video_dir),
                    record_video_size={"width": 1440, "height": 900},
                )
                page = context.new_page()
                video = page.video
                try:
                    _capture_study_session(page, base_url, output_dir, topic, learner_answer)
                    _capture_body_double(page, base_url, output_dir, topic)
                    page.wait_for_timeout(750)
                finally:
                    context.close()
                    browser.close()

                if video is None:
                    raise RuntimeError("Playwright did not create a video")
                generated = Path(video.path())
                webm = output_dir / "studyloop-kiro-demo.webm"
                generated.replace(webm)
                _encode_video(webm, output_dir)
        finally:
            _end_active_session(base_url)
            with suppress(Exception):
                _stop_server(server)
            if kiro_backup.exists():
                os.replace(kiro_backup, kiro_target)

    print(f"README media written to {output_dir}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"artifact directory (default: {DEFAULT_OUTPUT.relative_to(PROJECT_ROOT)})",
    )
    parser.add_argument(
        "--topic",
        required=True,
        help="learner-chosen topic to type into the real StudyLoop session",
    )
    parser.add_argument(
        "--answer",
        required=True,
        help="learner-authored answer to the mentor's first live question",
    )
    args = parser.parse_args()
    output_dir = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    capture(output_dir.resolve(), args.topic.strip(), args.answer.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
