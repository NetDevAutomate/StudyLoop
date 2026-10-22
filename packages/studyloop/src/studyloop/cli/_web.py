"""Web server command — study PWA."""

from __future__ import annotations

import contextlib
import socket
from typing import TYPE_CHECKING

import click

from studyloop.cli._shared import console
from studyloop.web.runtime_feedback import (
    LanCredentialFeedback,
    build_web_access_info,
    format_lan_credential_lines,
    format_web_access_lines,
)

if TYPE_CHECKING:
    from types import FrameType as _FrameType


def _candidate_lan_hosts() -> tuple[str, ...]:
    """Best-effort LAN address discovery for runtime feedback."""
    hosts: list[str] = []
    with contextlib.suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(("8.8.8.8", 80))
        hosts.append(sock.getsockname()[0])
    with contextlib.suppress(OSError):
        hosts.append(socket.gethostbyname(socket.gethostname()))
    return tuple(hosts)


def _is_local_address(address: str) -> bool:
    """Whether *address* is assigned to one of this machine's interfaces.

    Asks the kernel rather than enumerating interfaces: binding a socket to an
    address the machine does not have fails (``EADDRNOTAVAIL``), portably.
    """
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    with contextlib.suppress(OSError), socket.socket(family, socket.SOCK_STREAM) as probe:
        probe.bind((address, 0))
        return True
    return False


def _validated_bind_address(value: str) -> str:
    """The ``--bind`` value as a canonical IP literal this machine owns (D7).

    Refuses (exit 2) a value that is not an IP literal, a wildcard (that is
    ``--lan``'s every-interface exposure the ruling removes), or an address no
    interface of this machine carries, naming the candidates it can find.
    """
    import ipaddress

    def refuse(reason: str) -> click.BadParameter:
        candidates = ", ".join(dict.fromkeys(("127.0.0.1", *_candidate_lan_hosts())))
        return click.BadParameter(
            f"{value!r} {reason}. Addresses this machine reports: {candidates} "
            "(and any VPN address, e.g. `tailscale ip -4`).",
            param_hint="'--bind'",
        )

    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        raise refuse("is not an IP address") from None
    if address.is_unspecified:
        raise refuse(
            "binds every interface; name one address instead (the deprecated --lan still "
            "does this for one release)"
        )
    if not _is_local_address(str(address)):
        raise refuse("is not an address of this machine")
    return str(address)


#: Where every local consumer of the dashboard dials: ``modules/hop.py`` for the
#: ``studyloop drill`` practice_check hop, the launcher's readiness poll, the
#: browser this machine opens. IPv4 loopback specifically; ``::1`` is not it.
LOOPBACK = "127.0.0.1"


def listen_addresses(host: str) -> tuple[str, ...]:
    """The addresses ``studyloop web`` listens on for a validated bind *host*.

    A loopback address, or the deprecated wildcard (which already includes
    loopback), is one listener. Any other address is two: that address AND
    :data:`LOOPBACK` (review-4 item 3, ADR-0019 consequences), so a server
    bound to a tailnet address still answers ``studyloop drill`` and the other
    local consumers that assume loopback. Host and Origin checks (ADR-0014) are
    made per request against its own ``Host`` header, so they hold unchanged on
    both listeners.
    """
    import ipaddress

    address = ipaddress.ip_address(host)
    if address.is_loopback or address.is_unspecified:
        return (host,)
    return (host, LOOPBACK)


def listen_sockets(hosts: tuple[str, ...], port: int) -> list[socket.socket]:
    """Bound (not yet listening) TCP sockets for *hosts* on the one *port*.

    What ``uvicorn.Config.bind_socket`` does for one address, for several, and
    atomically: if any bind fails, every socket already bound is closed before
    the ``OSError`` propagates, so the server never comes up half-reachable.
    """
    bound: list[socket.socket] = []
    try:
        for host in hosts:
            family = socket.AF_INET6 if ":" in host else socket.AF_INET
            sock = socket.socket(family, socket.SOCK_STREAM)
            bound.append(sock)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
            sock.set_inheritable(True)
    except OSError:
        for sock in bound:
            sock.close()
        raise
    return bound


def _answers(host: str, port: int) -> bool:
    """Whether something accepts a TCP connection on *host*:*port* (one-second bound)."""
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def _show_url() -> None:
    """``studyloop web --show-url``: re-print the launcher's sign-in URL (review-4 item 4).

    The launcher prints it once, before tmux attaches; a closed tab lost it. The
    token and the bound host sit in the owner-only session state beside the
    practice_check capability (same file, same threat model), and the address is
    printed only when something answers on the recorded port -- a dead server's
    token is nobody's credential and is not handed out.
    """
    from studyloop.session_state import read_session_state
    from studyloop.web.ws_origin import BOOTSTRAP_QUERY

    state = read_session_state()
    port = state.get("web_port")
    token = state.get("web_sign_in_token")
    host = str(state.get("web_bind_host") or LOOPBACK)
    none_up = (
        "No studyloop web server is running for this session. Start one with "
        "`studyloop study --web` (or `--bind ADDRESS`), or run `studyloop web` by hand."
    )
    try:
        port_number = int(port) if port else 0
    except (TypeError, ValueError):
        port_number = 0
    if not port_number:
        raise click.ClickException(none_up)
    if not _answers(LOOPBACK, port_number):
        raise click.ClickException(none_up)
    if not token:
        raise click.ClickException(
            f"A server answers on port {port_number} but this session recorded no sign-in "
            "token for it: it was started by hand (`studyloop web`), and its sign-in URL was "
            "printed where it started."
        )
    netloc = f"[{host}]:{port_number}" if ":" in host else f"{host}:{port_number}"
    # soft_wrap: a sign-in URL folded across two lines cannot be copied or clicked.
    console.print(f"http://{netloc}/session?{BOOTSTRAP_QUERY}={token}", soft_wrap=True)


#: Printed by the deprecated ``--lan`` (D7), the same five caveats the setup
#: guide's second-device section carries.
_LAN_CAVEATS = (
    "Basic authentication does not encrypt the password, requests, responses or terminal traffic.",
    "LAN peers or intermediaries able to observe traffic may steal credentials and study "
    "content; active intermediaries may tamper with traffic.",
    "Never reuse a password, expose this mode directly to the Internet, or treat public/shared "
    "Wi-Fi as trusted.",
    "Prefer loopback access through an authenticated encrypted tunnel, or a correctly "
    "configured HTTPS/WSS reverse proxy with the application bound to loopback.",
    "0.0.0.0 exposes every IPv4 interface unless a firewall restricts access.",
)


@click.command()
@click.option("--port", "-p", default=8567, help="Port for web server")
@click.option(
    "--bind",
    "bind_address",
    default=None,
    metavar="ADDRESS",
    help="Serve on this one IP address of this machine instead of 127.0.0.1, e.g. its "
    "Tailscale/VPN address, where the tunnel encrypts the traffic. A non-loopback address "
    "requires the Basic-auth password (generated when unset).",
)
@click.option(
    "--lan",
    is_flag=True,
    help="Deprecated: binds every interface (0.0.0.0) in cleartext; use --bind ADDRESS. "
    "Removed in the next release.",
)
@click.option(
    "--password",
    default="",
    envvar="STUDYLOOP_WEB_PASSWORD",
    help="Password for HTTP Basic Auth (--bind/--lan protection). Also settable via "
    "STUDYLOOP_WEB_PASSWORD (used internally when `studyloop study --web --lan` "
    "spawns this command, so the password never appears in this process's argv).",
)
@click.option(
    "--dev",
    is_flag=True,
    default=False,
    help="Developer experiment mode: swap xterm.js for an alternative renderer.",
)
@click.option(
    "--show-url",
    is_flag=True,
    default=False,
    help="Print the sign-in address of the dashboard your study session started (token "
    "included) and exit; for when the tab was closed. Starts nothing.",
)
def web(
    port: int,
    bind_address: str | None,
    lan: bool,
    password: str,
    dev: bool,
    show_url: bool,
) -> None:
    """Launch the study PWA in your browser.

    Serves flashcard and quiz review as a web app on this machine (another
    device can reach it with --bind). Installable as a PWA (add to home
    screen). Includes OpenDyslexic font toggle for accessibility.

    Requires: uv pip install 'studyloop[web]'
    """
    if show_url:
        _show_url()
        return
    # R-10b: Click's envvar= support has already read STUDYLOOP_WEB_PASSWORD
    # into `password` above (that is the whole point of it — see the option's
    # help text and session/orchestrator.py::start_web_background, which sets
    # it so the --lan password never appears in the SPAWNED process's argv).
    # But leaving it in this process's OWN environ afterwards means every
    # non-agent subprocess this server itself spawns inherits it too, and
    # `ps eww`/`/proc/<pid>/environ` shows it here for this process's whole
    # lifetime — the exact argv-visibility problem R-10 fixed, recreated one
    # layer up. Scrub it the moment it has been read.
    import os as _os

    _os.environ.pop("STUDYLOOP_WEB_PASSWORD", None)

    # D2: the launcher hands over the server secret it minted the same way, so it
    # can open the browser at the sign-in URL. Scrubbed for the same reason as the
    # password: every child this server spawns would otherwise inherit it.
    from studyloop.web.ws_origin import BOOTSTRAP_QUERY, BOOTSTRAP_TOKEN_ENV, is_well_formed_secret

    launcher_token = _os.environ.pop(BOOTSTRAP_TOKEN_ENV, "")
    if launcher_token and not is_well_formed_secret(launcher_token):
        msg = (
            f"{BOOTSTRAP_TOKEN_ENV} must be at least 32 URL-safe characters "
            "(A-Z, a-z, 0-9, '-', '_'); refusing to start with it."
        )
        raise click.ClickException(msg)

    # D7 (council pass 3): one validated address instead of every interface.
    if lan and bind_address is not None:
        msg = "--lan and --bind cannot be combined; use --bind ADDRESS (--lan is deprecated)."
        raise click.UsageError(msg)
    if lan:
        host = "0.0.0.0"
    elif bind_address is not None:
        host = _validated_bind_address(bind_address)
    else:
        host = "127.0.0.1"
    import ipaddress as _ipaddress

    # Anything but loopback reaches other machines, and gets the password gate.
    exposed = lan or not _ipaddress.ip_address(host).is_loopback

    try:
        import uvicorn
    except ImportError:
        console.print(
            "[red]The web server requires FastAPI.[/red]\nInstall: uv pip install 'studyloop[web]'"
        )
        return

    import secrets

    from studyloop.settings import resolve_study_dirs

    study_dirs: list[str] = []
    with contextlib.suppress(Exception):
        # Falls back to content.base_path when review.directories is unset, so
        # the review panels discover decks the generator just wrote.
        study_dirs = resolve_study_dirs()

    # Resolve credentials: always read username from config; password from CLI > config > auto
    username = "study"
    password_generated = False
    try:
        from studyloop.settings import load_settings

        _settings = load_settings()
        username = _settings.lan_username or "study"
        if not password:
            password = _settings.lan_password
    except Exception:
        pass

    if exposed and not password:
        password = secrets.token_urlsafe(16)
        password_generated = True

    if lan:
        console.print(
            "[bold yellow]--lan is deprecated[/bold yellow] and is removed in the next release: "
            "it binds 0.0.0.0, every interface on every network this machine joins. Use "
            "--bind ADDRESS with one address, ideally a Tailscale/VPN address where the "
            "tunnel encrypts the traffic (docs/setup-guide.md, Remote Study)."
        )
        console.print("[bold yellow]Security caveats for --lan:[/bold yellow]")
        for caveat in _LAN_CAVEATS:
            console.print(f"  - {caveat}")
    elif exposed:
        console.print(
            "[yellow]Basic auth is a password gate, not encryption:[/yellow] serve "
            f"{host} only on a link that encrypts (Tailscale/VPN), or use ssh -L instead."
        )

    if exposed and password:
        for line in format_lan_credential_lines(
            LanCredentialFeedback(
                username=username,
                password=password,
                password_generated=password_generated,
            )
        ):
            console.print(line)

    from studyloop.web.app import create_app

    # `--dev` goes through the dev_engines REGISTRY. The deprecated
    # `--dev-renderer` inline path that used to sit alongside it is gone: it
    # injected different markup and shipped a duplicate 624 KB bundle plus the
    # only runtime consumer of the standalone ghostty-vt wasm.
    dev_engine = "ghostty" if dev else None

    if dev:
        # One engine since wterm was removed, so no branch is needed. Kept as a
        # named variable so adding a second engine later reintroduces the choice
        # in one obvious place.
        renderer_label = "ghostty-web (canvas renderer)"
        console.print(f"[yellow]--dev mode:[/yellow] xterm.js swapped for {renderer_label}")

    # Per-process server secret (F-WEB-20, 2026-10-21 review): `/api/*` plus both
    # WebSockets require it as an HttpOnly, SameSite=Strict cookie, and `/` hands
    # that cookie only to a browser presenting the secret as `?token=` (D2,
    # council pass 3), so neither a cross-site page nor a local process that
    # merely loads `/` can drive the API or the terminal. Printed once, inside the
    # sign-in URL (Jupyter's model); never stored. A restart mints a new one, and
    # a tab from before it must be reopened from the new URL.
    server_secret = launcher_token or secrets.token_urlsafe(32)
    app = create_app(
        study_dirs=study_dirs,
        username=username,
        password=password,
        dev_mode=dev,
        dev_engine=dev_engine,
        server_secret=server_secret,
    )
    access_info = build_web_access_info(
        bind_host=host,
        port=port,
        lan_enabled=lan,
        lan_hosts=_candidate_lan_hosts() if lan else (),
        path=f"/?{BOOTSTRAP_QUERY}={server_secret}",
    )
    # soft_wrap: a sign-in URL folded across two lines cannot be copied or clicked.
    if lan or not exposed:
        for line in format_web_access_lines(access_info):
            console.print(line, soft_wrap=True)
    else:
        # --bind <address>: the bound address is the one the other device opens;
        # loopback is served too (item 3) so this machine's own tools and browser
        # keep reaching the server the way they always have.
        console.print("[bold]Study PWA[/bold]")
        console.print(f"  Address: {access_info.local_url}", soft_wrap=True)
        loopback_url = build_web_access_info(
            bind_host=LOOPBACK,
            port=port,
            lan_enabled=False,
            path=f"/?{BOOTSTRAP_QUERY}={server_secret}",
        ).local_url
        console.print(f"  Local:   {loopback_url}", soft_wrap=True)
    console.print(
        "  [dim]Open that address to sign a browser in; the token is new each time "
        "studyloop web starts.[/dim]"
    )
    # loop="asyncio" is required for PTYTransport: uvloop reserves SIGCHLD
    # for its own subprocess tracking and refuses to install a user handler,
    # which our PTY child-exit detection depends on. The standard asyncio
    # loop allows add_signal_handler(SIGCHLD, ...) to coexist with subprocess
    # watching. See plan Blocker B6 + Amendment #7.
    #
    # Ctrl-C hardening: uvicorn's graceful shutdown can hang when a PTY/ACP
    # subprocess is wedged (e.g. Kiro MCP bootstrap stuck, child not reaping).
    # uvicorn's own handler escalates to ``force_exit=True`` only on a *second*
    # SIGINT — and even ``force_exit`` waits on hung tasks. We subclass
    # ``Server`` so the first SIGINT also kicks off a watchdog thread that
    # ``os._exit()``s after a grace window. Result: one Ctrl-C is enough,
    # operator never has to hunt PIDs.
    import os as _os
    import threading as _threading
    import time as _time

    class _StudyLoopServer(uvicorn.Server):
        _watchdog_started: bool = False

        def handle_exit(self, sig: int, frame: _FrameType | None) -> None:
            if not self._watchdog_started:
                self._watchdog_started = True
                console.print("\n[yellow]Shutting down… (Ctrl-C again to force)[/yellow]")
                _threading.Thread(
                    target=_force_exit_watchdog,
                    args=(5.0,),
                    daemon=True,
                ).start()
            super().handle_exit(sig, frame)

    def _force_exit_watchdog(grace: float) -> None:
        _time.sleep(grace)
        console.print(f"\n[red]Force-exiting after {grace:.0f}s (uvicorn shutdown hung).[/red]")
        _os._exit(130)

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        workers=1,
        log_level="warning",
        loop="asyncio",
    )
    # A non-loopback --bind listens on that address AND on loopback (item 3), so
    # the sockets are bound here and handed to uvicorn rather than letting it
    # bind config.host alone. One listener keeps uvicorn's own bind path.
    hosts = listen_addresses(host)
    if len(hosts) == 1:
        _StudyLoopServer(config).run()
        return
    try:
        sockets = listen_sockets(hosts, port)
    except OSError as exc:
        raise click.ClickException(
            f"Could not listen on port {port} at {' and '.join(hosts)}: {exc.strerror or exc}. "
            "Is another studyloop web (or your study session's dashboard) already running "
            "on it? Pick another with --port."
        ) from None
    _StudyLoopServer(config).run(sockets=sockets)
