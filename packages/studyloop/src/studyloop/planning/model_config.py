"""Server-owned planning model profiles and safe loopback discovery."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import urlsplit, urlunsplit

import httpx

DEFAULT_CONNECT_TIMEOUT_SECONDS = 0.35
DEFAULT_TURN_TIMEOUT_SECONDS = 120.0
_ENV_REFERENCE = re.compile(r"env:[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
_SECRET_REFERENCE = re.compile(r"secret:[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


@dataclass(frozen=True, slots=True)
class PlanningModelProfile:
    base_url: str
    model: str
    api_key_ref: str | None
    connect_timeout_seconds: float
    turn_timeout_seconds: float

    @classmethod
    def from_explicit(
        cls,
        *,
        base_url: str,
        model: str,
        api_key_ref: str | None = None,
        connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        turn_timeout_seconds: float = DEFAULT_TURN_TIMEOUT_SECONDS,
    ) -> PlanningModelProfile:
        normalized = _normalize_base_url(base_url)
        selected_model = model.strip()
        if not selected_model or len(selected_model) > 256:
            raise ValueError("planning model is required and must be at most 256 characters")
        reference = api_key_ref.strip() if api_key_ref else None
        if reference and not (
            _ENV_REFERENCE.fullmatch(reference) or _SECRET_REFERENCE.fullmatch(reference)
        ):
            raise ValueError("api_key_ref must use env: or secret: and never contain a raw key")
        if connect_timeout_seconds <= 0 or turn_timeout_seconds <= 0:
            raise ValueError("planning model timeouts must be positive")
        return cls(
            normalized,
            selected_model,
            reference,
            float(connect_timeout_seconds),
            float(turn_timeout_seconds),
        )


@dataclass(frozen=True, slots=True)
class LoopbackCandidate:
    base_url: str
    model: str = ""
    connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS
    turn_timeout_seconds: float = DEFAULT_TURN_TIMEOUT_SECONDS


DEFAULT_LOOPBACK_CANDIDATES: tuple[LoopbackCandidate, ...] = (
    LoopbackCandidate("http://127.0.0.1:4000/v1"),
    LoopbackCandidate("http://[::1]:4000/v1"),
)


def _normalize_base_url(value: str) -> str:
    raw = value.strip()
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("planning base URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("planning base URL cannot contain credentials, query, or fragment")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, path, "", ""))


def _literal_loopback_host(base_url: str) -> bool:
    try:
        parsed = urlsplit(_normalize_base_url(base_url))
        return ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        return False


def _models_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/models"


def _response_peer_host(response: httpx.Response) -> str:
    stream = response.extensions.get("network_stream")
    if stream is None:
        return ""
    peer = stream.get_extra_info("server_addr")
    if not isinstance(peer, tuple) or not peer:
        return ""
    return str(peer[0])


def _peer_is_loopback(response: httpx.Response) -> bool:
    try:
        return ip_address(_response_peer_host(response)).is_loopback
    except ValueError:
        return False


def _model_ids(response: httpx.Response) -> tuple[str, ...]:
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return ()
    result: list[str] = []
    for item in payload["data"]:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip():
            result.append(item["id"].strip())
    return tuple(result)


def _resolve_api_key_reference(reference: str | None) -> str | None:
    if reference is None:
        return None
    kind, name = reference.split(":", 1)
    if kind == "env":
        value = os.environ.get(name)
    else:
        from studyloop.secrets import get_secret

        value = get_secret(name)
    if not value or len(value) > 16_384 or any(ord(character) < 32 for character in value):
        return None
    return value


def detect_loopback_litellm(
    candidates: tuple[LoopbackCandidate, ...],
) -> PlanningModelProfile | None:
    """Pin the first reachable literal-loopback OpenAI-compatible gateway."""
    for candidate in candidates:
        if not _literal_loopback_host(candidate.base_url):
            continue
        try:
            base_url = _normalize_base_url(candidate.base_url)
            with (
                httpx.Client(
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(candidate.connect_timeout_seconds),
                ) as client,
                client.stream("GET", _models_url(base_url)) as response,
            ):
                if response.is_redirect or not _peer_is_loopback(response):
                    continue
                response.raise_for_status()
                response.read()
                models = _model_ids(response)
            selected = candidate.model.strip() or (models[0] if models else "")
            if not selected or (candidate.model and selected not in models):
                continue
            return PlanningModelProfile.from_explicit(
                base_url=base_url,
                model=selected,
                connect_timeout_seconds=candidate.connect_timeout_seconds,
                turn_timeout_seconds=candidate.turn_timeout_seconds,
            )
        except (httpx.HTTPError, OSError, RuntimeError, ValueError, TypeError):
            continue
    return None


def probe_model_profile(profile: PlanningModelProfile) -> bool:
    """Check reachability without redirects, proxy inheritance, or secret output."""
    try:
        api_key = _resolve_api_key_reference(profile.api_key_ref)
        if profile.api_key_ref is not None and api_key is None:
            return False
        headers = {"Authorization": f"Bearer {api_key}"} if api_key is not None else {}
        with (
            httpx.Client(
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(profile.connect_timeout_seconds),
                headers=headers,
            ) as client,
            client.stream("GET", _models_url(profile.base_url)) as response,
        ):
            if response.is_redirect:
                return False
            if _literal_loopback_host(profile.base_url) and not _peer_is_loopback(response):
                return False
            response.raise_for_status()
            response.read()
            return profile.model in _model_ids(response)
    except (httpx.HTTPError, OSError, RuntimeError, ValueError, TypeError):
        return False


def profile_to_config(profile: PlanningModelProfile) -> dict[str, object]:
    return {
        "base_url": profile.base_url,
        "model": profile.model,
        "api_key_ref": profile.api_key_ref,
        "connect_timeout_seconds": profile.connect_timeout_seconds,
        "turn_timeout_seconds": profile.turn_timeout_seconds,
    }


def profile_from_config(value: object) -> PlanningModelProfile | None:
    if not isinstance(value, dict) or not value:
        return None
    allowed = {
        "base_url",
        "model",
        "api_key_ref",
        "connect_timeout_seconds",
        "turn_timeout_seconds",
    }
    if not set(value) <= allowed:
        return None
    try:
        return PlanningModelProfile.from_explicit(
            base_url=str(value["base_url"]),
            model=str(value["model"]),
            api_key_ref=str(value["api_key_ref"]) if value.get("api_key_ref") else None,
            connect_timeout_seconds=float(
                value.get("connect_timeout_seconds", DEFAULT_CONNECT_TIMEOUT_SECONDS)
            ),
            turn_timeout_seconds=float(
                value.get("turn_timeout_seconds", DEFAULT_TURN_TIMEOUT_SECONDS)
            ),
        )
    except (KeyError, TypeError, ValueError):
        return None
