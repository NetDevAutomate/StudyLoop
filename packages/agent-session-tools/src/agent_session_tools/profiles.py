"""Export profiles and templates for standardized context formats."""

from pathlib import Path
from typing import Any

import yaml

# Built-in export profiles
BUILTIN_PROFILES = {
    "quick-resume": {
        "name": "quick-resume",
        "description": "Compact context for quickly resuming a session",
        "max_tokens": 4000,
        "last_n": 12,
        "include_tools": False,
        "only_code": False,
    },
    "code-focused": {
        "name": "code-focused",
        "description": "Only messages with code blocks",
        "max_tokens": 8000,
        "last_n": None,
        "include_tools": False,
        "only_code": True,
    },
    "full-handoff": {
        "name": "full-handoff",
        "description": "Complete session context for team handoffs",
        "max_tokens": 12000,
        "last_n": None,
        "include_tools": True,
        "only_code": False,
    },
    "debug-context": {
        "name": "debug-context",
        "description": "Debugging-focused with timestamps and metadata",
        "max_tokens": 8000,
        "last_n": 30,
        "include_tools": True,
        "only_code": False,
    },
}


def get_profiles_dir() -> Path:
    """Return profiles directory, creating if needed."""
    profiles_dir = Path.home() / ".config" / "agent_session" / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    return profiles_dir


def list_profiles() -> list[dict[str, Any]]:
    """List all available profiles (built-in + custom)."""
    profiles = []

    # Add built-in profiles
    for name, profile in BUILTIN_PROFILES.items():
        profiles.append(
            {"name": name, "description": profile.get("description", ""), "origin": "builtin"}
        )

    # Add custom profiles
    for yaml_file in get_profiles_dir().glob("*.yaml"):
        name = yaml_file.stem
        if name not in BUILTIN_PROFILES:
            try:
                with open(yaml_file) as f:
                    data = yaml.safe_load(f) or {}
                profiles.append(
                    {
                        "name": name,
                        "description": data.get("description", ""),
                        "origin": "custom",
                        "path": str(yaml_file),
                    }
                )
            except Exception:
                profiles.append(
                    {
                        "name": name,
                        "description": "(failed to parse)",
                        "origin": "custom",
                        "path": str(yaml_file),
                    }
                )

    return profiles


def load_profile(name: str) -> dict[str, Any]:
    """Load profile by name (built-in or custom)."""
    if name in BUILTIN_PROFILES:
        return BUILTIN_PROFILES[name].copy()

    profile_path = get_profiles_dir() / f"{name}.yaml"
    if not profile_path.exists():
        raise ValueError(f"Profile not found: {name}")

    with open(profile_path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid profile format: {profile_path}")

    return data


def create_profile(name: str, base: str | None = None, overwrite: bool = False) -> Path:
    """Create new custom profile."""
    if name in BUILTIN_PROFILES:
        raise ValueError(f"Cannot override built-in profile: {name}")

    profile_path = get_profiles_dir() / f"{name}.yaml"
    if profile_path.exists() and not overwrite:
        raise FileExistsError(f"Profile already exists: {name}")

    if base:
        profile_data = load_profile(base)
        profile_data["name"] = name
    else:
        profile_data = {
            "name": name,
            "description": "Custom export profile",
            "max_tokens": 6000,
            "last_n": 20,
            "include_tools": False,
            "only_code": False,
        }

    with open(profile_path, "w") as f:
        yaml.dump(profile_data, f, default_flow_style=False)

    return profile_path


def delete_profile(name: str) -> None:
    """Delete custom profile."""
    if name in BUILTIN_PROFILES:
        raise ValueError(f"Cannot delete built-in profile: {name}")

    profile_path = get_profiles_dir() / f"{name}.yaml"
    if not profile_path.exists():
        raise FileNotFoundError(f"Profile not found: {name}")

    profile_path.unlink()
