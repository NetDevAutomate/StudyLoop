"""Run actual withdrawal/regrant operations against disposable fictional replicas."""

import argparse
import importlib.util
import json
import os
import time
from pathlib import Path

from agent_session_tools.context import records
from agent_session_tools.context.lifecycle import forget_session
from agent_session_tools.context.provenance import Scope
from agent_session_tools.context.scope import ScopePolicy, apply_policy
from agent_session_tools.context.store import Access, ContextStore
from agent_session_tools.exporters.codex import CodexExporter
from agent_session_tools.replication import ledger, permissions
from agent_session_tools.replication.policy import PeerPolicy, ReplicaError, hello, negotiate


def run(output, require_installed):
    if require_installed and (
        "site-packages" not in permissions.__file__
        or importlib.util.find_spec("studyloop") is not None
    ):
        raise RuntimeError("A standalone installed memory wheel without StudyLoop is required")
    output.mkdir(parents=True, exist_ok=False)
    peers = {}
    for node, peer in (("laptop", "mini"), ("mini", "laptop")):
        config = {
            "memory": {
                "default_scope": "personal",
                "projects": {"lesson": {"scope": "personal", "roots": [str(output / "project")]}},
                "sync": {"node_id": node, "peers": {peer: {"allowed_scopes": ["personal"]}}},
            }
        }
        cfg = output / (node + ".json")
        cfg.write_text(json.dumps(config))
        path = output / (node + ".db")
        conn = records.connect(path)
        apply_policy(conn, ScopePolicy.from_config(config), actor="fictional lesson", dry_run=False)
        peers[node] = {"config": config, "cfg": cfg, "path": path, "conn": conn}
    a, b = peers["laptop"], peers["mini"]
    os.environ["STUDYLOOP_CONFIG"] = str(a["cfg"])
    os.environ["SESSION_CONTEXT_SCOPE"] = "personal"
    native = output / "native"
    native.mkdir()
    events = [
        {"type": "session_meta", "payload": {"cwd": str(output / "project")}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "STAGE36_SHARED: preserve the source of a validation result.",
                    }
                ],
            },
        },
    ]
    (native / "rollout-lesson.jsonl").write_text("".join(json.dumps(v) + "\n" for v in events))
    exporter = CodexExporter(native)
    imported = exporter.export_all(a["conn"])
    sid = "codex_rollout-lesson"

    def prepare():
        plan = negotiate(
            hello(a["conn"], PeerPolicy.from_config(a["config"], "mini")),
            hello(b["conn"], PeerPolicy.from_config(b["config"], "laptop")),
        )
        offer = ledger.prepare_offer(a["path"], a["config"], plan, "personal")
        acceptance = ledger.accept_offer(b["path"], b["config"], "laptop", offer)
        ledger.record_acceptance(a["path"], a["config"], "mini", offer, acceptance)
        body = ledger.release_content(a["path"], a["config"], "mini", offer)
        return offer, body

    def deliver():
        offer, body = prepare()
        receipt = ledger.receive_content(b["path"], b["config"], "laptop", offer["id"], body)
        return offer, body, receipt

    def change(action):
        packet = permissions.prepare_change(a["path"], a["config"], "mini", "personal", action)
        receipt = permissions.apply_change(b["path"], b["config"], "laptop", packet)
        return packet, receipt

    def count(table):
        return b["conn"].execute("SELECT count(*) FROM " + table).fetchone()[0]

    try:
        first, body, first_receipt = deliver()
        eid = b["conn"].execute("SELECT id FROM context_evidence LIMIT 1").fetchone()[0]
        received = {
            "permission_generation": first["generation"],
            "session_count": count("sessions"),
            "committed": first_receipt["committed"],
        }
        started = time.perf_counter()
        withdrawal, erased = change("withdraw")
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        gone = count("sessions") == 0
        permanent_count = count("context_retirements")
        os.environ["STUDYLOOP_CONFIG"] = str(b["cfg"])
        native_attempt = exporter.export_all(b["conn"], incremental=False)
        repeated = ledger.receive_content(b["path"], b["config"], "laptop", first["id"], body)
        replay_empty = count("sessions") == 0
        grant, grant_receipt = change("regrant")
        awaiting = count("sessions") == 0
        fresh, _, _ = deliver()
        restored = count("sessions") == 1
        regrant_view = {
            "generation": grant["generation"],
            "control_receipt": grant_receipt,
            "control_alone_left_empty": awaiting,
            "fresh_transfer_generation": fresh["generation"],
            "fresh_transfer_restored": restored,
        }
        b["conn"].execute(
            "INSERT INTO messages(id,session_id,role,content) VALUES ('local-extra',?,'user',?)",
            (sid, "STAGE36_LOCAL: this was never in the sender packet"),
        )
        b["conn"].commit()
        _, quarantined = change("withdraw")
        retained = count("messages") == 2
        hidden = ContextStore(b["conn"]).source(eid, Access(scope=Scope.PERSONAL)) is None
        b["conn"].rollback()
        change("regrant")
        offered, packet = prepare()
        rejected = False
        try:
            ledger.receive_content(b["path"], b["config"], "laptop", offered["id"], packet)
        except ReplicaError as exc:
            rejected = "does not cover" in str(exc)
        still_hidden = ContextStore(b["conn"]).source(eid, Access(scope=Scope.PERSONAL)) is None
        b["conn"].rollback()
        extra_retained = (
            b["conn"].execute("SELECT 1 FROM messages WHERE id='local-extra'").fetchone()
            is not None
        )
        forgotten = forget_session(b["conn"], sid, apply=True)
        native_after_forget = exporter.export_all(b["conn"], incremental=False)
        checks = {
            "actual_native_import": imported.added == 1 and imported.errors == 0,
            "initial_delivery_commits": received["committed"] and received["session_count"] == 1,
            "first_withdrawal_generation": withdrawal["generation"] == 1,
            "exclusive_peer_copy_erased": gone and erased["canonical_cleanup"]["complete"],
            "withdrawal_is_not_permanent_forget": permanent_count == 0,
            "native_archive_does_not_regrant": native_attempt.withdrawn == 1,
            "historical_receipt_does_not_reinsert": repeated == first_receipt and replay_empty,
            "regrant_control_does_not_expose": awaiting,
            "fresh_offer_binds_generation": fresh["generation"] == 2,
            "fresh_delivery_restores": restored,
            "ambiguous_local_body_retained": retained,
            "ambiguous_cleanup_explicitly_incomplete": not quarantined["canonical_cleanup"][
                "complete"
            ],
            "quarantine_hidden_from_context": hidden,
            "fresh_offer_cannot_expose_unoffered_body": rejected and still_hidden,
            "failed_regrant_preserves_local_extra": extra_retained,
            "permanent_forget_still_works": forgotten["applied"] and count("sessions") == 0,
            "forgotten_archive_stays_forgotten": native_after_forget.forgotten == 1
            and native_after_forget.withdrawn == 0,
            "full_sync_never_claimed": not erased["sync_complete"]
            and not grant_receipt["sync_complete"],
        }
        result = {
            "received": received,
            "withdrawal": erased,
            "regrant": regrant_view,
            "quarantine": {
                "receipt": quarantined,
                "bytes_retained": retained,
                "context_hidden": hidden,
            },
            "coverage": {
                "fresh_transfer_rejected": rejected,
                "still_hidden": still_hidden,
                "local_extra_retained": extra_retained,
            },
            "forget": {
                "applied": forgotten["applied"],
                "native_replay_suppressed": native_after_forget.forgotten,
            },
            "checks": checks,
            "timing": {
                "one_local_withdrawal_ms": elapsed_ms,
                "limit": "One fictional canonical database run; includes compaction, "
                "excludes SSH, full store, scale and engine comparison.",
            },
            "limits": "Ordered local protocol only. Ambiguous retention remains quarantined "
            "without an operator reconciliation/adoption path. No full-store, managed restore, "
            "authenticated SSH coordinator or complete production sync claim.",
            "runtime": {"module": permissions.__file__, "require_installed": require_installed},
        }
        (output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
        if not all(checks.values()):
            raise RuntimeError(
                "Withdrawal lesson failed: " + str([k for k, v in checks.items() if not v])
            )
        return result
    finally:
        for peer in peers.values():
            peer["conn"].close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-installed", action="store_true")
    args = parser.parse_args()
    result = run(args.output.resolve(), args.require_installed)
    print(json.dumps({"checks": result["checks"], "output": str(args.output.resolve())}))


if __name__ == "__main__":
    main()
