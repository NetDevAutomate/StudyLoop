"""Schema39: annotations can be about a session without invented evidence inputs."""

ANNOTATION_TABLES = ("session_notes", "session_tags", "session_learning_metadata")


def install(conn):
    conn.execute("""CREATE TABLE context_annotation_retirements (
        session_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('note','tags','learning')),
        PRIMARY KEY(session_id,kind)
    )""")
    for event in ("UPDATE", "DELETE"):
        conn.execute(f"""CREATE TRIGGER context_annotation_retirement_{event.lower()}
            BEFORE {event} ON context_annotation_retirements
            BEGIN SELECT RAISE(ABORT,'Annotation retirement is permanent'); END""")
    conn.execute("""CREATE TRIGGER access_generation_context_annotation_retirements_insert
        AFTER INSERT ON context_annotation_retirements BEGIN
        UPDATE context_access_state SET revision=revision+1 WHERE id=1; END""")
    conn.execute("""CREATE TABLE context_observation_session_owners (
        observation_id TEXT PRIMARY KEY NOT NULL
            REFERENCES context_observations(id) ON DELETE CASCADE,
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE
    )""")
    conn.execute(
        "CREATE INDEX context_observation_session_owner "
        "ON context_observation_session_owners(session_id)"
    )
    conn.execute("""CREATE TRIGGER context_session_owner_immutable
        BEFORE UPDATE ON context_observation_session_owners
        BEGIN SELECT RAISE(ABORT,'Session ownership is immutable'); END""")
    conn.execute("""CREATE TRIGGER context_session_owner_exclusive
        BEFORE INSERT ON context_observation_session_owners
        WHEN EXISTS (SELECT 1 FROM context_observation_owners WHERE observation_id=NEW.observation_id)
          OR EXISTS (SELECT 1 FROM context_observation_sources WHERE observation_id=NEW.observation_id)
          OR EXISTS (SELECT 1 FROM context_tombstones WHERE session_id=NEW.session_id)
        BEGIN SELECT RAISE(ABORT,'Session owner conflicts with existing ownership or retirement'); END""")
    for table in ("context_observation_owners", "context_observation_sources"):
        conn.execute(f"""CREATE TRIGGER {table}_no_session_owner BEFORE INSERT ON {table}
            WHEN EXISTS (SELECT 1 FROM context_observation_session_owners
                         WHERE observation_id=NEW.observation_id)
            BEGIN SELECT RAISE(ABORT,'Observation already has a session owner'); END""")
    conn.execute("""CREATE TRIGGER context_session_owner_delete_observation
        AFTER DELETE ON context_observation_session_owners
        BEGIN DELETE FROM context_observations WHERE id=OLD.observation_id; END""")
    conn.execute("""CREATE TRIGGER context_session_owner_forget
        AFTER INSERT ON context_tombstones BEGIN
        DELETE FROM context_observations WHERE id IN
          (SELECT observation_id FROM context_observation_session_owners WHERE session_id=NEW.session_id);
        END""")
    for event in ("INSERT", "DELETE"):
        conn.execute(f"""CREATE TRIGGER access_generation_context_observation_session_owners_{event.lower()}
            AFTER {event} ON context_observation_session_owners BEGIN
            UPDATE context_access_state SET revision=revision+1 WHERE id=1; END""")
    for table, kind in zip(
        ANNOTATION_TABLES, ("note", "tags", "learning"), strict=True
    ):
        conn.execute(f"""CREATE TRIGGER context_retire_owner_{table}
            BEFORE DELETE ON context_observation_session_owners
            WHEN EXISTS (SELECT 1 FROM context_observations
                         WHERE id=OLD.observation_id AND kind='session.annotation.{kind}')
            BEGIN INSERT OR IGNORE INTO context_annotation_retirements
              VALUES (OLD.session_id,'{kind}'); END""")
        conn.execute(f"""CREATE TRIGGER context_retire_legacy_{table}
            BEFORE DELETE ON context_observations WHEN OLD.kind='session.annotation.{kind}'
            BEGIN INSERT OR IGNORE INTO context_annotation_retirements
              SELECT session_id,'{kind}' FROM context_observation_session_owners
              WHERE observation_id=OLD.id; END""")
        conn.execute(f"""CREATE TRIGGER context_purge_retired_{table}
            AFTER INSERT ON context_annotation_retirements WHEN NEW.kind='{kind}'
            BEGIN DELETE FROM {table} WHERE session_id=NEW.session_id; END""")
        conn.execute(f"""CREATE TRIGGER context_forget_{table} AFTER INSERT ON context_tombstones
            BEGIN DELETE FROM {table} WHERE session_id=NEW.session_id; END""")
        for event in ("INSERT", "UPDATE"):
            conn.execute(f"""CREATE TRIGGER context_no_forgotten_{table}_{event.lower()}
                BEFORE {event} ON {table}
                WHEN EXISTS (SELECT 1 FROM context_tombstones WHERE session_id=NEW.session_id)
                  OR EXISTS (SELECT 1 FROM context_annotation_retirements
                             WHERE session_id=NEW.session_id AND kind='{kind}')
                BEGIN SELECT RAISE(ABORT,'Annotation session was forgotten'); END""")
        # Honour already-recorded deletion intent when upgrading an older file.
        conn.execute(
            f"DELETE FROM {table} WHERE session_id IN (SELECT session_id FROM context_tombstones)"
        )
