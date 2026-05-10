"""ACP-backed transport for agent CLIs that expose Agent Client Protocol."""

from __future__ import annotations

import asyncio
import json
import os
from typing import TYPE_CHECKING

from studyloop.session_runtime.protocol import SessionEvent, SessionStartSpec

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class AcpAgentSessionTransport:
    """Run an ACP-capable CLI over stdio.

    This is the first adapter boundary for ACP. It deliberately preserves raw
    JSON-RPC payloads so the web layer can evolve without pretending every
    agent has the same high-level event schema yet.
    """

    def __init__(self, spec: SessionStartSpec) -> None:
        self.spec = spec
        self.session_id = spec.session_id
        self._process: asyncio.subprocess.Process | None = None
        self._stopped = False

    async def start(self) -> None:
        """Start the ACP subprocess."""
        command = self.spec.command
        argv = ["/bin/sh", "-lc", command] if isinstance(command, str) else command
        env = os.environ.copy()
        env.update(self.spec.env)
        self._process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(self.spec.cwd),
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

    async def send(self, text: str) -> None:
        """Send a JSON-RPC notification or learner text to the ACP process."""
        process = self._require_process()
        if process.stdin is None:
            raise RuntimeError("ACP process stdin is unavailable")
        payload = _normalise_payload(text)
        process.stdin.write(payload)
        await process.stdin.drain()

    async def events(self) -> AsyncIterator[SessionEvent]:
        """Yield raw ACP stdout lines as events."""
        process = self._require_process()
        yield SessionEvent(
            "started",
            self.session_id,
            {
                "agent": self.spec.agent,
                "transport": "acp",
                "topic": self.spec.topic,
                "energy": self.spec.energy,
            },
        )
        if process.stdout is None:
            return
        while not self._stopped:
            line = await process.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace")
            parsed = _try_json(text)
            yield SessionEvent("acp", self.session_id, {"text": text, "json": parsed})
        yield SessionEvent("ended", self.session_id, {"returncode": process.returncode})

    async def stop(self) -> None:
        """Stop the ACP process."""
        self._stopped = True
        process = self._process
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except TimeoutError:
                process.kill()
                await process.wait()

    def _require_process(self) -> asyncio.subprocess.Process:
        if self._process is None:
            raise RuntimeError("ACP transport has not been started")
        return self._process


def _normalise_payload(text: str) -> bytes:
    stripped = text.strip()
    if stripped.startswith("{"):
        payload = stripped
    else:
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "session/input",
                "params": {"text": text},
            }
        )
    return f"{payload}\n".encode()


def _try_json(text: str) -> object | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
