#!/usr/bin/env python3
"""Maintainer harness: drive the REAL plan agent to a finished plan, then judge it.

Why this is a script and not a pytest test
------------------------------------------
It calls a real LLM through a real coding harness, so it needs a paid
subscription, costs credits (~0.8 per turn on Kiro at time of writing), takes
minutes, and its output is non-deterministic by design. None of that belongs in
CI. It is a maintainer tool: run it with whichever harness you have access to.

It still *asserts*, and exits non-zero when an invariant fails, so it can be
wired into a release checklist. The assertions are deliberately
**model-independent** — they check properties any competent plan must have,
never the wording a particular model chose. The load-bearing one is
NO_VERBATIM_ECHO: no milestone may be a line copied out of the brain dump. That
is exactly what separates an agent that reasoned from a form that echoed, and
the web form as it stands today would fail it.

The run also writes a fixture (``--fixture``) so a deterministic CI test can
replay one real conversation's outcome without a subscription.

Usage
-----
    export PATH="$PWD/.venv/bin:$PATH"
    python scripts/plan_agent_harness.py                 # auto-detect harness
    python scripts/plan_agent_harness.py --harness kiro
    python scripts/plan_agent_harness.py --dry-run        # no LLM, print the script

Harness support
---------------
Binaries and detection come from ``studyloop.adapters`` so there is ONE source
of truth for "which binary is this harness". What the adapters do not provide is
non-interactive prompt passing — ``launch_cmd`` builds an interactive command —
so the argv shapes for "first turn" and "resume with this answer" live in
HARNESSES below. Add a harness there when its CLI grows a non-interactive form.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_NAME = "study-plan-architect"
ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")

# --------------------------------------------------------------------------
# Harness argv shapes. `{prompt}` is substituted as a single argv element, so
# quoting is never the caller's problem.
#
# `resume` must continue the SAME conversation — the agent has to remember the
# brain dump and the answers already given, or every turn restarts the
# interview and no plan is ever reached.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Harness:
    name: str
    binary: str
    first: list[str]
    resume: list[str]
    supports_agent_flag: bool = True
    note: str = ""


HARNESSES: dict[str, Harness] = {
    "kiro": Harness(
        name="kiro",
        binary="kiro-cli",
        first=["chat", "--agent", AGENT_NAME, "--trust-all-tools", "{prompt}"],
        resume=["chat", "--agent", AGENT_NAME, "--trust-all-tools", "--resume", "{prompt}"],
    ),
    "claude": Harness(
        name="claude",
        binary="claude",
        first=["-p", "{prompt}"],
        resume=["-p", "-c", "{prompt}"],
        supports_agent_flag=False,
        note="persona comes from the installed agent md; -c continues the session",
    ),
    "codex": Harness(
        name="codex",
        binary="codex",
        first=["exec", "{prompt}"],
        resume=["exec", "--resume", "{prompt}"],
        supports_agent_flag=False,
        note="codex reads AGENTS.md from the repo root",
    ),
    "gemini": Harness(
        name="gemini",
        binary="gemini",
        first=["-p", "{prompt}"],
        resume=["-p", "-r", "{prompt}"],
        supports_agent_flag=False,
    ),
}

# --------------------------------------------------------------------------
# Scripted learners.
#
# TWO personas, because the first one written for this harness was a bad test.
# `articulate` supplies four well-formed observable success criteria and even
# resolves the devops-vs-data-platform contradiction unprompted — nobody who
# needs a planning tool can do that. It handed the agent most of the
# decomposition and then scored the agent for not echoing it.
#
# `vague` is the real case and the default: the learner knows which COURSES they
# intend to do (people do know what they bought) but cannot say what competence
# looks like, cannot split the work, and does not know what a rabbit hole is yet.
# The unknown unknowns are the point. A plan has to come out of that, and where
# it cannot, the agent must ask rather than invent.
#
# KNOWN LIMITATION, stated rather than hidden: a scripted learner cannot be
# surprised, so it cannot engage with a question the script did not anticipate.
# `vague` mitigates this by answering non-specifically and deferring, which is
# what a real beginner does to almost any question — but a genuinely novel
# clarifying question still gets a canned deferral rather than a real answer.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Persona:
    name: str
    brain_dump: str
    answers: list[str]
    #: Courses the learner explicitly named. Milestones should be grounded in
    #: these rather than in a curriculum the model invented.
    named_courses: tuple[str, ...]


ARTICULATE = Persona(
    name="articulate",
    brain_dump=(
        "I want to create a study plan. I understand programming concepts in general and "
        "I've done a little hands-on work, but I've never been taught software design "
        "properly. I'm working through the ArjanCodes path: Next-Level Python first, then "
        "Software Design Mastery 1/3 CORE DESIGNER, then 2/3 SYSTEM DESIGNER, and 3/3 "
        "MASTER DESIGNER once it's released. After those I want The Software Designer "
        "Mindset and Pythonic Patterns. I also own Domain Modeling Fundamentals and Design "
        "Wins and haven't decided where they fit. Alongside the courses I need agentic "
        "workflows with orchestration, knowledge graphs, ontology services, and Python "
        "testing/TDD. My course notes are in ~/Obsidian/Personal/Study/ArjanCodes. "
        "I don't know how to break this into steps yet."
    ),
    answers=[
        "I stop assembling scripts and start designing systems on purpose, so I can be "
        "handed a service end to end and be trusted with it. Concretely: I'm moving toward "
        "data platform work and agentic systems, not game dev or pure ops.",
        "1) I can justify a design decision out loud without hedging. 2) I can write a test "
        "before the code it covers and not delete it later. 3) I can model a domain and "
        "explain why the boundaries fall where they do. 4) I can build an agentic workflow "
        "with orchestration that recovers from a failed tool call.",
        "python, software-development. Not devops — my config says devops but that's stale, "
        "it should be data platform and agentic workflows.",
        "About 6 hours a week. Weekday evenings are low energy, so 45-minute blocks. "
        "Saturday mornings are my high-energy slot and can take 2 hours.",
        "Front-end work, Kubernetes, and anything to do with model training internals. "
        "Also not rewriting my existing scripts while I learn.",
        "I honestly don't know how to split it. Next-Level Python is the biggest course and "
        "the design mastery ones build on each other. Please work it out from the courses "
        "and the notes in my vault.",
        "No hard deadline. I'd like the first two courses done inside three months.",
        "The ArjanCodes courses themselves, and my own notes in "
        "~/Obsidian/Personal/Study/ArjanCodes. Prefer primary sources over blog posts.",
    ],
    named_courses=(
        "next-level python",
        "core designer",
        "system designer",
        "software designer mindset",
        "pythonic patterns",
        "domain modeling",
    ),
)

VAGUE = Persona(
    name="vague",
    brain_dump=(
        "I want to set up a study plan. I've bought a few Python courses and I want to get "
        "properly competent — good enough for data platform engineering and for building "
        "agentic workflows. I can write Python that works but I've never been taught it "
        "properly, I just pick things up as I need them. The courses I've got lined up are "
        "Next-Level Python, then the Software Design Mastery ones (there are three, the "
        "last isn't out yet), The Software Designer Mindset, and Pythonic Patterns. I "
        "haven't really started them. I'm not sure what order to do them in or how much of "
        "each I need. Honestly I don't know what good looks like here — I just know I'm not "
        "there yet."
    ),
    answers=[
        # why / mission — vague, aspirational, no observable change named
        "I'd stop feeling like I'm faking it. I want to be able to build data platform "
        "things and agent workflows properly instead of copying from tutorials and hoping. "
        "I don't really know what that looks like day to day though.",
        # success — the classic non-answer
        "That's the bit I can't answer. Be able to build things that work and understand "
        "why they work? I think I'd know it when I saw it. What should it look like?",
        # topics — doesn't know the vocabulary or what's configured
        "Python, definitely. Data engineering maybe? I don't know what topics you've got or "
        "what I'm supposed to pick.",
        # constraints — real but imprecise
        "Evenings mostly, when I've got the energy left. Some weekends. It varies a lot "
        "week to week, I can't promise a number.",
        # out of scope — cannot know yet
        "No idea. I don't know enough yet to know what counts as a rabbit hole.",
        # milestones — explicitly defers the decomposition
        "That's what I was hoping you'd work out. I don't know how to break it up — that's "
        "sort of the whole problem.",
        # target date
        "No real deadline. Soon-ish would be nice but nothing's riding on it.",
        # resources — the ONE concrete thing a real user reliably has
        "Just the courses I mentioned — Next-Level Python, the three Software Design "
        "Mastery ones, The Software Designer Mindset, Pythonic Patterns. Nothing else.",
    ],
    named_courses=(
        "next-level python",
        "software design mastery",
        "software designer mindset",
        "pythonic patterns",
    ),
)

PERSONAS: dict[str, Persona] = {"vague": VAGUE, "articulate": ARTICULATE}

#: Phrases the vague learner uses to decline a question. When the learner says
#: one of these, the agent must NOT simply move on — it should probe, or offer a
#: recommendation the learner can react to.
NON_ANSWER_MARKERS = (
    "i can't answer",
    "no idea",
    "i don't know",
    "hoping you'd",
    "what should it look like",
    "i'm not sure",
)

FOLLOW_UPS = [
    "That's right — go ahead.",
    "Yes, that matches. Please continue.",
    "Agreed. Carry on and create the plan when you have enough.",
]

UNRELEASED_MARKERS = ("MASTER DESIGNER", "3/3", "master designer", "isn't out yet")
SEED_SIGNALS = ("gil", "decorator pattern", "closures", "first-class")


@dataclass
class Result:
    harness: str
    persona: str = ""
    turns: int = 0
    seconds: float = 0.0
    plan_path: Path | None = None
    transcript: list[dict] = field(default_factory=list)
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, bool(ok), detail))

    @property
    def failed(self) -> list[tuple[str, bool, str]]:
        return [c for c in self.checks if not c[1]]


def strip_ansi(text: str) -> str:
    return ANSI.sub("", text)


#: Lines these CLIs print around the actual answer. Without stripping them the
#: captured tail is pure chrome — the exit banner alone filled a 500-char window
#: and made a "did the agent ask a question?" measurement silently vacuous.
CHROME = re.compile(
    r"To exit the CLI|▸ Credits:|Thinking\.\.\.|Try Lite Mode|Did you know\?"
    r"|All tools are now trusted|Agents can sometimes do|Learn more at"
    r"|^Model: |^\s*[─│╭╮╰╯═║╔╗╚╝┌┐└┘]|File URI not found|using tool:"
    r"|Completed in |Successfully |^\s*⠀|Run /|^\s*$"
)


def clean_agent_output(raw: str) -> str:
    """Return only the agent's substantive prose, with CLI chrome removed."""
    keep = [ln.rstrip() for ln in raw.splitlines() if ln.strip() and not CHROME.search(ln)]
    # Drop the giant ASCII logo: any line that is mostly non-alphanumeric.
    keep = [ln for ln in keep if sum(c.isalnum() or c.isspace() for c in ln) > len(ln) * 0.6]
    return "\n".join(keep)


def pick_harness(requested: str | None) -> Harness:
    if requested:
        h = HARNESSES.get(requested)
        if h is None:
            sys.exit(f"unknown harness {requested!r}; known: {', '.join(sorted(HARNESSES))}")
        if not shutil.which(h.binary):
            sys.exit(f"harness {requested!r} selected but {h.binary!r} is not on PATH")
        return h
    for name, h in HARNESSES.items():
        if shutil.which(h.binary):
            print(f"[harness] auto-detected {name} ({h.binary})")
            return h
    sys.exit(
        "no supported harness binary found on PATH. "
        f"Tried: {', '.join(h.binary for h in HARNESSES.values())}"
    )


def run_turn(h: Harness, prompt: str, *, resume: bool, cwd: Path, timeout: int) -> str:
    template = h.resume if resume else h.first
    argv = [h.binary] + [prompt if part == "{prompt}" else part for part in template]
    try:
        proc = subprocess.run(  # argv list, never shell=True
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            # stdin MUST be closed. These CLIs answer the prompt and then drop
            # into their interactive REPL; with an inherited tty (which is what
            # you get under tmux) that REPL never sees EOF and the turn hangs
            # until the timeout, having already done the work. DEVNULL gives it
            # the EOF that makes a one-shot turn actually terminate.
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return "<<TIMEOUT>>"
    return strip_ansi((proc.stdout or "") + (proc.stderr or ""))


def newest_plan(plans_dir: Path, since: float) -> Path | None:
    candidates = [
        p for p in plans_dir.glob("*.md") if p.is_file() and p.stat().st_mtime >= since - 1
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def parse_milestones(plan_text: str) -> list[str]:
    out: list[str] = []
    in_section = False
    for line in plan_text.splitlines():
        if line.strip().lower().startswith("## milestones"):
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section:
            m = re.match(r"\s*-\s*\[[ xX]\]\s*(.+)", line)
            if m:
                out.append(m.group(1).strip().strip("*").strip())
    return out


def live_seed_signals() -> list[str]:
    """Read the CURRENT struggle/due signals from sessions.db.

    A hardcoded list rots. The first version of this harness froze
    gil/decorator-pattern/closures, and by the next run the live seed was
    offering abc-vs-protocol instead - so the check reported a plan as ignoring
    evidence that no longer existed. Ask the database what it is actually
    handing the agent today.
    """
    try:
        sys.path.insert(0, str(REPO_ROOT / "packages" / "studyloop" / "src"))
        from studyloop.planning.authoring import seed_from_history

        seed = seed_from_history()
    except Exception:
        return []
    out: list[str] = []
    # configured_topics are what the plan is ABOUT, not evidence of struggle.
    # Counting them makes the check pass on the word "python" in a Python plan,
    # which is a false pass: it proved nothing about evidence being spent.
    generic = {str(t).strip().lower() for t in seed.get("configured_topics", [])}
    for row in seed.get("struggling_topics", []):
        topic = str(row.get("topic", "")).strip().lower()
        if topic not in generic:
            out.append(topic)
    for row in seed.get("due_concepts", []):
        for key in ("concept", "topic"):
            val = str(row.get(key, "")).strip().lower()
            # Skip extraction junk: single letters, paths, placeholders.
            if (
                len(val) > 3
                and "/" not in val
                and val not in {"quick topic", "x"}
                and val not in generic
            ):
                out.append(val)
    return sorted({s for s in out if s})


def judge(result: Result, plan_text: str, persona: Persona) -> None:
    """Model-independent invariants. Every one must hold for ANY good plan."""
    milestones = parse_milestones(plan_text)
    lower = plan_text.lower()

    result.check("PLAN_CREATED", result.plan_path is not None, str(result.plan_path or "none"))
    result.check(
        "FRONTMATTER",
        plan_text.startswith("---") and "title:" in plan_text[:400],
        "YAML frontmatter with a title",
    )
    required = ("## Mission", "## Milestones")
    missing = [h for h in required if h not in plan_text]
    result.check(
        "REQUIRED_SECTIONS", not missing, f"missing: {missing}" if missing else "all present"
    )

    result.check(
        "MILESTONE_COUNT_IN_RANGE",
        3 <= len(milestones) <= 6,
        f"{len(milestones)} milestones (protocol says 3-6)",
    )

    # A learner who cannot describe competence still knows which courses they
    # bought. If the plan cites none of them it invented a curriculum, which is
    # the failure mode the protocol's "never trust parametric knowledge" rule
    # exists to prevent — and the learner cannot act on a course they don't own.
    grounded = [c for c in persona.named_courses if c in lower]
    result.check(
        "GROUNDED_IN_NAMED_COURSES",
        bool(grounded),
        f"cites {len(grounded)}/{len(persona.named_courses)}: {grounded}"
        if grounded
        else "plan cites NONE of the courses the learner named",
    )

    # With a vague learner the agent is handed non-answers. It must ENGAGE with
    # them rather than silently invent the specifics and move on.
    #
    # An earlier version of this check looked for a question mark, which encoded
    # the wrong model of good behaviour and reported a false failure: this agent
    # engages by REFUSING the non-answer and proposing something to react to
    # ("that cannot be the completion test", "a fixed weekly hour target would be
    # dishonest here", "I recommend python + software-development"). That is what
    # StudyLoop's own persona rule asks for — one question per turn WITH a
    # recommended answer — and it is what the grilling model prescribes. So look
    # for engagement in either form: a question, or a reasoned push-back.
    engagement = re.compile(
        r"\?|cannot be|can't be|would be dishonest|not a deadline|i recommend"
        r"|provisional|draft |instead of|rather than|would be guesswork|not equal",
        re.IGNORECASE,
    )
    non_answers = [
        t
        for t in result.transcript
        if any(m in t.get("prompt", "").lower() for m in NON_ANSWER_MARKERS)
    ]
    engaged = [t for t in non_answers if engagement.search(t.get("tail") or "")]
    if non_answers:
        result.check(
            "AGENT_ENGAGED_NON_ANSWERS",
            len(engaged) >= max(1, len(non_answers) // 2),
            f"engaged {len(engaged)} of {len(non_answers)} non-answers "
            f"(question or reasoned push-back)",
        )

    # Every check below asserts a property OF THE MILESTONES. With no milestones
    # each one is trivially true, which would let an empty plan score well — the
    # vacuous green this harness exists to prevent. So they fail explicitly
    # instead, naming the reason.
    if not milestones:
        for name in (
            "CONCEPTS_ON_EVERY_MILESTONE",
            "NO_UNRELEASED_MILESTONE",
            "USES_SEED_EVIDENCE",
            "NO_VERBATIM_ECHO",
        ):
            result.check(name, False, "no milestones parsed — cannot hold vacuously")
        return

    # The protocol demands concepts on every milestone; without them nothing can
    # join to spaced repetition or the mastery graph.
    bare = [m for m in milestones if not re.search(r"[(\[].+[)\]]|:", m)]
    result.check(
        "CONCEPTS_ON_EVERY_MILESTONE",
        not bare,
        f"{len(bare)} milestone(s) name no concepts" if bare else "all name concepts",
    )

    # A tickable milestone for a course that does not exist is a broken promise.
    unreleased = [m for m in milestones if any(k in m for k in UNRELEASED_MARKERS)]
    result.check(
        "NO_UNRELEASED_MILESTONE",
        not unreleased,
        f"unreleased course is tickable: {unreleased}" if unreleased else "correctly excluded",
    )

    # Proves the sessions.db evidence was USED, not merely fetched.
    signals = live_seed_signals() or list(SEED_SIGNALS)
    hits = [sig for sig in signals if sig in lower]
    result.check(
        "USES_SEED_EVIDENCE",
        bool(hits),
        f"plan cites {hits}"
        if hits
        else f"none of {len(signals)} live signals reached the plan: {signals[:6]}",
    )

    # THE decisive check. A milestone lifted out of what the learner typed means
    # no decomposition happened — the agent transcribed instead of reasoning.
    #
    # Exact sentence equality is too weak: a real echo arrives as a PHRASE lifted
    # from the middle of a paragraph, or lightly reworded. So normalise both sides
    # (lowercase, strip punctuation, collapse whitespace) and ask whether the
    # milestone's own wording appears inside the learner's text. `_norm` keeps
    # word boundaries so "next level python" cannot match "next-level pythonic".
    def _norm(text: str) -> str:
        return " " + re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip() + " "

    learner_text = _norm(persona.brain_dump + " " + " ".join(persona.answers))
    echoed = []
    for m in milestones:
        # Compare on the milestone's substantive head, before any concept list:
        # "Ground the type system (type-annotations)" -> "Ground the type system".
        head = re.split(r"[(\[:]", m)[0]
        needle = _norm(head)
        if len(needle.strip()) >= 18 and needle in learner_text:
            echoed.append(m)
    result.check(
        "NO_VERBATIM_ECHO",
        not echoed,
        f"{len(echoed)} milestone(s) lifted from the learner's own words: {echoed[:2]}"
        if echoed
        else "no milestone is a lift from the input",
    )

    # Readiness is the product's own gate for activation.
    try:
        sys.path.insert(0, str(REPO_ROOT / "packages" / "studyloop" / "src"))
        from studyloop.planning import readiness
        from studyloop.planning.store import load_plan

        # load_plan takes only the id — it resolves the plans dir from
        # STUDYLOOP_PLANS_DIR, which main() sets to the scratch dir.
        plan = load_plan(result.plan_path.stem)  # type: ignore[union-attr]
        rd = readiness(plan)
        ok = bool(rd.get("ready", rd.get("ok", False)))
        result.check("READINESS_PASSES", ok, json.dumps(rd)[:300])
    except Exception as exc:  # harness must report, never crash
        result.check("READINESS_PASSES", False, f"could not evaluate: {type(exc).__name__}: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--harness", help=f"one of: {', '.join(sorted(HARNESSES))} (default: auto-detect)"
    )
    ap.add_argument(
        "--persona",
        default="vague",
        choices=sorted(PERSONAS),
        help="which scripted learner (default: vague — the realistic case)",
    )
    ap.add_argument("--max-turns", type=int, default=12, help="hard cost cap (default 12)")
    ap.add_argument("--turn-timeout", type=int, default=900, help="seconds per turn (default 900)")
    ap.add_argument(
        "--plans-dir",
        type=Path,
        default=Path("/tmp/plan_harness"),
        help="scratch plans dir; real plans are never touched (default /tmp/plan_harness)",
    )
    ap.add_argument("--fixture", type=Path, help="write the transcript + plan here for CI replay")
    ap.add_argument("--dry-run", action="store_true", help="print the scripted turns and exit")
    args = ap.parse_args()

    persona = PERSONAS[args.persona]
    if args.dry_run:
        print(f"persona: {persona.name}")
        print(f"brain dump ({len(persona.brain_dump)} chars):\n  {persona.brain_dump[:140]}...\n")
        for i, a in enumerate(persona.answers, 1):
            print(f"answer {i}: {a[:100]}{'...' if len(a) > 100 else ''}")
        print(f"\nthen up to {len(FOLLOW_UPS)} nudges, hard cap {args.max_turns} turns")
        return 0

    h = pick_harness(args.harness)
    args.plans_dir.mkdir(parents=True, exist_ok=True)
    for stale in args.plans_dir.glob("*.md"):
        stale.unlink()

    result = Result(harness=h.name)
    result.persona = persona.name
    started = time.time()
    env_note = f"STUDYLOOP_PLANS_DIR={args.plans_dir}"
    print(
        f"[harness] {h.name} | persona={persona.name} | {env_note} | cap {args.max_turns} turns\n",
        flush=True,
    )

    import os

    os.environ["STUDYLOOP_PLANS_DIR"] = str(args.plans_dir)

    script = [persona.brain_dump, *persona.answers, *FOLLOW_UPS]
    for i, prompt in enumerate(script):
        if result.turns >= args.max_turns:
            print(f"[harness] hit the {args.max_turns}-turn cap")
            break
        t0 = time.time()
        out = run_turn(h, prompt, resume=(i > 0), cwd=REPO_ROOT, timeout=args.turn_timeout)
        result.turns += 1
        elapsed = time.time() - t0
        # Keep the agent's OWN words, not the CLI's furniture, and keep enough
        # of them that a trailing question is actually inside the window.
        tail = clean_agent_output(out)[-1800:]
        result.transcript.append(
            {"turn": result.turns, "prompt": prompt, "seconds": round(elapsed, 1), "tail": tail}
        )
        print(f"[turn {result.turns}] {elapsed:.0f}s — {prompt[:70]}...", flush=True)
        if out == "<<TIMEOUT>>":
            print(f"[harness] turn {result.turns} timed out after {args.turn_timeout}s", flush=True)
            break
        found = newest_plan(args.plans_dir, started)
        if found is not None:
            result.plan_path = found
            print(f"[harness] plan written: {found.name}", flush=True)
            break

    result.seconds = time.time() - started
    plan_text = result.plan_path.read_text() if result.plan_path else ""
    judge(result, plan_text, persona)

    bar = "=" * 72
    head = f"INVARIANTS ({h.name}/{persona.name}, {result.turns} turns, {result.seconds:.0f}s)"
    print(f"\n{bar}\n{head}\n{bar}")
    for name, ok, detail in result.checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<28} {detail}")

    if plan_text:
        print(f"\n{'=' * 72}\nPLAN\n{'=' * 72}\n{plan_text}")

    if args.fixture:
        args.fixture.parent.mkdir(parents=True, exist_ok=True)
        args.fixture.write_text(
            json.dumps(
                {
                    "harness": h.name,
                    "persona": persona.name,
                    "turns": result.turns,
                    "seconds": round(result.seconds, 1),
                    "plan_markdown": plan_text,
                    "checks": [{"name": n, "ok": o, "detail": d} for n, o, d in result.checks],
                    "transcript": result.transcript,
                },
                indent=2,
            )
        )
        print(f"\n[harness] fixture -> {args.fixture}")

    failed = result.failed
    print(f"\n{len(result.checks) - len(failed)}/{len(result.checks)} invariants held")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
