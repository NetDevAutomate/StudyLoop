"""Experimental web-feature registry for ``studyloop web --dev``.

Deliberately dependency-free (stdlib only). The CLI needs the engine names at
*decorator* evaluation time to build ``--dev-engine``'s ``click.Choice``, but
``studyloop.cli._web`` defers its ``studyloop.web.app`` import so the CLI keeps
working when the ``web`` extra is not installed. Keeping the registry here lets
both sides share one source of truth without dragging FastAPI into CLI import.

Design contract
---------------
The default (non-dev) path serves ``index.html`` untouched, so xterm.js remains
the production renderer and PTY remains the only learner-facing transport.
``--dev`` also permits the experimental ACP transport; that server/UI gate is
implemented in the session routes rather than this dependency-free renderer
registry. A dev engine is opted into per-run and works by HTML injection:

1. ``<meta name="studyloop-dev-mode" content="ENGINE">`` marks which engine is
   live. Every vendored adapter checks this marker before patching
   ``window.Terminal`` and stays dormant when it does not match — which is why
   shipping several adapters side by side is safe.
2. The engine's stylesheet(s) and script(s) are appended inside ``<head>``.

Adding an engine requires only a new entry in :data:`DEV_ENGINES`.
"""

from __future__ import annotations

from typing import Any, Final

#: What renders the terminal when no ``--dev`` engine is loaded. This is the
#: production path and the *only* honest answer the picker can give by default.
STOCK_RENDERER: Final[str] = "xterm.js"

#: Vendor assets per dev engine. Keys are the ``--dev-engine`` choices and the
#: values written into the ``studyloop-dev-mode`` meta marker.
#:
#: ``renderer`` and ``caveats`` are not injection inputs — they exist so the
#: browser can *say* which engine is live and what it costs. Before they did,
#: ``--dev`` silently replaced ``window.Terminal`` while the transport picker
#: still read "Browser terminal (xterm.js)".
DEV_ENGINES: Final[dict[str, dict[str, Any]]] = {
    # libghostty — Ghostty's VT100 parser compiled to WASM, via
    # https://github.com/coder/ghostty-web (MIT).
    #
    # Self-contained: the 423 KB WASM binary is inlined in the UMD bundle as a
    # base64 data URL, so there is no second network fetch, no .wasm MIME-type
    # configuration, and the bundle works offline.
    "ghostty": {
        "css": ("/vendor/css/ghostty-0.4.0.css",),
        "js": (
            "/vendor/js/ghostty-web-0.4.0.js",
            "/vendor/js/ghostty-adapter-0.4.0.js",
        ),
        "renderer": "libghostty",
        # Verbatim from docs/web-ui-guide.md, "Known gaps (why this is still
        # --dev)". Kept short enough to fit a tooltip: a caveat nobody reads is
        # the same as no caveat.
        "caveats": (
            "Clipboard: agent OSC 52 copy requests are silently dropped.",
            "Scrollback beyond 512 KB is lost when you change palette.",
            "Emoji and other non-BMP characters cannot be typed (paste instead).",
            "Canvas rendering only — throughput under heavy output is unmeasured.",
            "Full-screen TUIs (vim, htop, mouse tracking) are untested.",
        ),
    },
}

#: Engine used when ``--dev`` is passed without ``--dev-engine``.
DEFAULT_DEV_ENGINE: Final[str] = "ghostty"


def resolve_dev_engine(engine: str | None) -> str:
    """Normalise and validate a dev engine name.

    Args:
        engine: Raw engine name (any case), or None for the default.

    Returns:
        The canonical lower-case engine key.

    Raises:
        ValueError: If the engine is not registered in :data:`DEV_ENGINES`.
    """
    if engine is None:
        return DEFAULT_DEV_ENGINE
    normalised = engine.strip().lower()
    if normalised not in DEV_ENGINES:
        known = ", ".join(sorted(DEV_ENGINES))
        raise ValueError(f"Unknown dev engine {engine!r}. Known engines: {known}")
    return normalised


def describe_terminal_engine(dev_mode: bool, engine: str | None) -> dict[str, Any]:
    """Describe the renderer that will actually paint the terminal.

    This describes the *renderer* axis. The same ``--dev`` operator flag also
    unlocks ACP on the separate transport axis, but renderer selection and
    agent transport remain independent implementation concerns.

    Args:
        dev_mode: Whether the app was created with ``--dev``.
        engine: The ``--dev-engine`` key. Inert when ``dev_mode`` is False,
            mirroring ``create_app``.

    Returns:
        A JSON-serialisable descriptor: ``dev_mode``, ``engine`` (None in the
        default path), ``renderer`` (the human name of what paints), ``label``
        (renderer plus an experimental marker), ``experimental`` and
        ``caveats``.
    """
    if not dev_mode or engine is None:
        return {
            "dev_mode": False,
            "engine": None,
            "renderer": STOCK_RENDERER,
            "label": STOCK_RENDERER,
            "experimental": False,
            "caveats": [],
        }
    resolved = resolve_dev_engine(engine)
    assets = DEV_ENGINES[resolved]
    renderer = str(assets["renderer"])
    return {
        "dev_mode": True,
        "engine": resolved,
        "renderer": renderer,
        "label": f"{renderer} (experimental)",
        "experimental": True,
        "caveats": list(assets["caveats"]),
    }


def inject_dev_engine(html: str, engine: str = DEFAULT_DEV_ENGINE) -> str:
    """Inject a dev terminal engine's marker, stylesheet and scripts into HTML.

    Scripts are injected with ``defer`` deliberately. index.html loads the
    xterm.js vendor bundles with ``defer`` too, and deferred scripts execute in
    document order, so appending here guarantees the adapter's
    ``window.Terminal = ...`` assignment is the last writer. Without ``defer``
    the adapter would run first and xterm.js would immediately overwrite it.

    Args:
        html: Raw contents of index.html.
        engine: Key into :data:`DEV_ENGINES`.

    Returns:
        The HTML with the marker, stylesheet links and script tags inserted
        inside ``<head>``.

    Raises:
        ValueError: If ``engine`` is not a known dev engine.
    """
    resolved = resolve_dev_engine(engine)
    assets = DEV_ENGINES[resolved]

    head_injection = f'\n  <meta name="studyloop-dev-mode" content="{resolved}">'
    for href in assets["css"]:
        head_injection += f'\n  <link rel="stylesheet" href="{href}">'
    html = html.replace("<head>", "<head>" + head_injection, 1)

    scripts = (
        f"\n  <!-- {resolved} dev-mode: defer so these run after the xterm defer"
        " scripts; the adapter patches window.Terminal last -->"
    )
    for src in assets["js"]:
        scripts += f'\n  <script defer src="{src}"></script>'
    return html.replace("</head>", scripts + "\n</head>", 1)
