"""Transport implementations for AgentSessionTransport.

Each module under this package provides one implementation:

- pty: pty.fork()-based transport for CLI agents (claude, codex, gemini,
  kiro, opencode). Emits raw output bytes + lifecycle events.

See packages/studyloop/src/studyloop/session/transport.py for the protocol
contract.
"""
