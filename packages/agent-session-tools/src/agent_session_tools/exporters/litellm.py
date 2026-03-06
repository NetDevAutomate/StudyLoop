"""LiteLLM Bedrock Proxy session exporter.

Extracts AI model usage sessions from litellm-bedrock-proxy webhook_metrics.
Currently supports metadata-only integration with session clustering.

Phase 1: Metadata-only (performance metrics as session context)
Phase 2: Full conversation capture (requires LiteLLM enhancements)
"""

import contextlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from .base import ExportStats


class LitellmExporter:
    """Exporter for LiteLLM Bedrock Proxy webhook metrics."""

    source_name = "litellm-proxy"

    def __init__(self, litellm_db_path: Path | None = None, session_timeout_minutes: int = 30):
        """Initialize LiteLLM exporter.

        Args:
            litellm_db_path: Path to LiteLLM metrics.db (auto-detect if None)
            session_timeout_minutes: Minutes of inactivity before new session
        """
        self.litellm_db_path = litellm_db_path or self._find_litellm_database()
        self.session_timeout = timedelta(minutes=session_timeout_minutes)

    def _find_litellm_database(self) -> Path | None:
        """Auto-detect LiteLLM database location."""
        candidates = [
            Path.home() / "code/personal/ai/litellm-bedrock-proxy/metrics.db",
            Path.home() / ".config/litellm-bedrock-proxy/metrics.db",
            Path.cwd().parent / "litellm-bedrock-proxy/metrics.db",
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate

        return None

    def is_available(self) -> bool:
        """Check if LiteLLM database is available."""
        return self.litellm_db_path is not None and self.litellm_db_path.exists()

    def export_all(self, conn: sqlite3.Connection, incremental: bool = True) -> ExportStats:
        """Export LiteLLM webhook metrics as sessions.

        Strategy:
        1. Query webhook_metrics for all records
        2. Group by inferred sessions (user patterns + time clustering)
        3. Create session records with aggregated metadata
        4. Create message records with available preview content

        Args:
            conn: Agent Session Tools database connection
            incremental: If True, only import new data

        Returns:
            Export statistics
        """
        if not self.is_available():
            return ExportStats(added=0, updated=0, skipped=0, errors=0)

        stats = ExportStats(added=0, updated=0, skipped=0, errors=0)

        # Connect to LiteLLM database
        assert self.litellm_db_path is not None
        litellm_conn = sqlite3.connect(self.litellm_db_path)
        litellm_conn.row_factory = sqlite3.Row

        try:
            # Check if full conversation table exists and has data
            full_conversations_available = self._check_conversations_table(litellm_conn)

            if full_conversations_available:
                webhook_records = litellm_conn.execute("""
                    SELECT * FROM webhook_conversations
                    ORDER BY timestamp
                """).fetchall()
            else:
                webhook_records = litellm_conn.execute("""
                    SELECT * FROM webhook_metrics
                    ORDER BY timestamp
                """).fetchall()

            if not webhook_records:
                return stats

            # Group records into inferred sessions
            sessions = self._detect_sessions(webhook_records, full_conversations_available)

            # Export each session
            for session in sessions:
                try:
                    if self._export_session(conn, session, incremental):
                        stats.added += 1
                    else:
                        stats.skipped += 1
                except Exception:
                    stats.errors += 1

            conn.commit()

        finally:
            litellm_conn.close()

        return stats

    def _check_conversations_table(self, litellm_conn: sqlite3.Connection) -> bool:
        """Check if webhook_conversations table exists and has data."""
        try:
            # Check if table exists
            tables = litellm_conn.execute("""
                SELECT name FROM sqlite_master WHERE type='table' AND name='webhook_conversations'
            """).fetchall()

            if not tables:
                return False

            # Check if table has data
            count = litellm_conn.execute("SELECT COUNT(*) FROM webhook_conversations").fetchone()[0]
            return count > 0

        except Exception:
            return False

    def _detect_sessions(self, webhook_records: list, full_content: bool = False) -> list[dict]:
        """Detect session boundaries from webhook records.

        Strategy: Group requests by temporal clustering since user_id not available
        - Each sequence of requests within session_timeout = one session
        - Session ID generated from first request timestamp
        """
        sessions = []
        current_session = None
        last_timestamp = None

        for record in webhook_records:
            try:
                # Parse timestamp
                record_time = datetime.fromisoformat(record["timestamp"])

                # Parse raw_data for additional context
                raw_data = {}
                if record["raw_data"]:
                    with contextlib.suppress(json.JSONDecodeError):
                        raw_data = json.loads(record["raw_data"])

                # Determine if new session needed
                start_new_session = current_session is None or (
                    last_timestamp and (record_time - last_timestamp) > self.session_timeout
                )

                if start_new_session:
                    # Finalize current session
                    if current_session:
                        sessions.append(current_session)

                    # Start new session
                    session_id = f"litellm_{int(record_time.timestamp())}"
                    current_session = {
                        "id": session_id,
                        "created_at": record_time.isoformat(),
                        "updated_at": record_time.isoformat(),
                        "project_path": raw_data.get("endpoint", "unknown"),
                        "metadata": {
                            "models_used": [],
                            "total_requests": 0,
                            "total_tokens": 0,
                            "total_cost": 0.0,
                            "avg_response_time": 0.0,
                            "error_count": 0,
                            "litellm_source": "webhook_metrics",
                        },
                        "messages": [],
                    }

                # Add request to current session
                if current_session:
                    self._add_request_to_session(current_session, record, raw_data, full_content)
                    last_timestamp = record_time

            except Exception:
                # Skip malformed records
                continue

        # Don't forget the last session
        if current_session:
            sessions.append(current_session)

        return sessions

    def _add_request_to_session(
        self, session: dict, record, raw_data: dict, full_content: bool = False
    ):
        """Add webhook record to session as messages."""
        try:
            session["updated_at"] = record["timestamp"]

            # Update session metadata (sqlite3.Row access)
            metadata = session["metadata"]
            metadata["total_requests"] += 1
            metadata["total_tokens"] += record["tokens_used"] if record["tokens_used"] else 0

            if record["event_type"] == "failure":
                metadata["error_count"] += 1

            model = record["model"] or "unknown"
            if model not in metadata["models_used"]:
                metadata["models_used"].append(model)

        except Exception:
            return

        # Create messages from available data (always create at least metadata messages)
        try:
            message_id = raw_data.get("request_id", str(uuid.uuid4()))

            # Extract content based on available data source
            if full_content and "conversation_json" in record and record["conversation_json"]:
                # Extract from full conversation data
                user_content, assistant_content = self._extract_full_conversation(
                    record["conversation_json"]
                )
            else:
                # Use preview content
                user_content = raw_data.get("request_preview", "") or f"[LiteLLM Request: {model}]"
                if record["event_type"] == "success":
                    assistant_content = (
                        raw_data.get("response_preview", "")
                        or f"[LiteLLM Response: {record['tokens_used'] or 0} tokens]"
                    )
                else:
                    assistant_content = f"[Error: {record['error_message'] or 'Unknown error'}]"

            user_message = {
                "id": f"{message_id}_user",
                "session_id": session["id"],
                "role": "user",
                "content": user_content,
                "model": model,
                "timestamp": record["timestamp"],
                "metadata": json.dumps(
                    {
                        "request_id": message_id,
                        "endpoint": raw_data.get("endpoint", ""),
                        "preview_only": not full_content,
                        "full_content_available": full_content,
                        "content_source": "webhook_conversations"
                        if full_content
                        else "webhook_metrics",
                        "raw_data_keys": list(raw_data.keys())[:10],  # Debug info
                    }
                ),
                "seq": len(session["messages"]) + 1,
            }
            session["messages"].append(user_message)

            # Assistant message uses extracted content (already determined above)

            assistant_message = {
                "id": f"{message_id}_assistant",
                "session_id": session["id"],
                "role": "assistant",
                "content": assistant_content,
                "model": model,
                "timestamp": record["timestamp"],
                "metadata": json.dumps(
                    {
                        "request_id": message_id,
                        "tokens_used": record["tokens_used"] or 0,
                        "response_time_ms": (record["response_time"] or 0) * 1000,
                        "ttft_ms": raw_data.get("time_to_first_token", 0),
                        "event_type": record["event_type"] or "unknown",
                        "status_code": record["status_code"] or 0,
                        "preview_only": not full_content,
                        "full_content_available": full_content,
                        "content_source": "webhook_conversations"
                        if full_content
                        else "webhook_metrics",
                    }
                ),
                "seq": len(session["messages"]) + 1,
            }
            session["messages"].append(assistant_message)

        except Exception:
            pass  # Skip malformed records silently

    def _extract_full_conversation(self, conversation_json: str) -> tuple[str, str]:
        """Extract full user prompt and assistant response from conversation JSON.

        Args:
            conversation_json: JSON string from webhook_conversations table

        Returns:
            Tuple of (user_content, assistant_content)
        """
        try:
            if not conversation_json:
                return "", ""

            # Parse the conversation JSON
            conv_data = json.loads(conversation_json)

            user_content = ""
            assistant_content = ""

            # Extract user messages from request data (multiple possible formats)
            if "request" in conv_data and "messages" in conv_data["request"]:
                messages = conv_data["request"]["messages"]
                user_messages = [msg for msg in messages if msg.get("role") == "user"]
                if user_messages:
                    user_content = user_messages[-1].get("content", "")

            # Alternative: kwargs format
            if not user_content and "kwargs" in conv_data and "messages" in conv_data["kwargs"]:
                messages = conv_data["kwargs"]["messages"]
                user_messages = [msg for msg in messages if msg.get("role") == "user"]
                if user_messages:
                    user_content = user_messages[-1].get("content", "")

            # Extract assistant response from completion data
            if "response" in conv_data and "choices" in conv_data["response"]:
                choices = conv_data["response"]["choices"]
                if choices and "message" in choices[0]:
                    assistant_content = choices[0]["message"].get("content", "")

            # Alternative: completion_response format
            if not assistant_content and "completion_response" in conv_data:
                completion = conv_data["completion_response"]
                if "choices" in completion and completion["choices"]:
                    choice = completion["choices"][0]
                    if "message" in choice:
                        assistant_content = choice["message"].get("content", "")

            return (
                user_content or "[No user content]",
                assistant_content or "[No assistant content]",
            )

        except (json.JSONDecodeError, KeyError, TypeError, IndexError):
            return "", ""

    def _export_session(self, conn: sqlite3.Connection, session: dict, incremental: bool) -> bool:
        """Export single session to Agent Session Tools database."""
        session_id = session["id"]

        # Check if already imported (incremental mode)
        if incremental:
            existing = conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if existing:
                return False

        # Skip sessions with no messages
        if not session["messages"]:
            return False

        # Insert session record
        conn.execute(
            """
            INSERT OR REPLACE INTO sessions
            (id, source, project_path, git_branch, created_at, updated_at, metadata)
            VALUES (?, 'litellm-proxy', ?, NULL, ?, ?, ?)
        """,
            (
                session_id,
                session["project_path"],
                session["created_at"],
                session["updated_at"],
                json.dumps(session["metadata"]),
            ),
        )

        # Insert messages
        conn.executemany(
            """
            INSERT OR REPLACE INTO messages
            (id, session_id, role, content, model, timestamp, metadata, seq)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            [
                (
                    msg["id"],
                    session_id,
                    msg["role"],
                    msg["content"],
                    msg["model"],
                    msg["timestamp"],
                    msg["metadata"],
                    msg["seq"],
                )
                for msg in session["messages"]
            ],
        )

        return True
