"""Static assets are revalidated on every load, like the page that uses them.

Found 2026-09-28 while checking a header fix in a browser: after the CSS on
disk changed, a reload still drew the old header. ``/`` is served with
``no-cache, no-store, must-revalidate``, but the static mount behind it sent
``style.css``, ``components.js`` and every ``js/`` module with only an ETag and
Last-Modified. With no Cache-Control a browser applies heuristic freshness,
commonly a tenth of the file's age, so a stylesheet unchanged for three weeks is
reused for about two days without asking the server. After ``git pull`` the
learner gets the new index.html beside the old CSS and JS: a fix that looks as
if it never landed, or markup the old script does not understand.

``no-cache`` does not mean "do not cache": the browser keeps its copy and asks
first, and an unchanged file costs a 304.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")


def _client():
    from fastapi.testclient import TestClient

    from studyloop.web.app import create_app

    return TestClient(create_app())


@pytest.mark.parametrize(
    "path",
    [
        "/style.css",
        "/components.js",
        "/js/retrieval-chip.js",
        "/js/components/live-agent-console.js",
    ],
)
def test_static_assets_are_revalidated_before_reuse(path: str) -> None:
    response = _client().get(path)
    assert response.status_code == 200, f"{path} -> {response.status_code}"
    directives = {
        part.strip().lower() for part in response.headers.get("cache-control", "").split(",")
    }
    assert "no-cache" in directives, (
        f"{path} carries no Cache-Control: no-cache "
        f"(got {response.headers.get('cache-control')!r}), so a browser may reuse a "
        "stale copy after an update without asking the server"
    )


def test_an_unchanged_asset_still_costs_only_a_304() -> None:
    client = _client()
    first = client.get("/style.css")
    etag = first.headers.get("etag")
    assert etag, "revalidation needs a validator"
    again = client.get("/style.css", headers={"If-None-Match": etag})
    assert again.status_code == 304
