"""Select scoped annotation headers before checking bounded report bodies.

Current conflict groups are atomic. History uses keyset continuation tied to the
query and access snapshot. Cursors are hints, never access capabilities.
"""

import base64
import binascii
import json

from .annotations import KINDS, _access, _legacy
from .observations import ObservationStore
from .query_budget import query_budget
from .scope import ScopeError, active_policy, visibility_sql
from .store import _hash, _json

MAX_CURRENT = 64
MAX_LINKS = 256
VM_STEPS = 1_000_000
CURRENT = "NOT EXISTS (SELECT 1 FROM context_observation_supersedes v WHERE v.previous_id=o.id)"


class Reader:
    def __init__(self, conn, session_id, kind):
        if kind not in KINDS:
            raise ValueError("Annotation kind must be note, tags or learning")
        self.conn, self.sid, self.kind = conn, session_id, kind
        self.store = ObservationStore(conn)
        if not self.store._session_owners_available():
            raise RuntimeError(
                "Annotation pages need schema39 or later; apply the current scope policy"
            )
        self.policy = active_policy()
        self.scope = self.policy.request_scope()
        visible, values = visibility_sql(
            conn, "s.id", policy=self.policy, scope=self.scope
        )
        if not conn.execute(
            "SELECT 1 FROM sessions s WHERE s.id=? AND " + visible,
            [session_id, *values],
        ).fetchone():
            raise ScopeError("Annotation session unavailable in current scope")
        self.visible = self.store._visible(self.policy, self.scope)
        from .records import observation_clause

        dependencies, dependency_values = observation_clause(conn, self.policy)
        # The exclusive native parent was checked in this read snapshot. Keep
        # per-record dependencies, without testing unrelated owner alternatives
        # for every historical row. The final response guard still checks access.
        self.where = (
            "o.kind=? AND o.subject=? AND own.session_id=? "
            "AND NOT EXISTS (SELECT 1 FROM context_observation_tombstones t "
            "WHERE t.observation_id=o.id) AND " + dependencies
        )
        self.values = [KINDS[kind], session_id, session_id, *dependency_values]
        self.join = (
            "context_observations o JOIN context_observation_session_owners own "
            "ON own.observation_id=o.id"
        )
        state = _access(conn)
        self.state = _hash(
            _json(
                [
                    "annotation-history/v1",
                    session_id,
                    kind,
                    self.policy.digest,
                    self.scope.value,
                    state[2],
                    state[3],
                ]
            )
        )

    def counts(self):
        row = self.conn.execute(
            f"SELECT count(*),coalesce(sum({CURRENT}),0) "
            f"FROM {self.join} WHERE {self.where}",
            self.values,
        ).fetchone()
        return row[0], row[1]

    def legacy(self, version_count, max_bytes):
        has_owned_history = self.conn.execute(
            "SELECT 1 FROM context_observations o JOIN context_observation_session_owners own "
            "ON own.observation_id=o.id WHERE o.kind=? AND o.subject=? AND own.session_id=? LIMIT 1",
            (KINDS[self.kind], self.sid, self.sid),
        ).fetchone()
        retired = self.conn.execute(
            "SELECT 1 FROM context_annotation_retirements WHERE session_id=? AND kind=?",
            (self.sid, self.kind),
        ).fetchone()
        retired = (
            retired
            or self.conn.execute(
                "SELECT 1 FROM context_observation_retired_subjects WHERE subject_sha256=?",
                (_hash(_json([KINDS[self.kind], self.sid])),),
            ).fetchone()
        )
        if version_count or has_owned_history or retired:
            return None, False, None
        table = {
            "note": "session_notes",
            "tags": "session_tags",
            "learning": "session_learning_metadata",
        }[self.kind]
        columns = [r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")]
        sizes = "+".join(
            'coalesce(length(CAST("' + col.replace('"', '""') + '" AS BLOB)),0)'
            for col in columns
        )
        count, body_bytes = self.conn.execute(
            f"SELECT count(*),coalesce(sum({sizes}),0) FROM {table} WHERE session_id=?",
            (self.sid,),
        ).fetchone()
        if not count:
            return None, False, None
        if count > MAX_LINKS:
            return None, True, "legacy_item_limit"
        if body_bytes > max_bytes:
            return None, True, "report_exceeds_byte_budget"
        return _legacy(self.conn, self.sid, self.kind), True, None

    def decode(self, cursor):
        if cursor is None:
            return None
        try:
            if not isinstance(cursor, str) or len(cursor) > 1024:
                raise ValueError()
            value = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
            if (
                not isinstance(value, dict)
                or set(value) != {"v", "state", "after"}
                or type(value["v"]) is not int
                or value["v"] != 1
                or value["state"] != self.state
                or (
                    value["after"] is not None
                    and (
                        not isinstance(value["after"], list)
                        or len(value["after"]) != 2
                        or any(not isinstance(k, str) or not k for k in value["after"])
                    )
                )
            ):
                raise ValueError()
            key = value["after"]
            if key is None:
                return None
            row = self.conn.execute(
                f"SELECT 1 FROM {self.join} WHERE {self.where} "
                f"AND NOT ({CURRENT}) AND o.recorded_at=? AND o.id=?",
                [*self.values, *key],
            ).fetchone()
            if row is None:
                raise ValueError()
            return key
        except (ValueError, TypeError, KeyError, binascii.Error, UnicodeError) as exc:
            raise ValueError(
                "Annotation continuation is invalid or stale; restart the history request"
            ) from exc

    def encode(self, row):
        return base64.urlsafe_b64encode(
            _json(
                {
                    "v": 1,
                    "state": self.state,
                    "after": [row["recorded_at"], row["id"]] if row else None,
                }
            ).encode()
        ).decode()

    def headers(self, *, current, limit, after=None):
        where = self.where + (
            f" AND ({CURRENT})" if current else f" AND NOT ({CURRENT})"
        )
        values = list(self.values)
        if after is not None:
            where += " AND (o.recorded_at,o.id)<(?,?)"
            values.extend(after)
        sizes = "+".join(
            f"length(CAST(o.{column} AS BLOB))"
            for column in (
                "id",
                "kind",
                "subject",
                "payload",
                "producer",
                "authority",
                "recorded_at",
                "binding_sha256",
                "subject_sha256",
            )
        )
        return self.store.sources._rows(
            f"SELECT o.id,o.recorded_at,({sizes}) AS row_bytes "
            f"FROM {self.join} WHERE {where} ORDER BY o.recorded_at DESC,o.id DESC LIMIT ?",
            [*values, limit],
        )

    def checked(self, header, max_bytes):
        if header["row_bytes"] > max_bytes:
            return None, "report_exceeds_byte_budget"
        links = sum(
            self.conn.execute(
                f"SELECT count(*) FROM {table} WHERE observation_id=?", (header["id"],)
            ).fetchone()[0]
            for table in (
                "context_observation_supersedes",
                "context_observation_sources",
                "context_record_observations",
            )
        )
        if links > MAX_LINKS:
            return None, "dependency_limit"
        # The header was scope-filtered in this transaction. Reuse its predicate,
        # but verify the complete immutable binding of each selected body.
        rows = self.store.sources._rows(
            f"SELECT o.* FROM {self.join} WHERE {self.where} AND o.id=?",
            [*self.values, header["id"]],
        )
        if len(rows) != 1:
            raise ScopeError("Annotation changed within the request")
        row = self.store._checked(
            rows[0], self.policy, self.scope, visible_snapshot=self.visible
        )
        return {
            k: row[k]
            for k in (
                "id",
                "payload",
                "producer",
                "authority",
                "recorded_at",
                "binding_sha256",
                "supersedes",
                "history_incomplete",
            )
        }, None


def page(conn, session_id, *, kind="note", max_bytes=32768, cursor=None, limit=32):
    if type(max_bytes) is not int or not 4096 <= max_bytes <= 131072:
        raise ValueError("Byte budget must be between 4096 and 131072")
    if type(limit) is not int or not 1 <= limit <= 64:
        raise ValueError("History candidate limit must be between 1 and 64")
    with query_budget(conn, steps=VM_STEPS) as work:
        result = _page(Reader(conn, session_id, kind), max_bytes, cursor, limit)
        result["work"]["vm_steps_observed"] = work["vm_steps"]
    if len(_json(result).encode()) > max_bytes:
        raise ValueError("Annotation header exceeds response budget")
    return result


def _page(reader, max_bytes, cursor, limit):
    after = reader.decode(cursor)
    total, count = reader.counts()
    legacy, has_legacy, legacy_reason = reader.legacy(total, max_bytes)
    result = {
        "contract": "session-annotations/v2",
        "session_id": reader.sid,
        "kind": reader.kind,
        "relationship": "about_session",
        "semantic_validation": "not_established",
        "current_count": count + has_legacy,
        "conflicting_current_versions": count > 1,
        "current_group_complete": legacy_reason is None,
        "current_omission_reason": legacy_reason,
        "versions": [],
        "legacy": legacy,
        "legacy_authority": "unattributed_report" if has_legacy else None,
        "coverage": "complete",
        "version_count": total,
        "history_omissions": [],
        "history_candidates": 0,
        "history_continuation": cursor is not None,
        "next_cursor": "x" * 512,
        "work": {
            "vm_step_limit": VM_STEPS,
            "vm_steps_observed": VM_STEPS,
            "current_candidate_limit": MAX_CURRENT,
            "history_candidate_limit": limit,
        },
    }

    def size():
        return len(_json(result).encode())

    # Reserve enough space to disclose at least one historical omission and a
    # continuation. Never sacrifice one side of a current conflict to fit history.
    reserve = 256 if total > count else 0
    if legacy is not None and size() > max_bytes - reserve:
        result.update(
            legacy=None,
            current_group_complete=False,
            current_omission_reason="report_exceeds_byte_budget",
        )
    if cursor is not None and (count or has_legacy):
        result.update(
            legacy=None,
            current_group_complete=False,
            current_omission_reason="history_continuation",
        )
    elif count > MAX_CURRENT:
        result.update(
            current_group_complete=False,
            current_omission_reason="current_candidate_limit",
        )
    else:
        headers = reader.headers(current=True, limit=min(count, MAX_CURRENT))
        for header in headers:
            item, reason = reader.checked(header, max_bytes)
            if item is None:
                result.update(
                    current_group_complete=False, current_omission_reason=reason
                )
                break
            item["current"] = True
            result["versions"].append(item)
            if size() > max_bytes - reserve:
                result.update(
                    current_group_complete=False,
                    current_omission_reason="current_group_exceeds_byte_budget",
                )
                break
        if not result["current_group_complete"]:
            result["versions"].clear()
    history = reader.headers(current=False, limit=limit + 1, after=after)
    processed = 0
    last = None
    for header in history[:limit]:
        item, reason = reader.checked(header, max_bytes)
        included = False
        if item is not None:
            item["current"] = False
            result["versions"].append(item)
            included = size() <= max_bytes
            if not included:
                result["versions"].pop()
                reason = "page_byte_budget"
        if not included and reason == "page_byte_budget":
            # Retry this candidate on a fresh history-only page. An item larger
            # than an empty page is instead disclosed once and advances the key.
            if processed or (
                cursor is None and any(v["current"] for v in result["versions"])
            ):
                break
            reason = "report_exceeds_byte_budget"
        if not included:
            result["history_omissions"].append({"id": header["id"], "reason": reason})
            if size() > max_bytes:
                result["history_omissions"].pop()
                break
        processed += 1
        last = header
    result["history_candidates"] = processed
    more = processed < len(history)
    if more and last is None and cursor is not None:
        raise ValueError(
            "Annotation page cannot fit continuation metadata; increase max_bytes"
        )
    result["next_cursor"] = reader.encode(last) if more else None
    if (
        more
        or cursor
        or result["history_omissions"]
        or not result["current_group_complete"]
    ):
        result["coverage"] = "partial"
    return result
