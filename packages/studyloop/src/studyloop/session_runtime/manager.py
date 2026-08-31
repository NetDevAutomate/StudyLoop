"""Session manager for live web-driven agent sessions."""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from typing import TYPE_CHECKING

from studyloop.session_runtime.acp import AcpAgentSessionTransport
from studyloop.session_runtime.protocol import AgentSessionTransport, SessionEvent, SessionStartSpec
from studyloop.session_runtime.pty import PtyAgentSessionTransport
from studyloop.session_state import SESSION_DIR

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


class AgentSessionManager:
    """Own live agent transports for the web/PWA session API."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or (SESSION_DIR / "web-sessions")
        self._sessions: dict[str, AgentSessionTransport] = {}

    async def start_session(
        self,
        *,
        topic: str,
        energy: int,
        agent: str | None = None,
        transport: str = "pty",
    ) -> tuple[str, AsyncIterator[SessionEvent]]:
        """Create and start a live agent session."""
        spec = self._build_spec(topic=topic, energy=energy, agent=agent, transport=transport)
        runtime = self._make_transport(spec)
        await runtime.start()
        self._sessions[spec.session_id] = runtime
        return spec.session_id, runtime.events()

    async def send(self, session_id: str, text: str) -> None:
        """Send learner input to an active session."""
        await self._sessions[session_id].send(text)

    async def stop(self, session_id: str) -> None:
        """Stop and forget an active session."""
        runtime = self._sessions.pop(session_id, None)
        if runtime:
            await runtime.stop()

    def _build_spec(
        self,
        *,
        topic: str,
        energy: int,
        agent: str | None,
        transport: str,
    ) -> SessionStartSpec:
        session_id = uuid.uuid4().hex
        session_dir = self.base_dir / _slug(topic) / session_id[:8]
        session_dir.mkdir(parents=True, exist_ok=True)

        resolved_agent = agent or _default_agent()
        command = _build_command(resolved_agent, transport, session_dir, topic, energy)
        env = {"STUDYLOOP_AGENT": resolved_agent}
        return SessionStartSpec(
            session_id=session_id,
            topic=topic,
            energy=energy,
            agent=resolved_agent,
            command=command,
            cwd=session_dir,
            transport=transport,
            env=env,
        )

    @staticmethod
    def _make_transport(spec: SessionStartSpec) -> AgentSessionTransport:
        if spec.transport == "acp":
            return AcpAgentSessionTransport(spec)
        return PtyAgentSessionTransport(spec)


def _default_agent() -> str:
    from studyloop.agent_launcher import detect_agents

    detected = detect_agents()
    if detected:
        return detected[0]
    return "shell"


def _build_command(
    agent: str,
    transport: str,
    session_dir: Path,
    topic: str,
    energy: int,
) -> str | list[str]:
    if agent == "shell":
        shell = os.environ.get("SHELL", "/bin/zsh")
        return [shell, "-l"]

    if transport == "acp":
        return _acp_command(agent)

    from studyloop.agent_launcher import AGENTS, build_canonical_persona

    adapter = AGENTS.get(agent)
    if not adapter:
        raise ValueError(f"Unknown agent: {agent}")
    if not shutil.which(adapter.binary):
        raise ValueError(f"Agent binary not found: {adapter.binary}")

    canonical = build_canonical_persona("focus", topic, energy)
    persona_hash = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    from studyloop.session.orchestrator import setup_session_dir

    setup_session_dir(session_dir, topic)
    persona_file = adapter.setup(canonical, session_dir)
    if adapter.mcp_setup:
        adapter.mcp_setup(session_dir)
    prompt = (
        f"echo 'StudyLoop session: {topic}'; "
        f"echo 'Persona hash: {persona_hash}'; "
        f"{adapter.launch_cmd(persona_file, False)}"
    )
    return prompt


def _acp_command(agent: str) -> list[str]:
    if agent == "kiro":
        binary = shutil.which("kiro-cli") or shutil.which("kiro") or "kiro-cli"
        return [binary, "acp"]
    raise ValueError(f"ACP transport is not configured for agent: {agent}")


def _slug(value: str) -> str:
    slug = "".join(ch if ch.isalnum() else "-" for ch in value.lower()).strip("-")
    return slug[:40] or "study"
