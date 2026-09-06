"""Schema45: local operator discard intent, distinct from source provenance."""


def install(conn):
    conn.execute("""CREATE TABLE context_quarantine_discards (
        id TEXT PRIMARY KEY NOT NULL CHECK(length(id)=64),
        local_instance TEXT NOT NULL,
        scope TEXT NOT NULL CHECK(scope IN ('personal','work','unclassified')),
        kind TEXT NOT NULL CHECK(kind IN ('session','evidence','assertion','relation','observation','record')),
        object_id TEXT NOT NULL,
        policy_digest TEXT NOT NULL,
        plan_json TEXT NOT NULL CHECK(json_valid(plan_json)),
        actor TEXT NOT NULL,
        committed_at TEXT NOT NULL,
        receipt_json TEXT NOT NULL CHECK(json_valid(receipt_json))
    )""")
    conn.execute("""CREATE TRIGGER context_quarantine_discard_no_delete
        BEFORE DELETE ON context_quarantine_discards
        BEGIN SELECT RAISE(ABORT,'Local discard history cannot be removed'); END""")
    conn.execute("""CREATE TRIGGER context_quarantine_discard_identity
        BEFORE UPDATE ON context_quarantine_discards
        WHEN NEW.id IS NOT OLD.id OR NEW.local_instance IS NOT OLD.local_instance
          OR NEW.scope IS NOT OLD.scope OR NEW.kind IS NOT OLD.kind
          OR NEW.object_id IS NOT OLD.object_id OR NEW.policy_digest IS NOT OLD.policy_digest
          OR NEW.plan_json IS NOT OLD.plan_json OR NEW.actor IS NOT OLD.actor
          OR NEW.committed_at IS NOT OLD.committed_at
        BEGIN SELECT RAISE(ABORT,'Local discard decision is immutable'); END""")
