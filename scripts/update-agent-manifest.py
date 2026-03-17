#!/usr/bin/env python3
"""Generate agents/manifest.json from current agent definition files."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "agents"

TRACKED_FILES: dict[str, list[str]] = {
    "claude": [
        "claude/socratic-mentor.md",
        "claude/study-generate.md",
        "claude/study-setup.md",
        "claude/study-audio.md",
    ],
    "kiro": ["kiro/study-mentor.json"],
    "gemini": ["gemini/study-mentor.md"],
    "opencode": ["opencode/study-mentor.md"],
}

SHARED_FILES = [
    "shared/audhd-framework.md",
    "shared/socratic-engine.md",
    "shared/knowledge-bridging.md",
    "shared/session-protocol.md",
    "shared/teach-back-protocol.md",
    "shared/network-bridges.md",
    "shared/break-science.md",
    "shared/wind-down-protocol.md",
]


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def main() -> None:
    today = date.today().isoformat()
    agents: dict[str, dict[str, str]] = {}

    all_files = []
    for files in TRACKED_FILES.values():
        all_files.extend(files)
    all_files.extend(SHARED_FILES)

    for rel_path in sorted(set(all_files)):
        full_path = AGENTS_DIR / rel_path
        if full_path.exists():
            agents[rel_path] = {"hash": hash_file(full_path), "updated": today}

    manifest = {"version": 1, "agents": agents}
    manifest_path = AGENTS_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Updated {manifest_path} with {len(agents)} entries")


if __name__ == "__main__":
    main()
