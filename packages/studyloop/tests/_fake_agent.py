"""Deterministic child process used only by StudyLoop source tests.

A real console script (so ``shutil.which`` finds it like any agent binary)
that speaks just enough "agent" to exercise the spawn → PTY → WebSocket →
terminal path without an LLM:

- prints a recognisable banner (``FAKE-AGENT READY``) on startup
- reads the study topic from the persona file passed as argv[1] and
  announces it (``FAKE-AGENT TOPIC: <topic>``)
- asks the test suite's Socratic question bank (``_socratic_bank``)
  one question at a time, grades each answer, and reveals the canonical
  answer only after an attempt is accepted — never before
- exits cleanly on EOF or SIGTERM so session teardown is exercised

It is launched only through the test suite's explicit child-command injection
and is excluded from built wheels, so it never appears in a user's picker.

Wire protocol (see ``tests/e2e/test_socratic_topic_qa.py`` for the assertions
that pin this down):

- ``FAKE-AGENT READY`` — startup banner.
- ``FAKE-AGENT TOPIC: <topic>`` — announced once, exact bank topic string.
- ``FAKE-AGENT ASKS: <question>`` — one per bank question, in order.
- ``FAKE-AGENT VERDICT: correct`` / ``FAKE-AGENT VERDICT: not-yet`` — grades
  the learner's most recent line against the current question.
- ``FAKE-AGENT NOTED: practice_check result received`` — a line carrying
  StudyLoop's own ``practice_check`` delivery (the ``<<<studyloop:practice_check``
  sentinel, ``session/module_delivery.py``) is a result the product posted
  into the session, not the learner's answer: it is acknowledged and never
  graded, so the question stays open and the session stays alive.
- ``FAKE-AGENT HINT: <hint>`` — follow-up on a ``not-yet`` verdict; the
  question is NOT re-asked and the answer is NOT revealed, so the learner
  gets another attempt at the same question.
- ``FAKE-AGENT ANSWER: <correct_answer>`` — revealed only after a ``correct``
  verdict for that question, then the next question (or DONE) follows.
- ``FAKE-AGENT DONE: <n>/<n> concepts confirmed`` — printed once every bank
  question has been answered correctly.
"""

from __future__ import annotations

import signal
import sys
from pathlib import Path

from _socratic_bank import TopicBank, bank_for_topic, topic_from_persona

BANNER = "FAKE-AGENT READY"
REPLY_PREFIX = "FAKE-AGENT SAYS:"
# studyloop.session.module_delivery.BEGIN_SENTINEL, spelled out so this script
# keeps importing nothing from the product (test_fake_agent.py pins the two
# equal). A delivered block travels as one printable line in the M0 Q3 fallback,
# so the sentinel is looked for anywhere in the line, not at its start.
PRACTICE_CHECK_SENTINEL = "<<<studyloop:practice_check"
NOTED = "FAKE-AGENT NOTED: practice_check result received"


def _is_practice_check(text: str) -> bool:
    """A delivered practice_check result -- data to acknowledge, not an answer to grade.

    Found 2026-10-12 by the Labs journey: the one-question generic bank graded the
    block's words as a correct answer, printed DONE and exited, and the session the
    journey still needed (its replay check reads the live state file) was gone.
    """
    return PRACTICE_CHECK_SENTINEL in text


def _write(line: str) -> None:
    sys.stdout.write(line + "\r\n")
    sys.stdout.flush()


def _load_bank(persona_arg: str | None) -> TopicBank | None:
    """Resolve the Socratic question bank from the persona file's topic.

    Returns ``None`` when no topic could be resolved -- no persona argument, an
    unreadable path, or a briefing naming a topic the bank does not cover. The
    agent then falls back to echo mode.

    That distinction matters: the plumbing tests invoke this binary with no
    argument at all or with a
    deliberately absent path, because all they prove is that bytes flow both
    ways through the PTY. Defaulting an unbriefed agent into a full Socratic
    session made it teach a topic nobody asked about, and broke those tests.
    """
    if not persona_arg:
        return None
    try:
        persona = Path(persona_arg).read_text(encoding="utf-8")
    except OSError:
        return None
    topic = topic_from_persona(persona)
    if not topic:
        return None
    return bank_for_topic(topic)


def _run_echo_session() -> None:
    """Echo each stdin line back as a canned mentor-ish reply.

    The unbriefed mode: no topic, so no question bank to teach from. Proves the
    spawn -> PTY -> WebSocket -> terminal path carries bytes in both directions.
    """
    try:
        for line in sys.stdin:
            text = line.strip()
            if not text:
                continue
            if text.lower() in {"exit", "quit"}:
                break
            if _is_practice_check(text):
                _write(NOTED)
                continue
            _write(f"{REPLY_PREFIX} I hear you on {text!r} — tell me more.")
    except (KeyboardInterrupt, BrokenPipeError):
        pass


def _run_socratic_session(bank: TopicBank) -> None:
    """Ask every question in *bank*, grading answers from stdin as they arrive."""
    _write(f"FAKE-AGENT TOPIC: {bank.topic}")

    correct_count = 0
    total = len(bank.questions)
    index = 0
    while index < total:
        question = bank.questions[index]
        # Announced ONCE per question, not once per attempt: the inner loop
        # below takes further attempts after a hint. Re-announcing made the
        # learner see the same question twice and inflated the question count.
        _write(f"FAKE-AGENT ASKS: {question.question}")

        while True:
            line = sys.stdin.readline()
            if not line:
                return  # EOF mid-session — nothing more to grade.
            text = line.strip()
            if not text:
                continue
            if text.lower() in {"exit", "quit"}:
                return
            if _is_practice_check(text):
                _write(NOTED)
                continue

            if question.grade(text):
                _write("FAKE-AGENT VERDICT: correct")
                _write(f"FAKE-AGENT ANSWER: {question.correct_answer}")
                correct_count += 1
                index += 1
                break

            # Not yet: hint and let them try again at the SAME question. The
            # canonical answer is deliberately withheld -- revealing it here
            # would short-circuit the productive struggle the bank exists for.
            _write("FAKE-AGENT VERDICT: not-yet")
            _write(f"FAKE-AGENT HINT: {question.hint}")

    _write(f"FAKE-AGENT DONE: {correct_count}/{total} concepts confirmed")


def main() -> int:
    """Run a Socratic session when briefed, otherwise echo. TTY-safe."""
    # Under pty.fork() stdout is a tty and line-buffering applies, but be
    # explicit: every write is flushed so tests never race the buffer.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    persona_arg = sys.argv[1] if len(sys.argv) > 1 else None
    bank = _load_bank(persona_arg)

    _write(BANNER)

    try:
        if bank is None:
            _run_echo_session()
        else:
            _run_socratic_session(bank)
    except (KeyboardInterrupt, BrokenPipeError):
        pass

    _write("FAKE-AGENT BYE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
