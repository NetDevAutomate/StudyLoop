"""Run the installed replica content phase against two fictional databases."""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

from agent_session_tools.context import annotations, records
from agent_session_tools.context.observations import ObservationStore
from agent_session_tools.context.provenance import Origin
from agent_session_tools.context.scope import ScopePolicy, apply_policy
from agent_session_tools.context.store import ContextStore, NativeSource
from agent_session_tools.replication import snapshot as projection
from agent_session_tools.replication.content import ReplicaConflict, apply_content
from agent_session_tools.replication.policy import PeerPolicy, ReplicaError, hello, negotiate

WORK_MARKER = "WORK_ONLY_FIXTURE_DO_NOT_TRANSFER"


def run(root, require_installed=False):
    module = Path(projection.__file__).resolve()
    if require_installed and "site-packages" not in module.parts:
        raise RuntimeError("Probe requires an installed memory wheel")
    root.mkdir(parents=True, exist_ok=False)
    peers = {}
    for node, other in (("laptop", "mini"), ("mini", "laptop")):
        config = {
            "memory": {
                "default_scope": "personal",
                "projects": {
                    "learning": {"scope": "personal", "roots": [str(root / node / "learning")]},
                    "job": {"scope": "work", "roots": [str(root / node / "job")]},
                },
                "sync": {"node_id": node, "peers": {other: {"allowed_scopes": ["personal"]}}},
            }
        }
        config_path = root / f"{node}.json"
        config_path.write_text(json.dumps(config, indent=2))
        path = root / f"{node}.db"
        conn = records.connect(path)
        apply_policy(conn, ScopePolicy.from_config(config), actor="fixture", dry_run=False)
        peers[node] = (conn, path, config)
    source, source_path, source_config = peers["laptop"]
    target, target_path, target_config = peers["mini"]
    os.environ["STUDYLOOP_CONFIG"] = str(root / "laptop.json")
    os.environ["SESSION_CONTEXT_SCOPE"] = "personal"
    try:
        for sid, project, text in (
            ("learn", "learning", "Fixture: local test was reported"),
            ("job", "job", WORK_MARKER),
        ):
            source.execute(
                "INSERT INTO sessions(id,source,project_path) VALUES (?,?,?)",
                (sid, "codex", source_config["memory"]["projects"][project]["roots"][0]),
            )
            source.execute(
                "INSERT INTO messages(id,session_id,role,content) VALUES (?,?,?,?)",
                (sid + "-m", sid, "assistant", text),
            )
        source.commit()
        apply_policy(source, ScopePolicy.from_config(source_config), actor="fixture", dry_run=False)
        store = ContextStore(source)
        ids = {}
        for sid, text in (("learn", "Fixture: local test was reported"), ("job", WORK_MARKER)):
            ids[sid] = store.capture(
                NativeSource(
                    session_id=sid,
                    native_key=sid + "-m",
                    harness="codex",
                    native_kind="message",
                    native_locator="fixture.jsonl:1",
                    parser_version="fixture",
                    machine_id="laptop",
                    body=text,
                    origin=Origin.CONVERSATION,
                )
            )
        with store._atomic(), records.policy_guard(source):
            bridge = source.execute(
                "INSERT INTO knowledge_bridges(source_concept,source_domain,"
                "target_concept,target_domain) "
                "VALUES ('withdrawal','network','forgetting','memory')"
            )
            owner = records.bind(source, "knowledge_bridges", bridge.lastrowid, session_id="learn")
            report = ObservationStore(source).append(
                kind="fixture.explanation",
                subject="lesson",
                payload={"explanation": "A withdrawal removes a previously available route."},
                producer="fixture",
                authority="reported",
                owner_session_id="learn",
            )
            records.link_observation(source, owner, report)
            old_note = annotations.write(
                source, "learn", "note", {"notes": "Initial fixture report"}
            )
            current_note = annotations.write(
                source,
                "learn",
                "note",
                {"notes": "Corrected fixture report; evidence remains reported"},
            )
        target.execute(
            "INSERT INTO knowledge_bridges(source_concept,source_domain,"
            "target_concept,target_domain) "
            "VALUES ('local','fixture','row','fixture')"
        )
        target.commit()

        def current_plan():
            source.rollback()
            target.rollback()
            return negotiate(
                hello(source, PeerPolicy.from_config(source_config, "mini")),
                hello(target, PeerPolicy.from_config(target_config, "laptop")),
            )

        plan = current_plan()
        start = time.perf_counter()
        packet = projection.export_snapshot(source_path, source_config, plan, "personal")
        projected_ms = (time.perf_counter() - start) * 1000
        encoded = json.dumps(packet, ensure_ascii=False, separators=(",", ":"))
        (root / "content-snapshot.json").write_text(encoded)
        start = time.perf_counter()
        outcome = apply_content(target_path, target_config, packet)
        imported_ms = (time.perf_counter() - start) * 1000
        mapped = target.execute(
            "SELECT row_id FROM context_record_owners WHERE id=?", (owner,)
        ).fetchone()[0]
        original_hash = source.execute(
            "SELECT binding_sha256 FROM context_observations WHERE id=?", (report,)
        ).fetchone()[0]
        copied_hash = target.execute(
            "SELECT binding_sha256 FROM context_observations WHERE id=?", (report,)
        ).fetchone()[0]
        retirement_link = target.execute(
            "SELECT previous_id FROM context_observation_supersedes WHERE observation_id=?",
            (current_note,),
        ).fetchone()[0]
        source_hash = target.execute(
            "SELECT body_sha256 FROM context_evidence WHERE id=?", (ids["learn"],)
        ).fetchone()[0]
        repeat = projection.export_snapshot(source_path, source_config, current_plan(), "personal")
        apply_content(target_path, target_config, repeat)
        count_after_repeat = target.execute("SELECT count(*) FROM knowledge_bridges").fetchone()[0]

        target.execute(
            "UPDATE knowledge_bridges SET quality='local concurrent edit' WHERE id=?", (mapped,)
        )
        target.commit()
        source.execute(
            "INSERT INTO messages(id,session_id,role,content) "
            "VALUES ('later','learn','user','body in failed content phase')"
        )
        source.commit()
        incoming = projection.export_snapshot(
            source_path, source_config, current_plan(), "personal"
        )
        conflict = None
        try:
            apply_content(target_path, target_config, incoming)
        except ReplicaConflict as exc:
            conflict = str(exc)

        stale_plan = current_plan()
        source.execute(
            "UPDATE context_session_projects SET project_id='job' WHERE session_id='learn'"
        )
        source.commit()
        stale = None
        try:
            projection.export_snapshot(source_path, source_config, stale_plan, "personal")
        except ReplicaError as exc:
            stale = str(exc)
        checks = {
            "reciprocal_scope_agreement_with_different_local_roots": plan["projects"]
            == {"learning": "personal"},
            "excluded_marker_absent_from_staged_payload": WORK_MARKER not in encoded,
            "excluded_marker_absent_from_destination_files": all(
                WORK_MARKER.encode() not in p.read_bytes() for p in root.glob("mini.db*")
            ),
            "native_hash_matches_original_body": source_hash
            == hashlib.sha256(b"Fixture: local test was reported").hexdigest(),
            "immutable_report_binding_preserved": original_hash == copied_hash,
            "correction_link_preserved": retirement_link == old_note,
            "integer_identity_remapped_without_overwrite": mapped == "2"
            and target.execute(
                "SELECT source_concept FROM knowledge_bridges WHERE id=1"
            ).fetchone()[0]
            == "local",
            "identical_retry_is_idempotent": count_after_repeat == 2,
            "divergence_rolls_back_whole_content_phase": conflict is not None
            and not target.execute("SELECT 1 FROM messages WHERE id='later'").fetchone(),
            "stale_negotiation_refused": stale is not None,
            "foreign_keys_intact": target.execute("PRAGMA foreign_key_check").fetchall() == [],
            "incomplete_sync_is_explicit": outcome["sync_complete"] is False
            and outcome["lifecycle_reconciled"] is False,
        }
        if not all(checks.values()):
            raise RuntimeError("Content-phase probe failed: " + str(checks))
        result = {
            "negotiation": plan,
            "projection": {
                "scope": "personal",
                "rows": {t: len(rows) for t, rows in packet["tables"].items()},
                "encoded_bytes": len(encoded.encode()),
                "excluded_marker_absent": True,
            },
            "import": {
                **outcome,
                "source_local_row": 1,
                "destination_local_row": int(mapped),
                "report_binding_preserved": original_hash == copied_hash,
            },
            "conflict": {"message": conflict, "later_message_committed": False},
            "stale_negotiation": {"message": stale},
            "checks": checks,
            "timing": {
                "single_export_ms": round(projected_ms, 3),
                "single_import_ms": round(imported_ms, 3),
            },
            "runtime": {"module": str(module), "require_installed": require_installed},
            "limits": (
                "Fictional real-schema content phase only. No SSH coordination, retirement "
                "reconciliation, legacy global-state coverage, managed restore or full sync "
                "acceptance is claimed. Conflict refusal preserves originals "
                "but is not convergence."
            ),
        }
        (root / "results.json").write_text(json.dumps(result, indent=2))
        return result
    finally:
        source.close()
        target.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--require-installed", action="store_true")
    args = parser.parse_args()
    result = run(args.output.resolve(), args.require_installed)
    print(json.dumps({"checks": result["checks"], "output": str(args.output)}))


if __name__ == "__main__":
    main()
