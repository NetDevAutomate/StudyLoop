"""Entry point for ``python -m studyctl.tui`` and ``textual serve``."""

from __future__ import annotations

from pathlib import Path

import yaml

from studyctl.tui.app import StudyApp

config_path = Path.home() / ".config" / "studyctl" / "config.yaml"
study_dirs: list[str] = []
theme = ""
dyslexic = False

if config_path.exists():
    try:
        data = yaml.safe_load(config_path.read_text()) or {}
        study_dirs = data.get("review", {}).get("directories", [])
        tui_cfg = data.get("tui", {})
        theme = tui_cfg.get("theme", "")
        dyslexic = tui_cfg.get("dyslexic_friendly", False)
    except Exception:
        pass

app = StudyApp(
    study_dirs=study_dirs,
    theme_name=theme,
    dyslexic_friendly=dyslexic,
)

if __name__ == "__main__":
    app.run()
