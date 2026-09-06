"""Schema41: durable retirement identities and distinct administrative eviction."""

from .session_owner_schema import ANNOTATION_TABLES


def install(conn):
    conn.execute("""CREATE TABLE context_lifecycle_mode (
        id INTEGER PRIMARY KEY CHECK(id=1),
        mode TEXT NOT NULL CHECK(mode IN ('ordinary','evict'))
    )""")
    conn.execute("INSERT INTO context_lifecycle_mode VALUES (1,'ordinary')")
    conn.execute("""CREATE TRIGGER lifecycle_mode_required BEFORE DELETE ON context_lifecycle_mode
        BEGIN SELECT RAISE(ABORT,'Lifecycle mode row is required'); END""")
    conn.execute("""CREATE TABLE context_retirements (
        kind TEXT NOT NULL CHECK(kind IN ('session','evidence','assertion','relation','observation','record')),
        object_id TEXT NOT NULL, retired_at TEXT NOT NULL,
        PRIMARY KEY(kind,object_id)
    )""")
    conn.execute("""CREATE TABLE context_erasure_pending (
        id INTEGER PRIMARY KEY CHECK(id=1), requested_at TEXT NOT NULL
    )""")
    for event in ("INSERT", "UPDATE"):
        conn.execute(f"""CREATE TRIGGER lifecycle_erasure_generation_{event.lower()}
            AFTER {event} ON context_erasure_pending BEGIN
              UPDATE context_access_state SET revision=revision+1 WHERE id=1;
            END""")
    for table in (
        "context_retirements",
        "context_tombstones",
        "context_observation_tombstones",
        "context_observation_retired_subjects",
    ):
        for event in ("UPDATE", "DELETE"):
            conn.execute(f"""CREATE TRIGGER lifecycle_permanent_{table}_{event.lower()}
                BEFORE {event} ON {table}
                BEGIN SELECT RAISE(ABORT,'Permanent retirement cannot be removed'); END""")
    ordinary = "(SELECT mode FROM context_lifecycle_mode WHERE id=1)='ordinary'"
    # Only known retirement-producing triggers change. Dependency purges still
    # run during eviction; they simply do not create permanent forgets.
    names = ["context_observation_retirement"]
    names += [f"context_retire_owner_{table}" for table in ANNOTATION_TABLES]
    names += [f"context_retire_legacy_{table}" for table in ANNOTATION_TABLES]
    for name in names:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (name,)
        ).fetchone()[0]
        conn.execute(f"DROP TRIGGER {name}")
        before, body = sql.split("BEGIN", 1)
        before += (
            " AND " + ordinary + " " if "WHEN" in before else " WHEN " + ordinary + " "
        )
        conn.execute(before + "BEGIN" + body)
    for kind, table, column, event in (
        ("session", "context_tombstones", "session_id", "INSERT"),
        ("observation", "context_observation_tombstones", "observation_id", "INSERT"),
        ("evidence", "context_evidence", "id", "DELETE"),
        ("assertion", "context_assertions", "id", "DELETE"),
        ("relation", "context_relations", "id", "DELETE"),
        ("record", "context_record_owners", "id", "DELETE"),
    ):
        ref = "NEW" if event == "INSERT" else "OLD"
        stamp = (
            "NEW.deleted_at"
            if event == "INSERT"
            else "strftime('%Y-%m-%dT%H:%M:%fZ','now')"
        )
        conn.execute(f"""CREATE TRIGGER lifecycle_retire_{kind}
            {"AFTER" if event == "INSERT" else "BEFORE"} {event} ON {table}
            WHEN {ordinary} BEGIN
              INSERT OR IGNORE INTO context_retirements VALUES
                ('{kind}',{ref}.{column},{stamp});
            END""")
    for kind, table in (
        ("evidence", "context_evidence"),
        ("assertion", "context_assertions"),
        ("relation", "context_relations"),
        ("observation", "context_observations"),
        ("record", "context_record_owners"),
    ):
        conn.execute(f"""CREATE TRIGGER lifecycle_no_replay_{kind}
            BEFORE INSERT ON {table}
            WHEN EXISTS(SELECT 1 FROM context_retirements WHERE kind='{kind}' AND object_id=NEW.id)
            BEGIN SELECT RAISE(ABORT,'Object identity was permanently retired'); END""")
    conn.execute("""CREATE TRIGGER lifecycle_pending_erasure AFTER INSERT ON context_retirements
        BEGIN
          INSERT INTO context_erasure_pending VALUES (1,strftime('%Y-%m-%dT%H:%M:%fZ','now'))
          ON CONFLICT(id) DO UPDATE SET requested_at=excluded.requested_at;
          UPDATE context_access_state SET revision=revision+1 WHERE id=1;
        END""")
    conn.execute("""INSERT OR IGNORE INTO context_retirements
        SELECT 'session',session_id,deleted_at FROM context_tombstones""")
    conn.execute("""INSERT OR IGNORE INTO context_retirements
        SELECT 'observation',observation_id,deleted_at FROM context_observation_tombstones""")
