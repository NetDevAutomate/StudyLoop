"""Schema43: local, content-bound retention history; no inferred legacy origins."""


def install(conn):
    conn.execute("""CREATE TABLE context_retention_origins (
        table_name TEXT NOT NULL,
        key_sha256 TEXT NOT NULL CHECK(length(key_sha256)=64),
        row_sha256 TEXT NOT NULL CHECK(length(row_sha256)=64),
        origin TEXT NOT NULL CHECK(origin IN ('native_capture','peer_commit','unattributed')),
        contributor TEXT NOT NULL,
        receipt_id TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        PRIMARY KEY(table_name,key_sha256,row_sha256,origin,contributor,receipt_id)
    )""")
    # This ledger is machine-local. It is deliberately absent from the scoped
    # content packet: a sender cannot export its own local-origin label as ours.
    # There is no backfill. Neither row age nor absence of a peer receipt proves
    # that a legacy row was independently captured on this machine.
    for event in ("UPDATE", "DELETE"):
        conn.execute(f"""CREATE TRIGGER context_retention_origins_{event.lower()}
            BEFORE {event} ON context_retention_origins
            BEGIN SELECT RAISE(ABORT,'Retention history requires managed reconciliation'); END""")
