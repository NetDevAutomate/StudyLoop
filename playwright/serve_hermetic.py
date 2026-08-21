"""Run a hermetic StudyLoop server for interactive browser testing.

This is deliberately a thin CLI around the same ``TestWorld`` and
``RunningServer`` objects used by the pytest journeys. It gives
``agent-browser`` a long-lived server to drive without exposing the developer's
HOME, configuration, databases, plans, or environment.

Typical usage::

    uv run --all-packages python playwright/serve_hermetic.py

The process stays alive until interrupted. Its first line is JSON connection
metadata; no environment values or credentials are printed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO_ROOT / "packages" / "studyloop" / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from e2e._env import (  # noqa: E402
    RunningServer,
    build_test_world,
    start_server,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface for the hermetic server."""
    parser = argparse.ArgumentParser(
        description="Run a long-lived hermetic StudyLoop server for agent-browser."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=18612,
        help="Loopback port for the server (default: 18612).",
    )
    parser.add_argument(
        "--root",
        type=Path,
        help="Existing directory for world data; defaults to a temporary directory.",
    )
    parser.add_argument(
        "--ready-file",
        type=Path,
        help="Optional JSON file receiving the same connection metadata as stdout.",
    )
    parser.add_argument(
        "--real-agent",
        action="store_true",
        help="Disable the deterministic fake agent; not recommended for CRUD tests.",
    )
    return parser


def connection_metadata(server: RunningServer, *, fake_agent: bool) -> dict[str, object]:
    """Return safe connection metadata without exposing environment values."""
    world = server.world
    return {
        "base_url": server.base_url,
        "fake_agent": fake_agent,
        "pid": server.proc.pid,
        "plans_dir": str(world.plans),
        "root": str(world.root),
        "session_db": str(world.session_db),
    }


def _temporary_root() -> Path:
    return Path(tempfile.mkdtemp(prefix="studyloop-agent-browser-"))


def run(argv: Sequence[str] | None = None) -> int:
    """Start the server and keep it alive until interrupted."""
    args = build_parser().parse_args(argv)
    owns_root = args.root is None
    root = args.root if args.root is not None else _temporary_root()
    fake_agent = not args.real_agent

    try:
        world = build_test_world(root, args.port, fake_agent=fake_agent)
        server = start_server(world)
    except Exception:
        if owns_root:
            shutil.rmtree(root, ignore_errors=True)
        raise

    metadata = connection_metadata(server, fake_agent=fake_agent)
    if args.ready_file is not None:
        args.ready_file.parent.mkdir(parents=True, exist_ok=True)
        args.ready_file.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(metadata, sort_keys=True), flush=True)

    try:
        server.proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        if owns_root:
            shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
