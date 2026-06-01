"""Content-generation HTTP routes (generate, catalog, secrets, WS)."""

from studyloop.secrets import get_secret
from studyloop.web.routes.content_gen import (  # noqa: F401
    _catalog,
    _jobs,
    _secrets,
    _ws,
)
from studyloop.web.routes.content_gen._catalog import (
    _bedrock_credentials_available,
    _ollama_base_url,
    _ollama_reachable,
)
from studyloop.web.routes.content_gen._jobs import (
    _JOB_QUEUES,
    GenerateRequest,
    GenerateResponse,
    _drop_queue,
)
from studyloop.web.routes.content_gen._router import router

__all__ = [
    "_JOB_QUEUES",
    "GenerateRequest",
    "GenerateResponse",
    "_bedrock_credentials_available",
    "_drop_queue",
    "_ollama_base_url",
    "_ollama_reachable",
    "get_secret",
    "router",
]
