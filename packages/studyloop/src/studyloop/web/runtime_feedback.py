"""Pure formatting helpers for web runtime feedback."""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address


@dataclass(frozen=True)
class WebAccessInfo:
    """Client-facing URLs and bind details for the web server."""

    local_url: str
    lan_urls: tuple[str, ...]
    bind_url: str
    lan_enabled: bool


@dataclass(frozen=True)
class LanCredentialFeedback:
    """Credential feedback safe for terminal output."""

    username: str
    password: str
    password_generated: bool


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
    else:
        lines.append("  [dim]Use --lan to expose to network[/dim]")
    return lines


def format_lan_credential_lines(feedback: LanCredentialFeedback) -> list[str]:
    """Format LAN credentials without echoing stored or user-provided passwords."""
    if not feedback.password:
        return []

    lines = [
        "[bold yellow]LAN authentication:[/bold yellow]",
        f"  Username: [green]{feedback.username}[/green]",
    ]
    if feedback.password_generated:
        lines.append(f"  Password: [green]{feedback.password}[/green]")
        lines.append(
            "  [dim]Set lan_username and lan_password in config.yaml "
            "to avoid auto-generated passwords.[/dim]"
        )
    else:
        lines.append("  Password: [dim]configured; not shown[/dim]")
    return lines
