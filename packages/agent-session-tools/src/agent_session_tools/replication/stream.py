"""Ordered row frames carrying one complete, hash-bound canonical projection."""

from ..context.store import _json
from .policy import ReplicaError
from .snapshot import TABLES
from .staging import Stage, StagedSnapshot

TARGET_CHUNK_BYTES = 4 * 1024 * 1024
MAX_CHUNK_ROWS = 1024


class Outgoing:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.sequence = 0
        self.parts = self._parts()

    def close(self):
        self.snapshot.close()

    def header(self):
        return {k: v for k, v in self.snapshot.items() if k != "tables"}

    def _parts(self):
        for table in TABLES:
            rows, size = [], 0
            for row in self.snapshot["tables"][table]:
                n = len(_json(row).encode())
                if rows and (
                    size + n > TARGET_CHUNK_BYTES or len(rows) >= MAX_CHUNK_ROWS
                ):
                    yield {"table": table, "rows": rows, "last": False}
                    rows, size = [], 0
                rows.append(row)
                size += n
            yield {"table": table, "rows": rows, "last": True}

    def next(self, sequence):
        if type(sequence) is not int or sequence != self.sequence:
            raise ReplicaError("Invalid outgoing stream sequence")
        part = next(self.parts, None)
        if part is None:
            return None
        self.sequence += 1
        return {"sequence": sequence, **part}


class Incoming:
    def __init__(self, header, columns):
        if not isinstance(header, dict) or set(header) != {
            "contract",
            "plan",
            "scope",
            "legacy_owned_table_gaps",
            "lifecycle_reconciled",
            "sha256",
        }:
            raise ReplicaError("Malformed streamed content header")
        self.header = header
        self.columns = columns
        self.stage = Stage()
        self.tables = {}
        self.sequence = 0
        self.table_index = 0

    def close(self):
        self.stage.close()

    def append(self, chunk):
        if (
            not isinstance(chunk, dict)
            or set(chunk) != {"sequence", "table", "rows", "last"}
            or type(chunk["sequence"]) is not int
            or chunk["sequence"] != self.sequence
            or self.table_index >= len(TABLES)
            or chunk["table"] != TABLES[self.table_index]
            or type(chunk["last"]) is not bool
            or not isinstance(chunk["rows"], list)
            or len(chunk["rows"]) > MAX_CHUNK_ROWS
            or (not chunk["rows"] and not chunk["last"])
        ):
            raise ReplicaError("Malformed or out-of-order content chunk")
        table = chunk["table"]
        if any(
            not isinstance(row, dict) or set(row) != self.columns[table]
            for row in chunk["rows"]
        ):
            raise ReplicaError("Streamed columns differ from installed schema")
        if self.stage.active is None:
            self.stage.start(table)
        self.stage.extend(chunk["rows"])
        if chunk["last"]:
            self.tables[table] = self.stage.end()
            self.table_index += 1
        self.sequence += 1
        return {"staged": True, "sequence": chunk["sequence"], "committed": False}

    def snapshot(self):
        if self.table_index != len(TABLES):
            raise ReplicaError("Incomplete stream cannot be promoted")
        self.stage.seal()
        snapshot = StagedSnapshot(
            self.stage,
            {
                **{k: v for k, v in self.header.items() if k != "sha256"},
                "tables": self.tables,
            },
        )
        if snapshot["sha256"] != self.header["sha256"]:
            raise ReplicaError("Complete stream differs from accepted content binding")
        return snapshot
