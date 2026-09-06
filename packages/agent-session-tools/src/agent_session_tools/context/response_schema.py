"""Schema38: a durable generation for access and retirement changes."""

from uuid import uuid4

# New bodies do not invalidate a read. Changes to their access dependencies or
# removal do. This deliberately also detects grants and unrelated revocations.
EVENTS = {
    "context_projects": ("INSERT", "UPDATE", "DELETE"),
    "context_session_projects": ("INSERT", "UPDATE", "DELETE"),
    "context_tombstones": ("INSERT", "UPDATE", "DELETE"),
    "context_observation_owners": ("UPDATE", "DELETE"),
    "context_observation_sources": ("INSERT", "DELETE"),
    "context_record_owners": ("DELETE",),
    "context_record_study_links": ("INSERT", "DELETE"),
    "context_record_observations": ("INSERT", "DELETE"),
    "context_review_targets": ("INSERT", "DELETE"),
    "context_evidence": ("DELETE",),
    "context_observations": ("DELETE",),
    "context_assertions": ("DELETE",),
    "context_relations": ("DELETE",),
    "context_citations": ("DELETE",),
    "context_observation_tombstones": ("INSERT", "DELETE"),
}


def install(conn):
    conn.execute("""CREATE TABLE context_access_state (
        id INTEGER PRIMARY KEY CHECK(id=1), instance TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK(revision>=0)
    )""")
    conn.execute("INSERT INTO context_access_state VALUES (1,?,0)", (uuid4().hex,))
    for table, events in EVENTS.items():
        for event in events:
            conn.execute(f"""CREATE TRIGGER access_generation_{table}_{event.lower()}
                AFTER {event} ON {table} BEGIN
                UPDATE context_access_state SET revision=revision+1 WHERE id=1;
                END""")
