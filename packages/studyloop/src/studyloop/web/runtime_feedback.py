"""Pure formatting helpers for web runtime feedback."""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True)
class WebAccessInfo:
    """Client-facing URLs and bind details for the web server."""

    local_url: str
    lan_urls: tuple[str, ...]
    bind_url: str
    lan_enabled: bool


def _format_url(host: str, port: int, path: str = "") -> str:
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    normalized_path = path if not path or path.startswith("/") else f"/{path}"
    return f"http://{host}:{port}{normalized_path}"


def _is_client_usable_lan_host(host: str) -> bool:
    try:
        parsed = ip_address(host)
    except ValueError:
        return bool(host and host != "0.0.0.0")
    return not (parsed.is_unspecified or parsed.is_loopback)


def build_web_access_info(
    *,
    bind_host: str,
    port: int,
    lan_enabled: bool,
    lan_hosts: tuple[str, ...] = (),
    path: str = "",
) -> WebAccessInfo:
    """Build client-facing URLs without exposing wildcard bind addresses as URLs."""
    local_host = "127.0.0.1" if bind_host in {"0.0.0.0", "::"} else bind_host
    seen_hosts: set[str] = set()
    usable_lan_hosts: list[str] = []
    for host in lan_hosts:
        if host in seen_hosts or not _is_client_usable_lan_host(host):
            continue
        seen_hosts.add(host)
        usable_lan_hosts.append(host)

    return WebAccessInfo(
        local_url=_format_url(local_host, port, path),
        lan_urls=tuple(_format_url(host, port, path) for host in usable_lan_hosts),
        bind_url=_format_url(bind_host, port),
        lan_enabled=lan_enabled,
    )


def format_web_access_lines(info: WebAccessInfo) -> list[str]:
    """Format web access info for Rich console output."""
    lines = ["[bold]Study PWA[/bold]", f"  Local: {info.local_url}"]
    if info.lan_enabled:
        if info.lan_urls:
            for url in info.lan_urls:
                lines.append(f"  LAN:   {url}")
        else:
            lines.append("  LAN:   unable to detect LAN IP; use this device's network IP")
        lines.append(f"  [dim]Listening on {info.bind_url}[/dim]")
        lines.append(
            "  [bold yellow]Security:[/bold yellow] Plain HTTP provides no transport "
            "confidentiality; use only a trusted network with TLS or a trusted "
            "VPN/encrypted tunnel."
        )
        lines.append(
            "  [yellow]A copied verifier for a weak password is offline guessable; "
            "use a strong unique password.[/yellow]"
        )
    else:
        lines.append("  [dim]Use --lan to expose to network[/dim]")
    return lines


def emit_lan_credential_lines(
    *,
    username: str,
    generated_password: str | None,
    emit: Callable[[str], None],
) -> None:
    """Emit credential feedback without retaining plaintext in a DTO or return value."""
    lines: list[str] = [
        "[bold yellow]LAN authentication:[/bold yellow]",
        f"  Username: [green]{username}[/green]",
    ]
    if generated_password is not None:
        lines.append(f"  Password: [green]{generated_password}[/green]")
        lines.append(
            "  [dim]Generated for this launch; it is not stored in agent-readable "
            "config or session state.[/dim]"
        )
    else:
        lines.append("  Password: [dim]configured; not shown[/dim]")
    for line in lines:
        emit(line)
