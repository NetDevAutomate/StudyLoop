"""Exercise real native capture and peer contribution records with fictional data."""

import argparse
import importlib.util
import json
import os
import time
from pathlib import Path

from agent_session_tools.context import records
from agent_session_tools.context.lifecycle import forget_session
from agent_session_tools.context.scope import ScopePolicy, apply_policy
from agent_session_tools.exporters.codex import CodexExporter
from agent_session_tools.replication import ledger, retention
from agent_session_tools.replication.policy import PeerPolicy, hello, negotiate


def run(output, require_installed):
    if require_installed and (
        "site-packages" not in retention.__file__
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
        db = output / (node + ".db")
        conn = records.connect(db)
        apply_policy(conn, ScopePolicy.from_config(config), actor="fictional lesson", dry_run=False)
        peers[node] = {"config": config, "cfg": cfg, "path": db, "conn": conn}
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
                        "text": "STAGE35_BODY: keep the validation failure with its source.",
                    }
                ],
            },
        },
    ]
    (native / "rollout-lesson.jsonl").write_text("".join(json.dumps(v) + "\n" for v in events))
    exporter = CodexExporter(native)
    imported = exporter.export_all(a["conn"])
    sid = "codex_rollout-lesson"

    def evidence(node):
        row = dict(node["conn"].execute("SELECT * FROM context_evidence LIMIT 1").fetchone())
        return retention.describe(node["conn"], "context_evidence", row)

    local = evidence(a)
    plan = negotiate(
        hello(a["conn"], PeerPolicy.from_config(a["config"], "mini")),
        hello(b["conn"], PeerPolicy.from_config(b["config"], "laptop")),
    )
    started = time.perf_counter()
    offer = ledger.prepare_offer(a["path"], a["config"], plan, "personal")
    accepted = ledger.accept_offer(b["path"], b["config"], "laptop", offer)
    after_offer = b["conn"].execute("SELECT count(*) FROM context_retention_origins").fetchone()[0]
    ledger.record_acceptance(a["path"], a["config"], "mini", offer, accepted)
    snapshot = ledger.release_content(a["path"], a["config"], "mini", offer)
    receipt = ledger.receive_content(b["path"], b["config"], "laptop", offer["id"], snapshot)
    received = evidence(b)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    count = b["conn"].execute("SELECT count(*) FROM context_retention_origins").fetchone()[0]
    repeat = ledger.receive_content(b["path"], b["config"], "laptop", offer["id"], snapshot)
    count_after = b["conn"].execute("SELECT count(*) FROM context_retention_origins").fetchone()[0]
    # Same logical row ID, deliberately changed body. Old receipts do not match.
    message = dict(b["conn"].execute("SELECT * FROM messages LIMIT 1").fetchone())
    before = retention.describe(b["conn"], "messages", message)
    message["content"] = "STAGE35_CHANGED_BODY"
    b["conn"].execute(
        "UPDATE messages SET content=? WHERE id=?", (message["content"], message["id"])
    )
    b["conn"].commit()
    changed = retention.describe(b["conn"], "messages", message)
    # Inspect factual capture after a real archive re-read; this is not regrant.
    captured_again = exporter.export_all(b["conn"], incremental=False)
    recaptured = evidence(b)
    history = json.dumps(
        [dict(r) for r in b["conn"].execute("SELECT * FROM context_retention_origins")]
    )
    forgotten = forget_session(b["conn"], sid, apply=True)
    historical_count = (
        b["conn"].execute("SELECT count(*) FROM context_retention_origins").fetchone()[0]
    )
    replay = exporter.export_all(b["conn"], incremental=False)
    checks = {
        "actual_native_import": imported.added == 1 and imported.errors == 0,
        "local_capture_fact": local["native_capture_observed"],
        "offer_creates_no_contribution": after_offer == 0,
        "received_contribution_names_peer": received["committed_peers"] == ["laptop"],
        "received_row_is_not_local_capture": not received["native_capture_observed"],
        "local_history_not_in_transfer": "context_retention_origins" not in snapshot["tables"],
        "retry_is_idempotent": repeat == receipt and count_after == count,
        "changed_version_has_unknown_history": changed["unattributed_history"]
        and changed["committed_peers"] == [],
        "version_binding_changes": before["binding"]["row_sha256"]
        != changed["binding"]["row_sha256"],
        "recapture_is_additional_fact": not captured_again.errors
        and recaptured["native_capture_observed"]
        and recaptured["committed_peers"] == ["laptop"],
        "facts_never_authorize_retention": recaptured["retention_authorized"] == "not_evaluated",
        "upstream_independence_not_inferred": received["independent_upstream_origins"]
        == "not_established",
        "history_contains_no_body_or_path": "STAGE35_" not in history
        and str(output) not in history,
        "permanent_forget_overrides_historical_capture": forgotten["applied"]
        and replay.forgotten == 1,
        "source_gone_history_retained": not b["conn"].execute("SELECT 1 FROM sessions").fetchone()
        and historical_count > 0,
    }
    result = {
        "local_capture": local,
        "accepted_offer": {"contribution_count": after_offer},
        "committed_delivery": received,
        "changed_version": {"before": before, "after": changed},
        "recapture_and_forget": {
            "capture_facts": recaptured,
            "forgotten": forgotten["applied"],
            "archive_replay_suppressed": replay.forgotten,
        },
        "checks": checks,
        "timing": {
            "single_local_delivery_ms": elapsed_ms,
            "limit": "One fictional local run; no network, throughput or engine comparison.",
        },
        "limits": "Historical capture/delivery facts only. Withdrawal, regrant, "
        "transitive independence, local derivative authorship, managed restore "
        "and real network coordinator remain open. "
        "No authorization is derived from these labels.",
        "runtime": {"module": retention.__file__, "require_installed": require_installed},
    }
    for node in peers.values():
        node["conn"].close()
    (output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    if not all(checks.values()):
        raise RuntimeError(
            "Retention lesson failed: " + str([k for k, v in checks.items() if not v])
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-installed", action="store_true")
    args = parser.parse_args()
    result = run(args.output.resolve(), args.require_installed)
    print(json.dumps({"checks": result["checks"], "output": str(args.output.resolve())}))


if __name__ == "__main__":
    main()
