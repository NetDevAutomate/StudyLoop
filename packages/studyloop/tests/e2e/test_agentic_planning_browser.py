"""Fresh setup -> real browser -> confined planning gateway vertical journey."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright")

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from e2e._env import build_test_world, start_server  # noqa: E402

pytestmark = [pytest.mark.e2e]

WEB_PORT = 18634
GATEWAY_PORT = 18635
NOTICE = (
    "Planning text and proposals are stored locally for recovery and may remain "
    "after rejection or replacement. StudyLoop sends the bounded planning context "
    "to your configured model. This release provides no automatic expiry."
)
BRAIN_DUMP = (
    "I can follow Python examples but I cannot yet design a service confidently. "
    "I own ArjanCodes Software Design Mastery 1/3 | CORE DESIGNER, and it isn't "
    "completed study just because I collected the notes. I do not know what should "
    "come first. I need a small, practical path."
)


class _GatewayState:
    requests: list[dict]

    def __init__(self) -> None:
        self.requests = []


def _tool_chunk(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments, separators=(",", ":")),
                            },
                        }
                    ]
                },
                "finish_reason": "tool_calls",
            }
        ]
    }


def _text_chunks(text: str) -> list[dict]:
    return [
        {"choices": [{"delta": {"content": text}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ]


def _gateway_handler(state: _GatewayState):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _json(self, status: int, body: dict) -> None:
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            if self.path == "/v1/models":
                self._json(200, {"data": [{"id": "studyloop-browser-e2e"}]})
                return
            self._json(404, {"detail": "not found"})

        def do_POST(self) -> None:
            if self.path != "/v1/chat/completions":
                self._json(404, {"detail": "not found"})
                return
            size = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(size))
            state.requests.append(body)
            messages = body.get("messages", [])
            tools = [m for m in messages if m.get("role") == "tool"]
            called_tools = [
                call.get("function", {}).get("name", "")
                for message in messages
                if message.get("role") == "assistant"
                for call in message.get("tool_calls", [])
            ]
            prior_clarification = any(
                m.get("role") == "assistant"
                and "one useful outcome" in str(m.get("content", "")).casefold()
                for m in messages
            )

            if not tools and not prior_clarification:
                chunks = _text_chunks(
                    "What is one useful outcome you want to be able to demonstrate first?"
                )
            elif not tools:
                chunks = [_tool_chunk("prepare-browser", "prepare_plan", {})]
            else:
                result = json.loads(tools[-1]["content"])["payload"]
                if called_tools[-1] == "prepare_plan":
                    draft = {
                        "title": "Design one small Python service",
                        "mission": {
                            "why": "Move from following examples to making one defensible design",
                            "success": [
                                "Explain one service boundary and its trade-offs",
                                "Write one test before its implementation",
                            ],
                            "constraints": ["Keep at most three aligned goals"],
                            "out_of_scope": ["Finishing every owned course"],
                        },
                        "goals": [
                            {
                                "alias": "service-boundary",
                                "title": "Design one service boundary",
                                "reason": "A concrete service makes design choices observable",
                                "alignment_rationale": "It directly supports the requested outcome",
                            },
                            {
                                "alias": "test-first",
                                "title": "Prove behaviour test-first",
                                "reason": "Tests make the boundary executable",
                                "alignment_rationale": "It supports a defensible implementation",
                            },
                        ],
                        "milestones": [
                            {
                                "alias": "draw-boundary",
                                "goal_alias": "service-boundary",
                                "title": "Draw and explain the request boundary",
                            },
                            {
                                "alias": "first-test",
                                "goal_alias": "test-first",
                                "title": "Write one failing boundary test",
                            },
                        ],
                        "evidence_dispositions": [],
                        "resources": [
                            {
                                "label": "Deliberate citation",
                                "url": "https://citation.invalid/course",
                                "note": "Open only if useful",
                            }
                        ],
                        "unknowns": [
                            {
                                "unknown_id": "service-choice",
                                "question": "Which service should become the worked example?",
                                "impact": "Changes examples, not the learning sequence",
                            }
                        ],
                        "next_action": "Name the smallest request the service must handle",
                    }
                    chunks = [
                        _tool_chunk(
                            "proposal-browser",
                            "submit_plan_proposal",
                            {
                                "run_id": result["run_id"],
                                "brief_context_digest": result["brief_context_digest"],
                                "draft": draft,
                            },
                        )
                    ]
                elif called_tools[-1] == "submit_plan_proposal":
                    chunks = [
                        _tool_chunk(
                            "inspect-browser",
                            "get_plan_proposal",
                            {
                                "run_id": result["run_id"],
                                "proposal_id": result["proposal_id"],
                            },
                        )
                    ]
                else:
                    chunks = _text_chunks(
                        "Your proposal is ready. "
                        "![tracker](https://egress.invalid/pixel) "
                        '<img src="http://127.0.0.1:9/local"> '
                        '<video poster="http://169.254.169.254/latest/meta-data"></video> '
                        '<svg><image href="http://192.168.1.1/private"></image></svg>'
                    )

            payload = (
                b"".join(f"data: {json.dumps(chunk)}\n\n".encode() for chunk in chunks)
                + b"data: [DONE]\n\n"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return Handler


@pytest.fixture(scope="module")
def gateway():
    state = _GatewayState()
    server = ThreadingHTTPServer(("127.0.0.1", GATEWAY_PORT), _gateway_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.fixture(scope="module")
def configured_world(tmp_path_factory: pytest.TempPathFactory, gateway: _GatewayState):
    root = tmp_path_factory.mktemp("agentic-browser-world")
    empty_materials = root / "no-notes"
    empty_materials.mkdir()
    config = root / "fresh-config.yaml"
    world = build_test_world(
        root,
        WEB_PORT,
        vault_path=empty_materials,
        config_path=config,
    )
    setup = subprocess.run(
        [
            sys.executable,
            "-m",
            "studyloop.cli",
            "setup",
            "--planning-base-url",
            f"http://127.0.0.1:{GATEWAY_PORT}/v1",
            "--planning-model",
            "studyloop-browser-e2e",
        ],
        input="\n",
        text=True,
        capture_output=True,
        env=dict(world.env),
        cwd=world.cwd,
        timeout=30,
    )
    assert setup.returncode == 0, setup.stdout + setup.stderr
    assert "No notes folder set" in setup.stdout
    assert "No AI assistant found" in setup.stdout
    assert "Planning model ready" in setup.stdout
    assert "Create with Architect" in setup.stdout
    assert "Type or dictate one brain dump" in setup.stdout
    assert config.exists()
    return world


@pytest.fixture(scope="module")
def running_server(configured_world):
    server = start_server(configured_world)
    try:
        yield server
    finally:
        server.stop()


def _open_plans(page, base_url: str) -> None:
    page.goto(base_url)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_function("() => !!window.Alpine && !!window.Alpine.store('nav')")
    page.evaluate("() => window.Alpine.store('nav').go('study-plans')")


def _wait_proposal(page) -> None:
    try:
        page.locator('[data-testid="architect-proposal"]').wait_for(state="visible", timeout=20_000)
    except Exception as exc:
        diagnostic = page.evaluate(
            """async () => {
              const root = document.querySelector('[x-data="planArchitectPanel()"]');
              const data = root && window.Alpine.$data(root);
              let server = null;
              if (data?.conversationId) {
                const response = await fetch(
                  `/api/planning/conversations/${encodeURIComponent(data.conversationId)}`
                );
                server = {status: response.status, body: await response.json()};
              }
              return {
                client: data && {
                  phase: data.phase,
                  conversationId: data.conversationId,
                  lastSequence: data.lastSequence,
                  latestTurn: data.latestTurn,
                  error: data.error,
                  messageCount: data.messages.length,
                  hasProposal: !!data.proposal,
                },
                server,
              };
            }"""
        )
        raise AssertionError(f"proposal never became visible: {diagnostic!r}") from exc


def test_fresh_onboarding_create_approve_and_revise_in_real_browser(
    browser, running_server, gateway: _GatewayState
) -> None:
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    blocked: list[str] = []
    requested: list[str] = []
    context.on("request", lambda request: requested.append(request.url))
    context.route(
        "https://citation.invalid/**",
        lambda route: (blocked.append(route.request.url), route.abort()),
    )
    page = context.new_page()
    try:
        _open_plans(page, running_server.base_url)
        page.locator('[data-testid="plan-new"]').click()
        notice = page.locator('[data-testid="architect-privacy-notice"]')
        notice.wait_for(state="visible")
        assert NOTICE in notice.inner_text()
        assert "automatic deletion" not in notice.inner_text().casefold()

        page.locator('[data-testid="architect-brain-dump"]').fill(BRAIN_DUMP)
        page.locator('[data-testid="architect-start"]').click()
        conversation = page.locator('[data-testid="architect-conversation"]')
        conversation.wait_for(state="visible", timeout=10_000)
        page.wait_for_function(
            "() => document.querySelector('[data-testid=architect-conversation]')"
            "?.textContent.includes('one useful outcome')",
            timeout=15_000,
        )
        page.locator('[data-testid="architect-turn"]').fill(
            "I want to design and test one small HTTP service without copying a tutorial."
        )
        page.locator('[data-testid="architect-send"]').click()
        _wait_proposal(page)

        assert (
            "Design one small Python service"
            in page.locator('[data-testid="architect-proposal"]').inner_text()
        )
        assert NOTICE not in page.locator('[data-testid="architect-proposal"]').inner_text()
        assert not any("egress.invalid" in url for url in requested)
        assert not any("127.0.0.1:9/local" in url for url in requested)
        assert not any("169.254.169.254" in url for url in requested)
        assert not any("192.168.1.1/private" in url for url in requested)
        assert not any("citation.invalid" in url for url in requested)

        proposal_doc = page.locator('[data-testid="architect-proposal-markdown"]')
        proposal_doc.locator("svg").wait_for(state="visible", timeout=10_000)
        geometry = proposal_doc.locator("svg").evaluate(
            """svg => {
                const box = svg.getBoundingClientRect();
                const viewBox = svg.viewBox && svg.viewBox.baseVal;
                return {width: box.width, height: box.height,
                        vw: viewBox ? viewBox.width : 0, vh: viewBox ? viewBox.height : 0};
            }"""
        )
        assert geometry["width"] > 40 and geometry["height"] > 40, geometry
        assert geometry["vw"] > 40 and geometry["vh"] > 40, geometry
        assert page.locator('[data-testid="architect-mermaid-text"]').inner_text().strip()

        citation = proposal_doc.locator('a[href="https://citation.invalid/course"]')
        citation.click()
        deadline = time.monotonic() + 3
        while not blocked and time.monotonic() < deadline:
            page.wait_for_timeout(50)
        assert blocked == ["https://citation.invalid/course"]

        approve = page.locator('[data-testid="architect-approve"]')
        assert approve.is_enabled()
        with page.expect_response("**/api/planning/proposals/*/decision") as decision_info:
            approve.click()
        decision_response = decision_info.value
        assert decision_response.ok, decision_response.text()
        decision_body = decision_response.json()
        detail = page.locator('[data-testid="plan-detail"]')
        page.wait_for_timeout(1200)
        architect_state = page.locator('[x-data="planArchitectPanel()"]')
        state = architect_state.evaluate(
            "el => ({phase: el._x_dataStack?.[0]?.phase, error: el._x_dataStack?.[0]?.error, "
            "planId: el._x_dataStack?.[0]?.planId})"
        )
        assert not state["error"], state
        assert state["phase"] == "detail", {"state": state, "decision": decision_body}
        detail.wait_for(state="visible", timeout=15_000)
        assert "Design one small Python service" in detail.inner_text()
        plan_svg = detail.locator('[data-testid="plan-markdown"] svg')
        plan_svg.wait_for(state="visible", timeout=10_000)
        box = plan_svg.bounding_box()
        assert box and box["width"] > 40 and box["height"] > 40, box

        # Revise uses the same conversation runtime and repeats the disclosure.
        page.locator('[data-testid="architect-review-plan"]').click()
        notice.wait_for(state="visible")
        assert NOTICE in notice.inner_text()
        page.locator('[data-testid="architect-brain-dump"]').fill(
            "Keep the goals, but make the first milestone a smaller request trace."
        )
        page.locator('[data-testid="architect-start"]').click()
        page.wait_for_function(
            "() => document.querySelector('[data-testid=architect-conversation]')"
            "?.textContent.includes('one useful outcome')",
            timeout=15_000,
        )
        page.locator('[data-testid="architect-turn"]').fill(
            "A health-check request is small enough."
        )
        page.locator('[data-testid="architect-send"]').click()
        _wait_proposal(page)
        page.locator('[data-testid="architect-reject"]').click()
        page.get_by_text("Proposal rejected", exact=True).wait_for(state="visible")

        # Every gateway request uses the exact closed catalogue.
        expected = ["prepare_plan", "submit_plan_proposal", "get_plan_proposal"]
        tool_names = [
            item["function"]["name"]
            for request in gateway.requests
            for item in request.get("tools", [])
        ]
        assert tool_names
        assert all(
            tool_names[index : index + 3] == expected for index in range(0, len(tool_names), 3)
        )
    finally:
        context.close()


def test_planning_conversation_survives_full_page_reloads_without_duplicates(
    browser, running_server, gateway: _GatewayState
) -> None:
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    page = context.new_page()
    try:
        _open_plans(page, running_server.base_url)
        page.locator('[data-testid="plan-new"]').click()
        page.locator('[data-testid="architect-brain-dump"]').fill(BRAIN_DUMP)
        page.locator('[data-testid="architect-start"]').click()
        conversation = page.locator('[data-testid="architect-conversation"]')
        conversation.wait_for(state="visible", timeout=10_000)
        page.wait_for_function(
            "() => document.querySelector('[data-testid=architect-conversation]')"
            "?.textContent.includes('one useful outcome')",
            timeout=15_000,
        )

        requests_after_clarification = len(gateway.requests)
        page.reload(wait_until="domcontentloaded")
        conversation.wait_for(state="visible", timeout=10_000)
        assert conversation.locator(".architect-message-learner").count() == 1
        assert conversation.locator(".architect-message-assistant").count() == 1
        assert "one useful outcome" in conversation.inner_text().casefold()
        assert len(gateway.requests) == requests_after_clarification

        page.locator('[data-testid="architect-turn"]').fill(
            "I want to design and test one small HTTP service without copying a tutorial."
        )
        with page.expect_response("**/api/planning/conversations/*/turns") as turn_info:
            page.locator('[data-testid="architect-send"]').click()
        assert turn_info.value.ok
        page.reload(wait_until="domcontentloaded")
        _wait_proposal(page)
        root = page.locator('[x-data="planArchitectPanel()"]')
        messages_before_proposal_reload = root.evaluate(
            "el => el._x_dataStack[0].messages.map(({role, content, sequence}) => "
            "({role, content, sequence}))"
        )
        assert [item["role"] for item in messages_before_proposal_reload] == [
            "learner",
            "assistant",
            "learner",
            "assistant",
        ]
        assert sum(BRAIN_DUMP in item["content"] for item in messages_before_proposal_reload) == 1
        assert (
            sum(
                "one useful outcome" in item["content"].casefold()
                for item in messages_before_proposal_reload
            )
            == 1
        )

        requests_after_proposal = len(gateway.requests)
        page.reload(wait_until="domcontentloaded")
        _wait_proposal(page)
        messages_after_proposal_reload = root.evaluate(
            "el => el._x_dataStack[0].messages.map(({role, content, sequence}) => "
            "({role, content, sequence}))"
        )
        assert messages_after_proposal_reload == messages_before_proposal_reload
        assert len(gateway.requests) == requests_after_proposal
        proposal_doc = page.locator('[data-testid="architect-proposal-markdown"]')
        proposal_doc.locator("svg").wait_for(state="visible", timeout=10_000)
        assert page.locator('[data-testid="architect-approve"]').is_enabled()
        assert page.locator('[data-testid="architect-reject"]').is_enabled()

        page.locator('[data-testid="architect-reject"]').click()
        page.get_by_text("Proposal rejected", exact=True).wait_for(state="visible")
        page.reload(wait_until="domcontentloaded")
        page.wait_for_function("() => !!window.Alpine && !!window.Alpine.store('nav')")
        state = root.evaluate(
            "el => ({phase: el._x_dataStack?.[0]?.phase, "
            "conversationId: el._x_dataStack?.[0]?.conversationId})"
        )
        assert state == {"phase": "idle", "conversationId": ""}
    finally:
        context.close()


@pytest.mark.parametrize("viewport", [(834, 1112), (1024, 768)])
def test_planning_capture_is_readable_at_supported_tablet_sizes(
    browser, running_server, viewport
) -> None:
    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]})
    page = context.new_page()
    try:
        _open_plans(page, running_server.base_url)
        page.locator('[data-testid="plan-new"]').click()
        capture = page.locator('[data-testid="architect-capture"]')
        capture.wait_for(state="visible")
        notice = page.locator('[data-testid="architect-privacy-notice"]')
        box = notice.bounding_box()
        assert box and box["x"] >= 0 and box["x"] + box["width"] <= viewport[0]
        assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
        page.locator('[data-testid="architect-brain-dump"]').focus()
        assert page.evaluate(
            "() => document.activeElement?.dataset.testid === 'architect-brain-dump'"
        )
    finally:
        context.close()
