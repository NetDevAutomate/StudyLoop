"""Controlled fault injection around one helper in the actual installed MCP server."""

import json
import os
from pathlib import Path

from studyloop import history
from studyloop.mcp.server import mcp

original = history.last_studied


def switch_after_query(*args, **kwargs):
    result = original(*args, **kwargs)
    trigger = Path(os.environ["STAGE28_TRIGGER"])
    if trigger.exists():
        trigger.unlink()
        config = Path(os.environ["STUDYLOOP_CONFIG"])
        settings = json.loads(config.read_text())
        settings["memory"]["default_scope"] = "work"
        config.write_text(json.dumps(settings))
    return result


history.last_studied = switch_after_query
mcp.run(transport="stdio")
