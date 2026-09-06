"""Rehearse schema36-to37 on a copy, comparing all pre-existing column values."""

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

import agent_session_tools.migrations as migrations


def quoted(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def fingerprint(conn, table, columns, where=""):
    sql = "SELECT " + ",".join(map(quoted, columns)) + " FROM " + quoted(table) + where
    rows = [json.dumps(list(row), default=str) for row in conn.execute(sql)]
    return {
        "rows": len(rows),
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
    if before_version != 36:
        raise ValueError("The Stage27 rehearsal expects a schema36 source")
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    columns = {
        table: [r[1] for r in conn.execute("PRAGMA table_info(" + quoted(table) + ")")]
        for table in tables
    }
    before = {table: fingerprint(conn, table, columns[table]) for table in tables}
    migrations.migrate(conn)
    after = {
        table: fingerprint(
            conn,
            "context_board_columns" if table == "board_columns" else table,
            columns[table],
            " WHERE scope='unclassified'" if table == "board_columns" else "",
        )
        for table in tables
    }
    foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    assert before == after and foreign_keys == [] and integrity == "ok"
    report = {
        "from_version": before_version,
        "to_version": conn.execute("PRAGMA user_version").fetchone()[0],
        "old_table_values_preserved": len(tables),
        "old_rows_preserved": sum(v["rows"] for v in before.values()),
        "legacy_board_names_moved": "board_columns" in tables,
        "foreign_key_check": foreign_keys,
        "integrity_check": integrity,
        "installed_module": migrations.__file__,
        "source_opened_read_only": True,
        "limits": "Consistent disposable copy; compares original columns after additive columns "
        "and the explicit legacy-board relocation. Not managed restore or replica reconciliation.",
    }
    conn.close()
    (output / "results.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
