"""Schema44: ordered scope permissions and denials independent of permanent forget."""


def install(conn):
    conn.execute(
        "ALTER TABLE context_capture_runs ADD COLUMN withdrawn INTEGER NOT NULL DEFAULT 0"
    )
    conn.execute("""CREATE TABLE context_replica_permissions (
        peer TEXT NOT NULL REFERENCES context_replica_peers(peer),
        direction TEXT NOT NULL CHECK(direction IN ('in','out')),
        scope TEXT NOT NULL CHECK(scope IN ('personal','work','unclassified')),
        generation INTEGER NOT NULL CHECK(generation>0),
        status TEXT NOT NULL CHECK(status IN ('withdrawn','granted')),
        last_batch TEXT NOT NULL, PRIMARY KEY(peer,direction,scope)
    )""")
    conn.execute("""CREATE TABLE context_replica_permission_batches (
        id TEXT NOT NULL, direction TEXT NOT NULL CHECK(direction IN ('in','out')),
        peer TEXT NOT NULL REFERENCES context_replica_peers(peer),
        scope TEXT NOT NULL CHECK(scope IN ('personal','work','unclassified')),
        generation INTEGER NOT NULL CHECK(generation>0),
        action TEXT NOT NULL CHECK(action IN ('withdraw','regrant')),
        batch_json TEXT NOT NULL CHECK(json_valid(batch_json)),
        status TEXT NOT NULL CHECK(status IN ('prepared','applied','acknowledged')),
        receipt_json TEXT CHECK(receipt_json IS NULL OR json_valid(receipt_json)),
        created_at TEXT NOT NULL, PRIMARY KEY(id,direction),
        UNIQUE(peer,direction,scope,generation)
    )""")
    conn.execute("""CREATE TABLE context_replica_denials (
        peer TEXT NOT NULL REFERENCES context_replica_peers(peer),
        scope TEXT NOT NULL CHECK(scope IN ('personal','work','unclassified')),
        kind TEXT NOT NULL CHECK(kind IN ('session','evidence','assertion','relation','observation','record')),
        object_id TEXT NOT NULL, generation INTEGER NOT NULL CHECK(generation>0),
        status TEXT NOT NULL CHECK(status IN ('withdrawn','awaiting_content','released')),
        PRIMARY KEY(peer,scope,kind,object_id)
    )""")
    conn.execute(
        "CREATE INDEX context_replica_denied_objects ON context_replica_denials(kind,object_id,status)"
    )
    for table in (
        "context_replica_permissions",
        "context_replica_permission_batches",
        "context_replica_denials",
    ):
        conn.execute(f"""CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT,'Permission history cannot be discarded'); END""")
    conn.execute("""CREATE TRIGGER context_replica_permission_order BEFORE UPDATE ON context_replica_permissions
        WHEN NEW.peer IS NOT OLD.peer OR NEW.direction IS NOT OLD.direction OR NEW.scope IS NOT OLD.scope
          OR NEW.generation != OLD.generation+1
        BEGIN SELECT RAISE(ABORT,'Permission generation must advance exactly once'); END""")
    conn.execute("""CREATE TRIGGER context_replica_permission_batch_identity BEFORE UPDATE ON context_replica_permission_batches
        WHEN NEW.id IS NOT OLD.id OR NEW.direction IS NOT OLD.direction OR NEW.peer IS NOT OLD.peer
          OR NEW.scope IS NOT OLD.scope OR NEW.generation IS NOT OLD.generation OR NEW.action IS NOT OLD.action
          OR NEW.batch_json IS NOT OLD.batch_json OR NEW.created_at IS NOT OLD.created_at
          OR (NEW.status IS NOT OLD.status AND NOT (OLD.direction='out' AND OLD.status='prepared' AND NEW.status='acknowledged'))
        BEGIN SELECT RAISE(ABORT,'Permission batch identity is immutable'); END""")
    conn.execute("""CREATE TRIGGER context_replica_denial_order BEFORE UPDATE ON context_replica_denials
        WHEN NEW.peer IS NOT OLD.peer OR NEW.scope IS NOT OLD.scope OR NEW.kind IS NOT OLD.kind
          OR NEW.object_id IS NOT OLD.object_id OR NEW.generation < OLD.generation
          OR (NEW.generation=OLD.generation AND NOT (NEW.status=OLD.status OR (OLD.status='awaiting_content' AND NEW.status='released')))
        BEGIN SELECT RAISE(ABORT,'Invalid denial transition'); END""")
    for table in ("context_replica_permissions", "context_replica_denials"):
        for event in ("INSERT", "UPDATE"):
            conn.execute(f"""CREATE TRIGGER {table}_generation_{event.lower()} AFTER {event} ON {table}
                BEGIN UPDATE context_access_state SET revision=revision+1 WHERE id=1; END""")
    for kind, table in (
        ("session", "sessions"),
        ("evidence", "context_evidence"),
        ("assertion", "context_assertions"),
        ("relation", "context_relations"),
        ("observation", "context_observations"),
        ("record", "context_record_owners"),
    ):
        for event in ("INSERT", "UPDATE"):
            conn.execute(f"""CREATE TRIGGER withdrawal_guard_{table}_{event.lower()} BEFORE {event} ON {table}
                WHEN EXISTS (SELECT 1 FROM context_replica_denials d WHERE d.kind='{kind}' AND d.object_id=NEW.id AND d.status!='released') AND (SELECT mode FROM context_lifecycle_mode WHERE id=1)='ordinary'
                BEGIN SELECT RAISE(ABORT,'Object has unresolved permission withdrawal'); END""")
    for table in (
        "messages",
        "session_notes",
        "session_tags",
        "session_learning_metadata",
        "file_references",
    ):
        for event in ("INSERT", "UPDATE"):
            conn.execute(f"""CREATE TRIGGER withdrawal_guard_{table}_{event.lower()} BEFORE {event} ON {table}
                WHEN EXISTS (SELECT 1 FROM context_replica_denials d WHERE d.kind='session' AND d.object_id=NEW.session_id AND d.status!='released') AND (SELECT mode FROM context_lifecycle_mode WHERE id=1)='ordinary'
                BEGIN SELECT RAISE(ABORT,'Session has unresolved permission withdrawal'); END""")
