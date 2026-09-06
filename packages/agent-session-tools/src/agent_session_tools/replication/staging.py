"""Private, disposable row storage for a complete scoped content projection.

This is an internal representation, not a wire format or a durable receipt. No
canonical reader can access it, and only the canonical transaction grants release.
"""

from collections.abc import Mapping, Sequence
import hashlib
import json
import sqlite3

from ..context.store import _json
from .policy import ReplicaError

MAX_STAGED_BYTES = 1024 * 1024 * 1024
MAX_STAGED_ROWS = 1_000_000
MAX_RAW_ROW_BYTES = 8 * 1024 * 1024
MAX_ENCODED_ROW_BYTES = 32 * 1024 * 1024


class RowMap(Mapping):
    """Indexed key lookup without retaining the bodies in a Python dictionary."""

    def __init__(self, rows, key):
        self.rows, self.key = rows, key
        if key != rows.store.keys[rows.table]:
            raise ReplicaError("Unsupported staged identity index")

    def __len__(self):
        return len(self.rows)

    def __iter__(self):
        for row in self.rows.store.conn.execute(
            "SELECT key_json FROM staged_rows WHERE table_name=? ORDER BY ordinal",
            (self.rows.table,),
        ):
            yield json.loads(row[0])

    def __getitem__(self, key):
        found = self.rows.store.conn.execute(
            "SELECT payload FROM staged_rows WHERE table_name=? AND key_json=?",
            (self.rows.table, _json(key)),
        ).fetchone()
        if found is None:
            raise KeyError(key)
        return json.loads(found[0])

    def values(self):
        yield from self.rows

    def items(self):
        for row in self.rows:
            yield row[self.key], row


class StagedRows(Sequence):
    def __init__(self, store, table, count):
        self.store, self.table, self.row_count = store, table, count

    def __len__(self):
        return self.row_count

    def __iter__(self):
        for row in self.store.conn.execute(
            "SELECT payload FROM staged_rows WHERE table_name=? ORDER BY ordinal",
            (self.table,),
        ):
            yield json.loads(row[0])

    def __getitem__(self, index):
        if type(index) is not int:
            raise TypeError("Staged rows require an integer index")
        if index < 0:
            index += self.row_count
        if not 0 <= index < self.row_count:
            raise IndexError(index)
        row = self.store.conn.execute(
            "SELECT payload FROM staged_rows WHERE table_name=? AND ordinal=?",
            (self.table, index),
        ).fetchone()
        if row is None:
            raise ReplicaError("Staged row is missing")
        return json.loads(row[0])

    def indexed(self, key):
        return RowMap(self, key)


class Stage:
    """SQLite owns an unnamed temporary database; no reusable body path exists.

    The cache is limited and staging has no WAL. This data is disposable on any
    error. It never substitutes for canonical rollback or crash recovery.
    """

    def __init__(self):
        from .snapshot import TABLES

        self.conn = sqlite3.connect("")
        self.conn.execute("PRAGMA temp_store=FILE")
        self.conn.execute("PRAGMA cache_size=-2048")
        self.conn.execute("PRAGMA mmap_size=0")
        self.conn.execute("PRAGMA journal_mode=MEMORY")
        self.conn.execute("""CREATE TABLE staged_rows (
            table_name TEXT NOT NULL, ordinal INTEGER NOT NULL,
            key_json TEXT, payload TEXT NOT NULL,
            PRIMARY KEY(table_name,ordinal), UNIQUE(table_name,key_json)
        )""")
        self.tables = frozenset(TABLES)
        self.keys = {}
        self.rows, self.bytes = 0, 0
        self.sealed = False
        self.failed = False
        self.active = None
        self.active_count = 0

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def add(self, table, rows):
        self.start(table)
        self.extend(rows)
        return self.end()

    def start(self, table):
        if (
            self.sealed
            or self.failed
            or self.active is not None
            or table not in self.tables
            or table in self.keys
        ):
            raise ReplicaError("Invalid or repeated staged table")
        # Only maps requested by the closure validator need a unique identity.
        # Composite-key association tables are traversed as rows, never indexed
        # under an invented single-column identity.
        from ..context.records import TABLES as LEARNER_TABLES

        key = (
            "session_id"
            if table == "context_session_projects"
            else "id"
            if table
            in {
                "sessions",
                "messages",
                "context_evidence",
                "context_assertions",
                "context_relations",
                "context_observations",
                "context_record_owners",
                *LEARNER_TABLES,
            }
            else None
        )
        self.keys[table] = key
        self.active, self.active_count = table, 0

    def extend(self, rows):
        if self.active is None or self.failed or self.sealed:
            raise ReplicaError("No writable staged table")
        table, key = self.active, self.keys[self.active]
        try:
            for row in rows:
                encoded = _json(row)
                size = len(encoded.encode())
                self.rows += 1
                self.bytes += size
                if (
                    size > MAX_ENCODED_ROW_BYTES
                    or self.bytes > MAX_STAGED_BYTES
                    or self.rows > MAX_STAGED_ROWS
                ):
                    raise ReplicaError("Staged content exceeds its resource bounds")
                if key is not None and row.get(key) is None:
                    raise ReplicaError("Missing staged object identity")
                self.conn.execute(
                    "INSERT INTO staged_rows VALUES (?,?,?,?)",
                    (
                        table,
                        self.active_count,
                        _json(row[key]) if key else None,
                        encoded,
                    ),
                )
                self.active_count += 1
        except sqlite3.IntegrityError as exc:
            self.failed = True
            raise ReplicaError("Duplicate staged object identity") from exc
        except BaseException:
            self.failed = True
            raise

    def end(self):
        if self.active is None or self.failed or self.sealed:
            raise ReplicaError("No complete staged table")
        result = StagedRows(self, self.active, self.active_count)
        self.active = None
        return result

    def seal(self):
        if (
            self.failed
            or self.sealed
            or self.active is not None
            or set(self.keys) != self.tables
        ):
            raise ReplicaError("Incomplete or already sealed staging")
        self.conn.commit()
        self.conn.execute("PRAGMA query_only=ON")
        self.sealed = True


def canonical_parts(value):
    """Same bytes as canonical JSON, yielding at most one encoded row at a time."""
    if isinstance(value, StagedRows):
        yield "["
        for i, row in enumerate(value):
            if i:
                yield ","
            yield _json(row)
        yield "]"
    elif isinstance(value, dict):
        yield "{"
        for i, key in enumerate(sorted(value)):
            if i:
                yield ","
            yield _json(key)
            yield ":"
            yield from canonical_parts(value[key])
        yield "}"
    else:
        yield _json(value)


def binding(value):
    digest, size = hashlib.sha256(), 0
    for part in canonical_parts(value):
        encoded = part.encode()
        size += len(encoded)
        if size > MAX_STAGED_BYTES:
            raise ReplicaError("Encoded staged content exceeds its resource bound")
        digest.update(encoded)
    return digest.hexdigest(), size


class StagedSnapshot(dict):
    """Internal complete projection, owned by the caller until closed."""

    def __init__(self, stage, value):
        if not stage.sealed:
            raise ReplicaError("Unsealed staging cannot become a snapshot")
        super().__init__(value)
        self.stage = stage
        self["sha256"], _ = binding(self)
        _, self.encoded_bytes = binding(self)

    def close(self):
        self.stage.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
