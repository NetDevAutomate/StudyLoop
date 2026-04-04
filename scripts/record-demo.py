#!/usr/bin/env python3
"""Record a Playwright demo of the studyctl study session dashboard.

Starts a study session with --lan --web, opens the dashboard in a
headless recorded browser, interacts with the agent via the ttyd
terminal, and saves the video as mp4.

Handles the Claude Code trust prompt and waits for the agent to be
ready before typing questions.

Usage:
    uv run python scripts/record-demo.py

Output:
    demos/studyctl-session-demo.mp4
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
DEMO_DIR = PROJECT_DIR / "demos"
DEMO_DIR.mkdir(exist_ok=True)

WEB_PORT = 8567
TTYD_PORT = 7681

# Demo questions — concise, showcasing the Socratic method + AuDHD support
DEMO_QUESTIONS = [
    (
        "I want to learn about Python decorators. I know networking really"
        " well but I'm new to Python patterns — where should we start?"
    ),
    "Can you show me a simple decorator example? I learn best from concrete code.",
    "How does this relate to middleware in networking? That's something I know well.",
]

# How long to wait for each response (seconds)
RESPONSE_WAIT = [60, 60, 60]


def _studyctl(*args: str) -> subprocess.CompletedProcess | None:
    """Run studyctl, handling the expected timeout from tmux attach."""
    env = {**os.environ}
    env.pop("TMUX", None)
    try:
        return subprocess.run(
            [sys.executable, "-m", "studyctl.cli", *args],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
            cwd=str(PROJECT_DIR),
        )
    except subprocess.TimeoutExpired:
        # Expected — studyctl study calls os.execvp(tmux attach) which
        # hangs since we have no terminal. Session is already started.
        return None


def _wait_for_port(port: int, timeout: int = 20) -> bool:
    import urllib.request

    for _ in range(timeout * 2):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def _get_xterm_text(frame) -> str:
    """Extract visible text from xterm terminal."""
    try:
        # xterm.js renders text in .xterm-rows
        rows = frame.locator(".xterm-rows")
        return rows.inner_text(timeout=2000)
    except Exception:
        return ""


def main() -> None:
    from playwright.sync_api import sync_playwright

    # 1. Clean up
    print("[1/7] Cleaning up stale sessions...")
    _studyctl("study", "--end")
    time.sleep(2)

    # Kill any stale ttyd processes
    subprocess.run(["pkill", "-f", "ttyd"], capture_output=True, check=False)
    time.sleep(1)

    # 2. Start a fresh study session
    print("[2/7] Starting study session (Python Decorators, energy 8, --lan)...")
    _studyctl("study", "Python Decorators for Network Engineers", "--energy", "8", "--lan")

    # 3. Wait for services
    print(f"[3/7] Waiting for web server on :{WEB_PORT}...")
    if not _wait_for_port(WEB_PORT):
        print(f"  ERROR: Web server not ready on port {WEB_PORT}")
        return
    print("  Web server ready.")

    print(f"  Waiting for ttyd on :{TTYD_PORT}...")
    ttyd_ready = _wait_for_port(TTYD_PORT)
    if ttyd_ready:
        print("  ttyd ready.")
    else:
        print("  WARNING: ttyd not ready — will record dashboard only.")
        return

    time.sleep(3)

    # 4. Record with Playwright
    print("[4/7] Starting Playwright recording (headless)...")
    video_path = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            record_video_dir=str(DEMO_DIR),
            record_video_size={"width": 1280, "height": 900},
        )
        page = context.new_page()

        # --- Scene 1: Dashboard overview ---
        print("[5/7] Recording dashboard overview...")
        page.goto(f"http://127.0.0.1:{WEB_PORT}/session")
        page.wait_for_load_state("load")
        time.sleep(4)  # Alpine.js init

        # --- Scene 2: Handle Claude Code startup in ttyd ---
        terminal_panel = page.locator(".terminal-panel")
        if not terminal_panel.is_visible():
            print("  No terminal panel visible — aborting.")
            context.close()
            browser.close()
            return

        print("  Terminal panel visible.")
        frame = page.frame_locator(".terminal-iframe")
        xterm = frame.locator(".xterm")

        try:
            xterm.wait_for(timeout=15000)
            print("  xterm loaded.")

            # Wait for Claude Code to show the trust prompt or its prompt
            print("  Waiting for Claude Code to initialize (10s)...")
            time.sleep(10)

            # Check for trust prompt — accept it if present
            terminal_text = _get_xterm_text(frame)
            if "trust" in terminal_text.lower() or "Yes, I trust" in terminal_text:
                print("  Trust prompt detected — accepting...")
                xterm.click()
                time.sleep(0.3)
                # Press Enter to accept default (option 1: Yes, I trust)
                xterm.press("Enter")
                print("  Waiting for Claude to fully start (20s)...")
                time.sleep(20)
            else:
                print("  No trust prompt — Claude may already be ready.")
                time.sleep(5)

            # Verify Claude is ready by checking for its prompt indicator
            terminal_text = _get_xterm_text(frame)
            if ">" in terminal_text or "claude" in terminal_text.lower():
                print("  Claude prompt detected — ready for interaction!")
            else:
                print("  Terminal state unclear — proceeding anyway.")
                print(f"  Terminal text sample: {terminal_text[:200]!r}")

            # --- Scene 3: Ask questions ---
            print("[6/7] Interacting with agent...")
            for i, question in enumerate(DEMO_QUESTIONS):
                q_num = i + 1
                wait_time = RESPONSE_WAIT[i]
                print(f"  Q{q_num}/{len(DEMO_QUESTIONS)}: {question[:60]}...")

                # Focus and type with natural speed
                xterm.click()
                time.sleep(0.5)
                xterm.type(question, delay=25)
                time.sleep(0.3)
                xterm.press("Enter")

                print(f"    Waiting {wait_time}s for response...")
                time.sleep(wait_time)

                # Brief pause between questions
                if i < len(DEMO_QUESTIONS) - 1:
                    time.sleep(3)

            # --- Scene 4: Pop-out demo ---
            print("  Demonstrating pop-out feature...")
            popout_btn = page.locator(".terminal-controls .timer-btn").nth(1)
            if popout_btn.is_visible():
                try:
                    with context.expect_page() as new_page_info:
                        popout_btn.click()
                    new_page = new_page_info.value
                    new_page.wait_for_load_state("load")
                    time.sleep(3)

                    # Show placeholder on main page
                    page.bring_to_front()
                    time.sleep(2)

                    # Show the pop-out terminal
                    new_page.bring_to_front()
                    time.sleep(3)

                    # Back to main dashboard
                    page.bring_to_front()
                    new_page.close()
                    time.sleep(1)

                    # Re-expand inline terminal
                    collapse_btn = page.locator(".terminal-controls .timer-btn").first
                    if collapse_btn.is_visible():
                        collapse_btn.click()
                        time.sleep(2)
                except Exception as e:
                    print(f"  Pop-out demo error: {e}")

        except Exception as e:
            print(f"  Terminal interaction error: {e}")
            time.sleep(5)

        # --- Scene 5: Final dashboard view ---
        print("[7/7] Final dashboard shot...")
        page.bring_to_front()
        time.sleep(3)

        # Save
        video_path = page.video.path()
        context.close()
        browser.close()

    # 5. Process video
    if video_path and Path(video_path).exists():
        webm_path = DEMO_DIR / "studyctl-session-demo.webm"
        # Remove old output files (not the source we're about to rename)
        for old in DEMO_DIR.glob("studyctl-session-demo.*"):
            old.unlink(missing_ok=True)

        Path(video_path).rename(webm_path)
        size_mb = webm_path.stat().st_size / 1024 / 1024
        print(f"\nRecorded: {webm_path} ({size_mb:.1f} MB)")

        # Convert to mp4
        import shutil

        if shutil.which("ffmpeg"):
            mp4_path = DEMO_DIR / "studyctl-session-demo.mp4"
            print("Converting to mp4...")
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(webm_path),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "23",
                    "-pix_fmt",
                    "yuv420p",
                    str(mp4_path),
                ],
                capture_output=True,
            )
            if mp4_path.exists():
                mp4_mb = mp4_path.stat().st_size / 1024 / 1024
                print(f"MP4: {mp4_path} ({mp4_mb:.1f} MB)")
            else:
                print(f"ffmpeg error: {result.stderr.decode()[:300]}")
        else:
            print("ffmpeg not found — webm only")
    else:
        print("WARNING: No video file generated")

    # 6. End session
    print("\nEnding study session...")
    _studyctl("study", "--end")
    print("Done! Demo files in demos/")


if __name__ == "__main__":
    main()
