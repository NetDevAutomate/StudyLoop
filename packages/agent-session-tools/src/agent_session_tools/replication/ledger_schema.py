"""Schema42: durable peer knowledge, content offers and control acknowledgements."""


def install(conn):
    conn.execute("""CREATE TABLE context_replica_peers (
        peer TEXT PRIMARY KEY, instance TEXT NOT NULL,
        local_node TEXT NOT NULL, local_instance TEXT NOT NULL, first_seen TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE context_replica_offers (
        id TEXT NOT NULL, direction TEXT NOT NULL CHECK(direction IN ('out','in')),
        peer TEXT NOT NULL REFERENCES context_replica_peers(peer),
        scope TEXT NOT NULL CHECK(scope IN ('personal','work','unclassified')),
        offer_json TEXT NOT NULL CHECK(json_valid(offer_json)),
        status TEXT NOT NULL CHECK(status IN ('prepared','accepted','retired','applied','acknowledged')),
        acceptance_json TEXT CHECK(acceptance_json IS NULL OR json_valid(acceptance_json)),
        receipt_json TEXT CHECK(receipt_json IS NULL OR json_valid(receipt_json)),
        created_at TEXT NOT NULL, PRIMARY KEY(id,direction)
    )""")
    conn.execute("""CREATE TABLE context_replica_objects (
        peer TEXT NOT NULL REFERENCES context_replica_peers(peer),
        kind TEXT NOT NULL CHECK(kind IN ('session','evidence','assertion','relation','observation','record')),
        object_id TEXT NOT NULL,
        scope TEXT NOT NULL CHECK(scope IN ('personal','work','unclassified')),
        first_offer TEXT NOT NULL,
        PRIMARY KEY(peer,kind,object_id,scope)
    )""")
    conn.execute("""CREATE TABLE context_replica_control_batches (
        id TEXT NOT NULL, direction TEXT NOT NULL CHECK(direction IN ('out','in')),
        peer TEXT NOT NULL REFERENCES context_replica_peers(peer),
        batch_json TEXT NOT NULL CHECK(json_valid(batch_json)),
        status TEXT NOT NULL CHECK(status IN ('prepared','applied','acknowledged')),
        receipt_json TEXT CHECK(receipt_json IS NULL OR json_valid(receipt_json)),
        created_at TEXT NOT NULL, PRIMARY KEY(id,direction)
    )""")
    conn.execute("""CREATE TRIGGER replica_offer_transition BEFORE UPDATE ON context_replica_offers
        WHEN (NEW.status IS NOT OLD.status AND NOT (
            (OLD.direction='out' AND OLD.status='prepared' AND NEW.status IN ('accepted','retired'))
            OR (OLD.direction='out' AND OLD.status='accepted' AND NEW.status='acknowledged')
            OR (OLD.direction='in' AND OLD.status='accepted' AND NEW.status='applied')))
          OR (OLD.acceptance_json IS NOT NULL AND NEW.acceptance_json IS NOT OLD.acceptance_json)
          OR (OLD.receipt_json IS NOT NULL AND NEW.receipt_json IS NOT OLD.receipt_json)
        BEGIN SELECT RAISE(ABORT,'Invalid replica offer transition'); END""")
    conn.execute("""CREATE TRIGGER replica_control_transition BEFORE UPDATE ON context_replica_control_batches
        WHEN NEW.status IS NOT OLD.status AND NOT (
            OLD.direction='out' AND OLD.status='prepared' AND NEW.status='acknowledged')
        BEGIN SELECT RAISE(ABORT,'Invalid replica control transition'); END""")
    for table in ("context_replica_peers", "context_replica_objects"):
        for event in ("UPDATE", "DELETE"):
            conn.execute(f"""CREATE TRIGGER replica_history_{table}_{event.lower()}
                BEFORE {event} ON {table}
                BEGIN SELECT RAISE(ABORT,'Replica history requires explicit managed reconciliation'); END""")
    for table, body_column in (
        ("context_replica_offers", "offer_json"),
        ("context_replica_control_batches", "batch_json"),
    ):
        conn.execute(f"""CREATE INDEX {table}_peer ON {table}(peer,direction,status)""")
        scope_guard = (
            " OR NEW.scope IS NOT OLD.scope"
            if table == "context_replica_offers"
            else ""
        )
        conn.execute(f"""CREATE TRIGGER replica_identity_{table}
            BEFORE UPDATE ON {table}
            WHEN NEW.id IS NOT OLD.id OR NEW.direction IS NOT OLD.direction
              OR NEW.peer IS NOT OLD.peer OR NEW.{body_column} IS NOT OLD.{body_column}
              OR NEW.created_at IS NOT OLD.created_at {scope_guard}
            BEGIN SELECT RAISE(ABORT,'Replica transfer identity is immutable'); END""")
        conn.execute(f"""CREATE TRIGGER replica_history_{table}_delete BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT,'Replica transfer history cannot be discarded'); END""")
