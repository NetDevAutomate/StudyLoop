-- Unified session export schema for Claude Code and Kiro CLI
-- Supports FTS5 full-text search on message content

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,  -- 'claude_code' or 'kiro_cli'
    project_path TEXT,
    git_branch TEXT,
    created_at TEXT,
    updated_at TEXT,
    metadata JSON
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    parent_id TEXT,
    role TEXT NOT NULL,  -- 'user', 'assistant', 'tool_use', 'tool_result'
    content TEXT,
    model TEXT,
    timestamp TEXT,
    metadata JSON,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_sessions_source ON sessions(source);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_path);

-- Full-text search on message content
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    session_id UNINDEXED,
    role UNINDEXED,
    tokenize='porter unicode61'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages
WHEN NEW.content IS NOT NULL
BEGIN
    INSERT INTO messages_fts(rowid, content, session_id, role)
    VALUES (NEW.rowid, NEW.content, NEW.session_id, NEW.role);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_update AFTER UPDATE ON messages
WHEN NEW.content IS NOT NULL
BEGIN
    UPDATE messages_fts SET
        content = NEW.content,
        session_id = NEW.session_id,
        role = NEW.role
    WHERE rowid = NEW.rowid;
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages
BEGIN
    DELETE FROM messages_fts WHERE rowid = OLD.rowid;
END;
