"""Spike probe (T1): how many bytes does one send_input() deliver through the
PTY master to a raw-mode child, and what does os.write return / raise?

Not a test. Run from the worktree with:
  env -u VIRTUAL_ENV uv run python openspec/changes/module-contract-v1/evidence/T/pty_probe.py
"""

from __future__ import annotations

import asyncio
import errno
import hashlib
import os
import sys
import tempfile
import textwrap
import warnings

from studyloop.session.transport import OutputBytes, SessionConfig, Stopped
from studyloop.session.transports.pty import PTYTransport

warnings.filterwarnings("ignore", category=DeprecationWarning)

CHILD = textwrap.dedent(
    """
    import hashlib, os, sys, termios, tty
    mode = sys.argv[1]
    want = int(sys.argv[2])
    fd = sys.stdin.fileno()
    if mode == "raw":
        tty.setraw(fd)
    buf = b""
    while len(buf) < want:
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        buf += chunk
        if buf.endswith(b"<<END>>"):
            break
    sys.stdout.write("GOT %d sha=%s\\n" % (len(buf), hashlib.sha256(buf).hexdigest()[:12]))
    sys.stdout.flush()
    """
)


async def probe(mode: str, size: int, *, direct: bool) -> str:
    tmp = tempfile.mkdtemp()
    script = os.path.join(tmp, "child.py")
    with open(script, "w") as fh:
        fh.write(CHILD)
    payload = (b"x" * (size - 7)) + b"<<END>>"
    want = len(payload)

    t = PTYTransport(
        resolve_binary=lambda _a: sys.executable,
        build_launch_cmd=lambda _c: [sys.executable, script, mode, str(want)],
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
    await asyncio.sleep(0.3)  # let the child set raw mode before we write
    note = ""
    if direct:
        fd = t._state.master_fd  # type: ignore[union-attr]
        try:
            n = os.write(fd, payload)
            note = f"os.write returned {n}/{want}"
        except OSError as exc:
            note = f"os.write raised errno={exc.errno} ({errno.errorcode.get(exc.errno)})"
    else:
        try:
            await t.send_input(payload)
            note = "send_input returned None"
        except OSError as exc:
            note = f"send_input raised errno={exc.errno} ({errno.errorcode.get(exc.errno)})"
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
        note += " | child never reported (timeout)"
    await t.end()
    got = ""
    if b"GOT " in out:
        got = out[out.index(b"GOT ") :].split(b"\n", 1)[0].decode(errors="replace")
    psha = hashlib.sha256(payload).hexdigest()[:12]
    return (
        f"{mode:6} size={want:6} direct={direct!s:5} :: {note} :: child {got} (payload sha={psha})"
    )


async def main() -> None:
    for mode in ("raw", "cooked"):
        for size in (512, 1024, 2048, 4096, 8192, 16384, 65536):
            for direct in (True, False):
                print(await probe(mode, size, direct=direct))


asyncio.run(main())
