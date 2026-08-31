"""Topic-relevant Socratic Q&A — the agent asks about what the learner studies.

WHAT THIS PROVES
----------------
Two properties the goal calls for, both machine-checked rather than eyeballed:

1. **Relevance** — every question the mentor asks contains vocabulary from the
   topic under study (``Python Decorators`` → decorator/wrapper/functools/…).
   A generic "tell me more" transcript fails.
2. **Correct answers exist and are recognised** — a right answer is graded
   ``correct`` and the canonical answer is revealed; a wrong answer is graded
   ``not-yet`` and gets a hint instead. The accept/reject boundary is asserted
   in both directions, so a grader that always says "correct" fails too.

The transcript is produced by the real product path: the web app spawns the
agent over a PTY, bytes travel the real session WebSocket, and the learner's
answers are typed the way the UI types them. The question bank is shared with
the test agent (``_socratic_bank``) so the assertions cannot drift
from what the agent actually says.

The same properties against a **live LLM mentor** are covered by
``test_socratic_steering.py`` (``live_provider``, judged by a second model).
This module is its deterministic counterpart: it runs in every e2e sweep with
no credentials, so Socratic behaviour is never untested.

Run:  cd packages/studyloop && uv run pytest tests/e2e/test_socratic_topic_qa.py -m e2e
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("websockets")

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from e2e._env import (  # noqa: E402
    STUDY_TOPIC,
    ConsoleWatch,
    diag,
    launch_env,
    shutdown,
)

if TYPE_CHECKING:
    from playwright.sync_api import Browser

pytestmark = [pytest.mark.e2e]

PORT = 18603
BROWSER_PORT = 18604

# Answers a learner who understands the material would give. Each maps to the
# matching question in the bank; they are written as prose (not keyword soup)
# so grading is exercised on realistic input.
GOOD_ANSWERS = [
    "python calls timed with the function and rebinds the name to the wrapper it returns",
    "the wrapper shadows the metadata so __name__ is wrong unless functools wraps copies it",
    "the wrapper keeps a closure over the enclosing scope so it still reaches func",
]

# A plausible-but-wrong answer: on topic in vocabulary, wrong in substance.
WRONG_ANSWER = "i think you just put an at sign there and python compiles it away"


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("socratic-qa")
    e = launch_env(root, PORT, fake_agent=True)
    try:
        yield e
    finally:
        try:
            import requests

            requests.post(f"{e.base_url}/api/session/end", timeout=10)
        except Exception:  # pragma: no cover
            pass
        shutdown(e)


class Transcript:
    """Accumulated PTY bytes, parsed into the agent's marker lines."""

    def __init__(self) -> None:
        self.raw = b""

    def feed(self, chunk: bytes) -> None:
        self.raw += chunk

    @property
    def text(self) -> str:
        return self.raw.decode("utf-8", errors="replace")

    def lines_with(self, prefix: str) -> list[str]:
        out = []
        for line in self.text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            idx = line.find(prefix)
            if idx != -1:
                out.append(line[idx + len(prefix) :].strip())
        return out

    def has(self, needle: str) -> bool:
        return needle in self.text


def _read_until(ws, transcript: Transcript, needle: str, *, frames: int = 60) -> bool:
    """Pump WS frames into *transcript* until *needle* appears."""
    for _ in range(frames):
        if transcript.has(needle):
            return True
        try:
            msg = ws.recv(timeout=10)
        except TimeoutError:  # pragma: no cover - surfaced by the caller's assert
            break
        if isinstance(msg, bytes):
            transcript.feed(msg)
        elif isinstance(msg, str):
            transcript.feed(msg.encode())
    return transcript.has(needle)


def test_mentor_asks_topic_relevant_questions_and_grades_answers(env) -> None:
    """Full Socratic exchange over the real session WebSocket.

    Sequence: start a session on the study topic → read the mentor's opening
    question → answer it wrongly (assert rejection + hint) → answer correctly
    (assert acceptance + canonical answer) → work through the remaining
    questions → assert every question was on-topic and the session completed.
    """
    import requests
    from _socratic_bank import bank_for_topic
    from websockets.sync.client import connect as ws_connect

    bank = bank_for_topic(STUDY_TOPIC)
    assert bank.questions, f"no question bank for {STUDY_TOPIC!r} — nothing to teach"

    resp = requests.post(
        f"{env.base_url}/api/session/start",
        json={"topic": STUDY_TOPIC, "energy": 6, "agent": "codex", "transport": "pty"},
        timeout=25,
    )
    body = resp.json()
    assert resp.status_code == 201, f"session start failed: {body}"
    ws_url = f"ws://127.0.0.1:{env.port}{body['ws_url']}"

    t = Transcript()
    with ws_connect(ws_url, open_timeout=15, additional_headers={"Origin": env.base_url}) as ws:
        assert _read_until(ws, t, "FAKE-AGENT READY"), f"no banner; got {t.text[:400]!r}"

        # --- The mentor picked up the topic from its persona briefing ---
        topics = t.lines_with("FAKE-AGENT TOPIC:")
        assert _read_until(ws, t, "FAKE-AGENT TOPIC:"), "mentor never announced a topic"
        topics = t.lines_with("FAKE-AGENT TOPIC:")
        assert topics and topics[0].lower() == STUDY_TOPIC.lower(), (
            f"mentor is teaching {topics!r}, not the requested {STUDY_TOPIC!r} — the "
            "persona briefing did not reach the agent"
        )

        # --- It opens with a question, not an answer ---
        assert _read_until(ws, t, "FAKE-AGENT ASKS:"), "mentor did not ask an opening question"
        first_q = t.lines_with("FAKE-AGENT ASKS:")[0]
        assert first_q.endswith("?"), f"opening turn is not a question: {first_q!r}"

        # --- A wrong answer is rejected and hinted, not accepted ---
        ws.send(json.dumps({"type": "input", "data": WRONG_ANSWER + "\r"}))
        assert _read_until(ws, t, "FAKE-AGENT VERDICT:"), "no verdict for the wrong answer"
        verdicts = t.lines_with("FAKE-AGENT VERDICT:")
        assert verdicts[0] == "not-yet", (
            f"a wrong answer was graded {verdicts[0]!r} — the grader accepts anything"
        )
        assert _read_until(ws, t, "FAKE-AGENT HINT:"), "no hint after a wrong answer"
        assert not t.lines_with("FAKE-AGENT ANSWER:"), (
            "the mentor revealed the answer before the learner had a real attempt — "
            "that breaks the productive-struggle contract"
        )

        # --- Correct answers are accepted and the canonical answer revealed ---
        for answer in GOOD_ANSWERS[: len(bank.questions)]:
            ws.send(json.dumps({"type": "input", "data": answer + "\r"}))
            want = len([v for v in t.lines_with("FAKE-AGENT VERDICT:") if v == "correct"]) + 1
            assert _read_until(
                ws,
                t,
                "FAKE-AGENT DONE:"
                if want == len(bank.questions)
                else f"FAKE-AGENT ASKS: {bank.questions[want].question[:24]}",
            ), f"answer {answer!r} did not advance the session; transcript tail:\n{t.text[-600:]!r}"

        # --- Every question was about the topic under study ---
        asked = t.lines_with("FAKE-AGENT ASKS:")
        assert len(asked) == len(bank.questions), (
            f"expected {len(bank.questions)} questions, saw {len(asked)}: {asked}"
        )
        vocab = bank.concept_vocabulary
        for q in asked:
            low = q.lower()
            assert any(word in low for word in vocab), (
                f"question is not relevant to {bank.topic!r} (no vocabulary from {vocab}): {q!r}"
            )
            assert "?" in q, f"'question' has no question mark: {q!r}"

        # --- Canonical answers were revealed after each attempt ---
        answers = t.lines_with("FAKE-AGENT ANSWER:")
        assert len(answers) == len(bank.questions), (
            f"expected a canonical answer per question, got {len(answers)}: {answers}"
        )
        expected = [q.correct_answer for q in bank.questions]
        assert answers == expected, (
            "the answers the mentor revealed do not match the topic's correct "
            f"answers.\n  got:      {answers}\n  expected: {expected}"
        )

        # --- The session reports the concepts confirmed ---
        done = t.lines_with("FAKE-AGENT DONE:")
        assert done, f"session never completed; tail: {t.text[-400:]!r}"
        assert done[0].startswith(f"{len(bank.questions)}/{len(bank.questions)}"), (
            f"not all concepts confirmed: {done[0]!r}"
        )

        end = requests.post(f"{env.base_url}/api/session/end", timeout=15)
        assert end.status_code == 200, end.text


def test_grading_boundary_is_asserted_both_ways() -> None:
    """The bank's grader accepts understanding and rejects the plausible-wrong.

    Unit-level counterpart to the transcript assertions: without this, a
    grader that returns True for everything would still satisfy the journey.
    """
    from _socratic_bank import bank_for_topic

    bank = bank_for_topic(STUDY_TOPIC)
    for question, good in zip(bank.questions, GOOD_ANSWERS, strict=False):
        assert question.grade(good), f"correct answer rejected: {good!r} for {question.question!r}"
        assert not question.grade(WRONG_ANSWER), f"wrong answer accepted for {question.question!r}"
        assert not question.grade("yes"), "an empty-content answer was accepted"


def test_every_bank_question_is_socratic_and_on_topic() -> None:
    """Static contract for the whole bank: questions ask, and stay on topic.

    Guards the extension path — a new topic bank added without a question
    mark, without topic vocabulary, or with a keyword set its own canonical
    answer fails, breaks here rather than in a confusing journey timeout.
    """
    from _socratic_bank import BANKS

    for bank in BANKS:
        assert bank.questions, f"bank {bank.topic!r} has no questions"
        assert bank.concept_vocabulary, f"bank {bank.topic!r} has no concept vocabulary"
        for q in bank.questions:
            assert q.question.rstrip().endswith("?"), (
                f"{bank.topic}: not a question: {q.question!r}"
            )
            low = q.question.lower()
            assert any(w in low for w in bank.concept_vocabulary), (
                f"{bank.topic}: question has no topic vocabulary: {q.question!r}"
            )
            assert q.correct_answer.strip(), f"{bank.topic}: question has no correct answer"
            assert q.grade(q.correct_answer), (
                f"{bank.topic}: the canonical answer would be graded wrong — the "
                f"keyword set and the answer disagree: {q.question!r}"
            )
            assert q.hint.strip(), f"{bank.topic}: question has no hint"


def test_learner_answers_questions_in_the_browser_terminal(browser: Browser, env) -> None:
    """The same exchange, driven through the UI the learner actually uses.

    Starts the session from the Study Session picker, types an answer into the
    xterm terminal, and asserts the mentor's graded reply reaches xterm's
    buffer — proving the Q&A loop works keyboard-to-glyph, not just over a
    raw socket.
    """
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    watch = ConsoleWatch(page)
    read_buffer = """() => {
        const mount = document.querySelector('.xterm-mount');
        if (!mount || !window.Alpine || !window.Alpine.$data) return '';
        const t = window.Alpine.$data(mount)._term;
        if (!t || !t.buffer) return '';
        const b = t.buffer.active;
        let s = '';
        for (let i = 0; i < b.length; i++) {
            const line = b.getLine(i);
            if (line) s += line.translateToString(true) + '\\n';
        }
        return s;
    }"""
    try:
        page.route(
            "**/api/backlog",
            lambda route: route.fulfill(
                json={
                    "active": [],
                    "parking_lot": [],
                    "active_count": 0,
                    "parking_lot_count": 0,
                    "max_active": 3,
                }
            ),
        )
        page.goto(f"{env.base_url}/#study-session")
        page.wait_for_function("() => !!window.Alpine", timeout=15000)
        page.locator("#topic-input").fill(STUDY_TOPIC)
        page.wait_for_function(
            """() => {
                const s = document.querySelector('#agent-select');
                return s && [...s.options].some(o => o.value === 'codex');
            }""",
            timeout=40000,
        )
        page.select_option("#agent-select", value="codex")
        page.wait_for_function(
            "() => !document.querySelector('.study-start-picker .start-session-btn').disabled",
            timeout=10000,
        )
        page.locator(".study-start-picker .start-session-btn").click()

        # The mentor's opening question is painted in the terminal.
        page.wait_for_function(
            f"() => ({read_buffer})().includes('FAKE-AGENT ASKS:')", timeout=30000
        )

        # Type a correct answer the way a learner does — into the terminal.
        page.locator(".xterm-mount").click()
        page.keyboard.type(GOOD_ANSWERS[0])
        page.keyboard.press("Enter")

        page.wait_for_function(
            f"() => ({read_buffer})().includes('FAKE-AGENT VERDICT: correct')", timeout=30000
        )
        buf = page.evaluate(read_buffer)
        assert "FAKE-AGENT ANSWER:" in buf, (
            f"no canonical answer after a correct reply; buffer tail:\n{buf[-800:]}"
        )
        # Relevance, asserted on what the user can actually see on screen.
        assert "decorator" in buf.lower() or "wrapper" in buf.lower(), (
            f"nothing topic-relevant visible in the terminal:\n{buf[-800:]}"
        )
        watch.assert_clean("answering questions in the browser terminal")
    except Exception:
        diag(page, "socratic-browser-qa", watch)
        raise
    finally:
        try:
            import requests

            requests.post(f"{env.base_url}/api/session/end", timeout=10)
        except Exception:  # pragma: no cover
            pass
        ctx.close()
