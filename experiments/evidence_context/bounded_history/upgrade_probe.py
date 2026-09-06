"""Upgrade a disposable copy and verify every pre-existing table's rows remain intact."""

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

import agent_session_tools.migrations as migrations


def fingerprint(conn, table):
    quoted = '"' + table.replace('"', '""') + '"'
    rows = [
        json.dumps(list(row), sort_keys=True, default=str)
        for row in conn.execute("SELECT * FROM " + quoted)
    ]
    return {
        "count": len(rows),
        "sha256": hashlib.sha256(json.dumps(sorted(rows)).encode()).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-installed", action="store_true")
    args = parser.parse_args()
    if args.require_installed:
        assert "site-packages" in migrations.__file__
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    with sqlite3.connect(args.source.resolve().as_uri() + "?mode=ro", uri=True) as source:
        conn = sqlite3.connect(output / "upgrade-copy.db")
        source.backup(conn)
    conn.execute("PRAGMA foreign_keys=ON")
    before_version = conn.execute("PRAGMA user_version").fetchone()[0]
    if before_version != 39:
        raise ValueError("This Stage31 rehearsal expects a schema39 source copy")
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    before = {name: fingerprint(conn, name) for name in tables}
    migrations.migrate(conn)
    after = {name: fingerprint(conn, name) for name in tables}
    check = conn.execute("PRAGMA foreign_key_check").fetchall()
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    assert before == after and check == [] and integrity == "ok"
    report = {
        "from_version": before_version,
        "to_version": conn.execute("PRAGMA user_version").fetchone()[0],
        "old_tables_unchanged": len(tables),
        "old_table_rows": sum(v["count"] for v in before.values()),
        "foreign_key_check": check,
        "integrity_check": integrity,
        "installed_module": migrations.__file__,
        "source_opened_read_only": True,
        "limits": "Additive upgrade on a consistent disposable copy. "
        "Not full managed backup restoration with deletion reconciliation.",
    }
    conn.close()
    (output / "results.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
