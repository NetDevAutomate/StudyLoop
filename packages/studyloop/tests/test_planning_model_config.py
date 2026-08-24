"""Fixed-endpoint configuration and loopback LiteLLM detection contracts."""

from __future__ import annotations

import http.server
import json
import threading
from typing import Any

import pytest


class _NetworkStream:
    def __init__(self, peer_host: str) -> None:
        self.peer_host = peer_host

    def get_extra_info(self, name: str) -> object:
        if name == "server_addr":
            return (self.peer_host, 4000)
        return None


class _Response:
    def __init__(
        self,
        *,
        status_code: int = 200,
        peer_host: str = "127.0.0.1",
        payload: object | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.extensions = {"network_stream": _NetworkStream(peer_host)}
        self._payload = payload or {"data": [{"id": "planner-model"}]}
        self.headers = headers or {}

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    @property
    def is_redirect(self) -> bool:
        return 300 <= self.status_code < 400

    def json(self) -> object:
        return self._payload

    def read(self) -> bytes:
        return b""

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    def __init__(self, capture: dict[str, Any], response: _Response, **kwargs: Any) -> None:
        capture["kwargs"] = kwargs
        self.capture = capture
        self.response = response

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def stream(self, method: str, url: str) -> _Response:
        self.capture["method"] = method
        self.capture["url"] = url
        return self.response


def _install_client(monkeypatch: pytest.MonkeyPatch, response: _Response) -> dict[str, Any]:
    capture: dict[str, Any] = {}

    def factory(**kwargs: Any) -> _Client:
        return _Client(capture, response, **kwargs)

    monkeypatch.setattr("studyloop.planning.model_config.httpx.Client", factory)
    return capture


def test_loopback_detection_ignores_hostile_proxy_environment_and_pins_peer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enabling HTTPX environment trust or skipping peer verification breaks confinement."""
    from studyloop.planning.model_config import LoopbackCandidate, detect_loopback_litellm

    monkeypatch.setenv("HTTP_PROXY", "http://attacker.invalid:9999")
    monkeypatch.setenv("HTTPS_PROXY", "http://attacker.invalid:9999")
    capture = _install_client(monkeypatch, _Response())

    profile = detect_loopback_litellm(
        (LoopbackCandidate("http://127.0.0.1:4000/v1", connect_timeout_seconds=0.25),)
    )

    assert profile is not None
    assert profile.base_url == "http://127.0.0.1:4000/v1"
    assert profile.model == "planner-model"
    assert capture["kwargs"]["trust_env"] is False
    assert capture["kwargs"]["follow_redirects"] is False
    assert capture["url"] == "http://127.0.0.1:4000/v1/models"


def test_loopback_detection_verifies_the_real_connected_peer_before_socket_close() -> None:
    """Reading peer metadata after HTTPX closes its socket makes every real gateway invisible."""
    from studyloop.planning.model_config import LoopbackCandidate, detect_loopback_litellm

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = json.dumps({"data": [{"id": "real-local-model"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return None

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        profile = detect_loopback_litellm((LoopbackCandidate(f"http://127.0.0.1:{port}/v1"),))
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert profile is not None
    assert profile.model == "real-local-model"


@pytest.mark.parametrize(
    ("candidate", "response"),
    [
        ("http://192.168.1.20:4000/v1", _Response()),
        ("http://localhost:4000/v1", _Response()),
        (
            "http://127.0.0.1:4000/v1",
            _Response(status_code=307, headers={"location": "http://example.test"}),
        ),
        ("http://127.0.0.1:4000/v1", _Response(peer_host="10.0.0.8")),
    ],
)
def test_loopback_detection_refuses_lan_dns_redirect_and_non_loopback_peer(
    monkeypatch: pytest.MonkeyPatch,
    candidate: str,
    response: _Response,
) -> None:
    """Accepting any of these cases would let discovery select a non-local destination."""
    from studyloop.planning.model_config import LoopbackCandidate, detect_loopback_litellm

    capture = _install_client(monkeypatch, response)

    assert detect_loopback_litellm((LoopbackCandidate(candidate),)) is None
    if candidate.startswith("http://127."):
        assert capture.get("url") == "http://127.0.0.1:4000/v1/models"
    else:
        assert "url" not in capture


def test_explicit_profile_is_normalized_once_and_contains_only_a_secret_reference() -> None:
    """Storing a raw provider key or accepting a model-controlled path must fail validation."""
    from studyloop.planning.model_config import PlanningModelProfile

    profile = PlanningModelProfile.from_explicit(
        base_url="https://gateway.example.test/v1/",
        model="  chosen-model  ",
        api_key_ref="env:STUDYLOOP_PLANNING_KEY",  # pragma: allowlist secret
    )

    assert profile.base_url == "https://gateway.example.test/v1"
    assert profile.model == "chosen-model"
    assert profile.api_key_ref == "env:STUDYLOOP_PLANNING_KEY"  # pragma: allowlist secret
    assert "secret-value" not in repr(profile)

    credential_url = (
        "https://user:"
        "secret-value@gateway.example.test/v1?next=http://evil.test"  # pragma: allowlist secret
    )
    with pytest.raises(ValueError, match=r"query|fragment|credentials"):
        PlanningModelProfile.from_explicit(
            base_url=credential_url,
            model="chosen-model",
        )


def test_profile_probe_resolves_an_environment_reference_without_retaining_the_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An authenticated readiness check must not put plaintext in the profile or result."""
    from studyloop.planning.model_config import PlanningModelProfile, probe_model_profile

    secret = "provider-secret-that-must-not-be-retained"  # pragma: allowlist secret
    monkeypatch.setenv("STUDYLOOP_PLANNING_KEY", secret)
    capture = _install_client(monkeypatch, _Response())
    profile = PlanningModelProfile.from_explicit(
        base_url="https://gateway.example.test/v1",
        model="planner-model",
        api_key_ref="env:STUDYLOOP_PLANNING_KEY",  # pragma: allowlist secret
    )

    assert probe_model_profile(profile) is True
    assert capture["kwargs"]["headers"] == {"Authorization": f"Bearer {secret}"}
    assert secret not in repr(profile)


def test_profile_probe_resolves_an_encrypted_store_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The configured reference, rather than a raw key, selects encrypted storage."""
    from studyloop.planning.model_config import PlanningModelProfile, probe_model_profile

    secret = "encrypted-provider-secret"  # pragma: allowlist secret
    monkeypatch.setattr(
        "studyloop.secrets.get_secret", lambda name: secret if name == "openai" else None
    )
    capture = _install_client(monkeypatch, _Response())
    profile = PlanningModelProfile.from_explicit(
        base_url="https://gateway.example.test/v1",
        model="planner-model",
        api_key_ref="secret:openai",  # pragma: allowlist secret
    )

    assert probe_model_profile(profile) is True
    assert capture["kwargs"]["headers"] == {"Authorization": f"Bearer {secret}"}


def test_profile_probe_refuses_missing_or_malformed_secret_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing references fail closed; reference payloads cannot smuggle whitespace."""
    from studyloop.planning.model_config import PlanningModelProfile, probe_model_profile

    monkeypatch.delenv("MISSING_PLANNING_KEY", raising=False)
    client_created = False

    def factory(**_kwargs: Any) -> _Client:
        nonlocal client_created
        client_created = True
        raise AssertionError("a missing credential must fail before network access")

    monkeypatch.setattr("studyloop.planning.model_config.httpx.Client", factory)
    profile = PlanningModelProfile.from_explicit(
        base_url="https://gateway.example.test/v1",
        model="planner-model",
        api_key_ref="env:MISSING_PLANNING_KEY",  # pragma: allowlist secret
    )

    assert probe_model_profile(profile) is False
    assert client_created is False
    with pytest.raises(ValueError, match="api_key_ref"):
        PlanningModelProfile.from_explicit(
            base_url="https://gateway.example.test/v1",
            model="planner-model",
            api_key_ref="env:KEY\nAuthorization: injected",  # pragma: allowlist secret
        )


def test_profile_config_refuses_unknown_or_plaintext_credential_fields() -> None:
    """Silently ignoring a raw-key field could let doctor certify unsafe configuration."""
    from studyloop.planning.model_config import profile_from_config

    assert (
        profile_from_config(
            {
                "base_url": "https://gateway.example.test/v1",
                "model": "planner-model",
                "api_key_ref": "env:PLANNING_KEY",  # pragma: allowlist secret
                "api_key": "plaintext-provider-key",  # pragma: allowlist secret
            }
        )
        is None
    )
