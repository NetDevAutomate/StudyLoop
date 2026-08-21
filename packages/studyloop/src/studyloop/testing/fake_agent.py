"""studyloop-fake-agent — deterministic stand-in agent for e2e harness runs.

A real console script (so ``shutil.which`` finds it like any agent binary)
that speaks just enough "agent" to exercise the spawn → PTY → WebSocket →
terminal path without an LLM:

- prints a recognisable banner (``FAKE-AGENT READY``) on startup
- reads the study topic from the persona file passed as argv[1] and
  announces it (``FAKE-AGENT TOPIC: <topic>``)
- asks the topic's Socratic question bank (``studyloop.testing.socratic_bank``)
  one question at a time, grades each answer, and reveals the canonical
  answer only after an attempt is accepted — never before
- exits cleanly on EOF or SIGTERM so session teardown is exercised

It is registered as the ``fake`` adapter ONLY when ``STUDYLOOP_TEST_AGENT=1``
(see ``adapters/fake.py``), so it never appears in a real user's picker.

Wire protocol (see ``tests/e2e/test_socratic_topic_qa.py`` for the assertions
that pin this down):

- ``FAKE-AGENT READY`` — startup banner.
- ``FAKE-AGENT TOPIC: <topic>`` — announced once, exact bank topic string.
- ``FAKE-AGENT ASKS: <question>`` — one per bank question, in order.
- ``FAKE-AGENT VERDICT: correct`` / ``FAKE-AGENT VERDICT: not-yet`` — grades
  the learner's most recent line against the current question.
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

from studyloop.testing.socratic_bank import TopicBank, bank_for_topic, topic_from_persona

BANNER = "FAKE-AGENT READY"
REPLY_PREFIX = "FAKE-AGENT SAYS:"


def _write(line: str) -> None:
    sys.stdout.write(line + "\r\n")
    sys.stdout.flush()


def _load_bank(persona_arg: str | None) -> TopicBank:
    """Resolve the Socratic question bank from the persona file's topic."""
    topic = ""
    if persona_arg:
        try:
            topic = topic_from_persona(Path(persona_arg).read_text(encoding="utf-8"))
        except OSError:
            topic = ""
    return bank_for_topic(topic)


def _run_socratic_session(bank: TopicBank) -> None:
    """Ask every question in *bank*, grading answers from stdin as they arrive."""
    _write(f"FAKE-AGENT TOPIC: {bank.topic}")

    correct_count = 0
    total = len(bank.questions)
    index = 0
    while index < total:
        question = bank.questions[index]
        _write(f"FAKE-AGENT ASKS: {question.question}")

        line = sys.stdin.readline()
        if not line:
            return  # EOF mid-session — nothing more to grade.
        text = line.strip()
        if not text:
            continue
        if text.lower() in {"exit", "quit"}:
            return

        if question.grade(text):
            _write("FAKE-AGENT VERDICT: correct")
            _write(f"FAKE-AGENT ANSWER: {question.correct_answer}")
            correct_count += 1
            index += 1
        else:
            _write("FAKE-AGENT VERDICT: not-yet")
            _write(f"FAKE-AGENT HINT: {question.hint}")

    _write(f"FAKE-AGENT DONE: {correct_count}/{total} concepts confirmed")


def main() -> int:
    """Run the Socratic session. Deterministic, line-buffered, TTY-safe."""
    # Under pty.fork() stdout is a tty and line-buffering applies, but be
    # explicit: every write is flushed so tests never race the buffer.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    persona_arg = sys.argv[1] if len(sys.argv) > 1 else None
    bank = _load_bank(persona_arg)

    _write(BANNER)

    try:
        _run_socratic_session(bank)
    except (KeyboardInterrupt, BrokenPipeError):
        pass

    _write("FAKE-AGENT BYE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
