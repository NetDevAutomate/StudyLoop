"""T3: the read-only launch-state route — schema, locality, redaction, no writes.

``GET /api/second-brain/launch-target`` is the only web surface for launch
state (design: "Expose inert state through a read-only route"). The tests here
pin the exact response schema, the no-store cache policy, direct-peer-only
locality, the generic redacted invalid-configuration fallback, and — both over
HTTP and statically — that no mutation method, redirect, subprocess, or
network-client path shares the route.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

pytest = __import__("pytest")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402  # pyright: ignore[reportMissingImports]

from studyloop.web.app import create_app  # noqa: E402

if TYPE_CHECKING:
    from pytest import LogCaptureFixture, MonkeyPatch

LAUNCH_TARGET_PATH = "/api/second-brain/launch-target"
LOOPBACK_PEER = ("127.0.0.1", 50123)


def _write_config(tmp_path: Path, monkeypatch: MonkeyPatch, body: str) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(body)
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))


def _write_obsidian_config(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_config(
        tmp_path,
        monkeypatch,
        f"second_brain:\n  provider: obsidian\n  vault_path: {vault}\n",
    )
    return vault


def _client(peer: tuple[str, int]) -> TestClient:
    return TestClient(create_app(study_dirs=[]), client=peer)


def test_loopback_peer_gets_local_obsidian_state_with_no_store(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _write_obsidian_config(tmp_path, monkeypatch)

    resp = _client(LOOPBACK_PEER).get(LAUNCH_TARGET_PATH)

    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    body = resp.json()
    assert body["provider"] == "obsidian"
    assert body["device_locality"] == "local"
    assert body["enabled"] is True


def test_response_contains_exactly_the_launch_target_contract_fields(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _write_obsidian_config(tmp_path, monkeypatch)

    body = _client(LOOPBACK_PEER).get(LAUNCH_TARGET_PATH).json()

    assert sorted(body) == [
        "device_locality",
        "disabled_reason",
        "enabled",
        "href",
        "label",
        "provider",
    ]


def test_forwarding_headers_claiming_loopback_are_ignored_for_a_non_loopback_peer(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _write_obsidian_config(tmp_path, monkeypatch)

    resp = _client(("203.0.113.9", 40412)).get(
        LAUNCH_TARGET_PATH,
        headers={
            "X-Forwarded-For": "127.0.0.1",
            "X-Real-IP": "127.0.0.1",
            "Forwarded": "for=127.0.0.1",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "obsidian"
    assert body["device_locality"] == "remote"
    assert body["enabled"] is False
    assert body["href"] is None


INVALID_DESTINATION = "https://evil.example.com/secret-workspace/project-42"


def test_invalid_destination_with_recognized_provider_falls_back_to_generic_xtiles(
    tmp_path: Path, monkeypatch: MonkeyPatch, caplog: LogCaptureFixture
) -> None:
    _write_config(
        tmp_path,
        monkeypatch,
        f"second_brain:\n  provider: xtiles\n  xtiles_destination_url: {INVALID_DESTINATION}\n",
    )

    with caplog.at_level("DEBUG"):
        resp = _client(LOOPBACK_PEER).get(LAUNCH_TARGET_PATH)

    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "xtiles"
    assert body["label"] == "xTiles"
    assert body["enabled"] is False
    assert body["href"] is None
    assert body["disabled_reason"] == "Second Brain configuration is invalid."
    assert INVALID_DESTINATION not in resp.text
    assert INVALID_DESTINATION not in caplog.text


def test_unrecognized_provider_falls_back_to_a_generic_none_target(
    tmp_path: Path, monkeypatch: MonkeyPatch, caplog: LogCaptureFixture
) -> None:
    _write_config(tmp_path, monkeypatch, "second_brain:\n  provider: notion-secret-plan\n")

    with caplog.at_level("DEBUG"):
        resp = _client(LOOPBACK_PEER).get(LAUNCH_TARGET_PATH)

    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "none"
    assert body["label"] == "Second Brain"
    assert body["device_locality"] == "unknown"
    assert body["enabled"] is False
    assert body["href"] is None
    assert body["disabled_reason"] == "Second Brain configuration is invalid."
    assert "notion-secret-plan" not in resp.text
    assert "notion-secret-plan" not in caplog.text


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_mutation_methods_are_not_accepted_and_change_nothing(
    tmp_path: Path, monkeypatch: MonkeyPatch, method: str
) -> None:
    _write_obsidian_config(tmp_path, monkeypatch)
    config_path = tmp_path / "config.yaml"
    before = config_path.read_text()

    resp = _client(LOOPBACK_PEER).request(
        method,
        LAUNCH_TARGET_PATH,
        json={"provider": "xtiles", "xtiles_destination_url": "https://xtiles.app/x"},
    )

    assert resp.status_code in {404, 405}
    assert config_path.read_text() == before


@pytest.mark.parametrize(
    ("peer_host", "locality"),
    [
        pytest.param(None, "unknown", id="missing-peer"),
        pytest.param("127.0.0.1", "local", id="ipv4-loopback"),
        pytest.param("::1", "local", id="ipv6-loopback"),
        pytest.param("192.0.2.7", "remote", id="ipv4-non-loopback"),
        pytest.param("testclient", "remote", id="non-ip-peer"),
    ],
)
def test_device_locality_derives_only_from_the_direct_peer(
    peer_host: str | None, locality: str
) -> None:
    from studyloop.web.routes.second_brain import _device_locality

    assert _device_locality(peer_host) == locality


def test_route_is_registered_before_the_static_mount_and_is_get_only() -> None:
    from starlette.routing import Mount, Route

    app = create_app(study_dirs=[])
    route_index = next(
        i for i, r in enumerate(app.routes) if isinstance(r, Route) and r.path == LAUNCH_TARGET_PATH
    )
    static_mount_index = next(
        i for i, r in enumerate(app.routes) if isinstance(r, Mount) and r.path == ""
    )
    assert route_index < static_mount_index

    route = app.routes[route_index]
    assert isinstance(route, Route)
    assert route.methods is not None
    assert route.methods <= {"GET", "HEAD"}


def test_route_module_imports_no_launch_subprocess_redirect_or_network_dependency() -> None:
    """Design boundary, pinned statically: the route serializes resolver state
    and nothing else. An allowlist, not a denylist, so a server-side desktop
    launch, redirect, subprocess path, or direct xTiles network client is a
    decision rather than a drift.
    """
    import ast
    import inspect

    from studyloop.web.routes import second_brain

    allowed = {
        "__future__",
        "dataclasses",
        "ipaddress",
        "fastapi",
        "fastapi.responses",
        "studyloop.second_brain.launch",
        "studyloop.settings",
    }
    source = Path(inspect.getsourcefile(second_brain) or "")
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    offenders: list[str] = []
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders.extend(
                f"line {node.lineno}: import {alias.name}"
                for alias in node.names
                if alias.name not in allowed
            )
        elif isinstance(node, ast.ImportFrom):
            if node.module not in allowed:
                offenders.append(f"line {node.lineno}: from {node.module} import ...")
            imported_names.update(alias.name for alias in node.names)
    assert offenders == [], "launch route grew a dependency outside its boundary:\n" + "\n".join(
        offenders
    )
    assert "RedirectResponse" not in imported_names


def test_fallback_recognizes_the_raw_provider_the_way_the_resolver_does(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``resolve_second_brain`` recognizes a provider after strip+lower; the
    generic fallback must not be stricter, or ``provider: XTILES`` with an
    invalid destination would lose its label."""
    _write_config(
        tmp_path,
        monkeypatch,
        f"second_brain:\n  provider: 'XTILES '\n  xtiles_destination_url: {INVALID_DESTINATION}\n",
    )

    body = _client(LOOPBACK_PEER).get(LAUNCH_TARGET_PATH).json()

    assert body["provider"] == "xtiles"
    assert body["label"] == "xTiles"
    assert body["disabled_reason"] == "Second Brain configuration is invalid."


def test_unparseable_config_file_falls_back_to_a_generic_none_target(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _write_config(tmp_path, monkeypatch, "second_brain: [unclosed\n")

    resp = _client(LOOPBACK_PEER).get(LAUNCH_TARGET_PATH)

    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "none"
    assert body["label"] == "Second Brain"
    assert body["enabled"] is False
    assert body["disabled_reason"] == "Second Brain configuration is invalid."
    assert resp.headers["cache-control"] == "no-store"
