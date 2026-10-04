"""Spike probe 2 (T1): does a loop on the short count (wait for master
writability, write the remainder) deliver the whole payload to a raw-mode
child? And in cooked mode with a trailing newline, how much of a long
line survives the canonical line discipline?

Not a test. Run from the worktree with:
  env -u VIRTUAL_ENV uv run python openspec/changes/module-contract-v1/evidence/T/pty_probe2.py
"""

from __future__ import annotations

import asyncio
import errno
import hashlib
import os
import select
import sys
import tempfile
import textwrap
import warnings

from studyloop.session.transport import OutputBytes, SessionConfig, Stopped
from studyloop.session.transports.pty import PTYTransport

warnings.filterwarnings("ignore", category=DeprecationWarning)

CHILD = textwrap.dedent(
    """
    import hashlib, os, sys, tty
    mode = sys.argv[1]
    fd = sys.stdin.fileno()
    if mode == "raw":
        tty.setraw(fd)
    buf = b""
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        buf += chunk
        if b"<<END>>" in buf:
            break
    sys.stdout.write("GOT %d sha=%s\\n" % (len(buf), hashlib.sha256(buf).hexdigest()[:12]))
    sys.stdout.flush()
    """
)


def looped_write(fd: int, payload: bytes, deadline_s: float = 3.0) -> tuple[int, int, str]:
    """Write all of payload; wait for writability between short writes."""
    view = memoryview(payload)
    sent = 0
    rounds = 0
    note = ""
    while sent < len(view):
        try:
            n = os.write(fd, view[sent:])
        except OSError as exc:
            if exc.errno == errno.EAGAIN:
                n = 0
            else:
                return sent, rounds, f"raised {errno.errorcode.get(exc.errno)}"
        sent += n
        rounds += 1
        if sent < len(view):
            _, w, _ = select.select([], [fd], [], deadline_s)
            if not w:
                note = "select(write) timed out"
                break
    return sent, rounds, note


async def probe(mode: str, size: int, newline: bool) -> str:
    tmp = tempfile.mkdtemp()
    script = os.path.join(tmp, "child.py")
    with open(script, "w") as fh:
        fh.write(CHILD)
    tail = b"<<END>>\n" if newline else b"<<END>>"
    payload = (b"x" * (size - len(tail))) + tail

    t = PTYTransport(
        resolve_binary=lambda _a: sys.executable,
        build_launch_cmd=lambda _c: [sys.executable, script, mode],
    )
    cfg = SessionConfig(
        study_session_id="probe",
        agent="probe",
        persona_file="/dev/null",
        cwd=tmp,
        env=dict(os.environ),
        cols=200,
        rows=50,
    )
    await t.start(cfg)
    await asyncio.sleep(0.3)
    fd = t._state.master_fd  # type: ignore[union-attr]
    sent, rounds, note = looped_write(fd, payload)
    out = b""
    try:
        async with asyncio.timeout(4.0):
            async for ev in t.events():
                if isinstance(ev, OutputBytes):
                    out += ev.data
                    if b"GOT " in out and b"\n" in out[out.index(b"GOT ") :]:
                        break
                if isinstance(ev, Stopped):
                    break
    except TimeoutError:
        note += " | child never reported"
    await t.end()
    got = ""
    if b"GOT " in out:
        got = out[out.index(b"GOT ") :].split(b"\n", 1)[0].decode(errors="replace")
    psha = hashlib.sha256(payload).hexdigest()[:12]
    return (
        f"{mode:6} size={len(payload):6} nl={newline!s:5} :: looped write sent"
        f" {sent}/{len(payload)} in {rounds} rounds {note} :: child {got} (payload sha={psha})"
    )


async def main() -> None:
    for size in (1024, 4096, 16384, 65536):
        print(await probe("raw", size, newline=False))
    for size in (512, 1024, 2048, 4096):
        print(await probe("cooked", size, newline=True))


asyncio.run(main())
