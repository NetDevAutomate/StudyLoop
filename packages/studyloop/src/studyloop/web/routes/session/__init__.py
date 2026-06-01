"""Session API routes — live study session dashboard."""

from studyloop.session_state import (
    PARKING_FILE,
    SESSION_DIR,
    STATE_FILE,
    is_session_active,
    parse_parking_file,
    parse_topics_file,
    read_session_state,
    write_session_state,
)

# Register routes (side-effect imports)
from studyloop.web.routes.session import (  # noqa: F401
    _dashboard,
    _options,
    _start,
    _ws,
)
from studyloop.web.routes.session._ipc import _get_full_state
from studyloop.web.routes.session._models import StartSessionRequest
from studyloop.web.routes.session._options import (
    _agent_options,
    _course_options,
    _lesson_options,
    _topic_options,
    _vendor_options,
)
from studyloop.web.routes.session._render import (
    STATUS_SHAPES,
    _render_activity_feed,
    _render_counters,
    _render_session_meta,
    _render_summary,
    _render_update,
)
from studyloop.web.routes.session._router import router
from studyloop.web.routes.session._transport import (
    _build_acp_transport,
    _build_pty_transport,
)

__all__ = [
    "PARKING_FILE",
    "SESSION_DIR",
    "STATE_FILE",
    "STATUS_SHAPES",
    "StartSessionRequest",
    "_agent_options",
    "_build_acp_transport",
    "_build_pty_transport",
    "_course_options",
    "_get_full_state",
    "_lesson_options",
    "_render_activity_feed",
    "_render_counters",
    "_render_session_meta",
    "_render_summary",
    "_render_update",
    "_topic_options",
    "_vendor_options",
    "is_session_active",
    "parse_parking_file",
    "parse_topics_file",
    "read_session_state",
    "router",
    "write_session_state",
]
