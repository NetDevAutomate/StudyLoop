"""Transport implementations for AgentSessionTransport.

Each module under this package provides one implementation:

- pty: pty.fork()-based transport for the admitted CLI harnesses. Emits raw
  output bytes plus lifecycle events.
- acp: stdio JSON-RPC transport for the Agent Client Protocol endpoints of
  Kiro CLI (``kiro-cli acp``) and Grok Build (``grok agent stdio``).
  See ``private-docs/2026-05-10-acp-event-shapes.md`` for the event-shape
  capture spike that motivates the skeleton.
- acp_normaliser: pure helper module for translating ACP wire shapes
  into our ``AgentMessage`` event vocabulary. Used by ``acp.py`` at
  Phase 2 implementation time.

See packages/studyloop/src/studyloop/session/transport.py for the protocol
contract.
"""
