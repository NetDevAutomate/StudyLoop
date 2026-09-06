"""Exercise the real quarantine CLI against fictional standalone replicas."""

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

from agent_session_tools.context import records
from agent_session_tools.context.scope import ScopePolicy, apply_policy
from agent_session_tools.exporters.codex import CodexExporter
from agent_session_tools.replication import ledger, permissions, quarantine
from agent_session_tools.replication.policy import PeerPolicy, hello, negotiate


def run(output, require_installed):
    if require_installed and (
        "site-packages" not in quarantine.__file__
        or importlib.util.find_spec("studyloop") is not None
    ):
        raise RuntimeError("This check requires an installed memory wheel with StudyLoop absent")
    output.mkdir(parents=True, exist_ok=False)
    nodes = {}
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
        nodes[node] = {"conn": conn, "path": path, "config": config, "cfg": cfg}
    a, b = nodes["laptop"], nodes["mini"]
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
                "content": [{"type": "input_text", "text": "STAGE37_SHARED_SOURCE"}],
            },
        },
    ]
    (native / "rollout-lesson.jsonl").write_text("".join(json.dumps(v) + "\n" for v in events))
    exporter = CodexExporter(native)
    sid = "codex_rollout-lesson"
    cli = Path(sys.executable).with_name("session-context")
    if require_installed and not cli.is_file():
        raise RuntimeError("The installed session-context entry point is missing")
    cli_command = (
        [str(cli)]
        if cli.is_file()
        else [sys.executable, "-I", "-m", "agent_session_tools.context.cli"]
    )

    def command(*args):
        return subprocess.run(
            [*cli_command, "quarantine", *args, "--db", str(b["path"])],
            capture_output=True,
            text=True,
            timeout=20,
        )

    def checked(*args):
        result = command(*args)
        if result.returncode:
            raise RuntimeError(result.stderr)
        return json.loads(result.stdout)

    def deliver():
        plan = negotiate(
            hello(a["conn"], PeerPolicy.from_config(a["config"], "mini")),
            hello(b["conn"], PeerPolicy.from_config(b["config"], "laptop")),
        )
        value = ledger.prepare_offer(a["path"], a["config"], plan, "personal")
        acceptance = ledger.accept_offer(b["path"], b["config"], "laptop", value)
        ledger.record_acceptance(a["path"], a["config"], "mini", value, acceptance)
        body = ledger.release_content(a["path"], a["config"], "mini", value)
        return ledger.receive_content(b["path"], b["config"], "laptop", value["id"], body)

    def change(action):
        packet = permissions.prepare_change(a["path"], a["config"], "mini", "personal", action)
        return permissions.apply_change(b["path"], b["config"], "laptop", packet)

    try:
        imported = exporter.export_all(a["conn"])
        delivered = deliver()
        b["conn"].execute(
            "INSERT INTO messages(id,session_id,role,content) VALUES ('local-extra',?,'user',?)",
            (sid, "STAGE37_PRIVATE_LOCAL_ADDITION"),
        )
        b["conn"].commit()
        withdrawn = change("withdraw")
        retained_count = b["conn"].execute("SELECT count(*) FROM messages").fetchone()[0]
        os.environ["STUDYLOOP_CONFIG"] = str(b["cfg"])
        before = list(b["conn"].iterdump())
        listing = checked("list", "--limit", "2")
        first = checked("inspect", sid)
        read_only = list(b["conn"].iterdump()) == before
        refusal = command("discard", sid, "--expect", first["id"])
        refused_unchanged = list(b["conn"].iterdump()) == before
        change("regrant")
        stale = command("discard", sid, "--expect", first["id"], "--discard-local-additions")
        updated = checked("inspect", sid)
        result = checked("discard", sid, "--expect", updated["id"], "--discard-local-additions")
        gone = b["conn"].execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
        local_gone = (
            b["conn"].execute("SELECT 1 FROM messages WHERE id='local-extra'").fetchone() is None
        )
        no_permanent = not b["conn"].execute("SELECT 1 FROM context_retirements").fetchone()
        native_attempt = exporter.export_all(b["conn"], incremental=False)
        restored = deliver()
        before_retry = list(b["conn"].iterdump())
        replay = checked("discard", sid, "--expect", updated["id"], "--discard-local-additions")
        preserved = list(b["conn"].iterdump()) == before_retry
        count = b["conn"].execute("SELECT count(*) FROM context_quarantine_discards").fetchone()[0]
        checks = {
            "actual_native_capture": imported.added == 1 and imported.errors == 0,
            "initial_content_committed": delivered["committed"],
            "ambiguous_copy_retained": retained_count == 2
            and not withdrawn["canonical_cleanup"]["complete"],
            "actual_cli_lists_withheld_ids": bool(listing["items"])
            and not listing["bodies_included"],
            "preview_does_not_change_database": read_only,
            "preview_contains_no_source_text": "STAGE37_" not in json.dumps(first),
            "loss_acknowledgement_required": refusal.returncode == 2 and refused_unchanged,
            "new_permission_invalidates_old_plan": stale.returncode == 2
            and "stale" in stale.stderr,
            "new_preview_binds_current_state": updated["id"] != first["id"],
            "explicit_discard_commits": result["logical_discard_committed"] and gone,
            "local_addition_loss_is_real": local_gone,
            "discard_is_not_global_forget": no_permanent and not result["permanent_forget"],
            "discard_does_not_regrant": native_attempt.withdrawn == 1 and not result["regrant"],
            "fresh_content_restores_sender_copy": restored["committed"],
            "old_discard_retry_preserves_new_copy": replay == result and preserved,
            "one_durable_operator_decision": count == 1,
            "canonical_cleanup_reported": result["canonical_file_cleanup"]["complete"],
            "full_sync_not_claimed": not result["sync_complete"],
        }
        data = {
            "quarantined": {
                "retained_messages": retained_count,
                "withdrawal_cleanup_complete": withdrawn["canonical_cleanup"]["complete"],
            },
            "preview": {"listing": listing, "plan": first, "database_unchanged": read_only},
            "refusal": {
                "without_acknowledgement_exit": refusal.returncode,
                "old_plan_exit": stale.returncode,
                "new_plan_id": updated["id"],
            },
            "discard": result,
            "recovery": {
                "fresh_content_committed": restored["committed"],
                "old_receipt_replay_preserved_new_copy": preserved,
                "operator_decisions": count,
            },
            "checks": checks,
            "limits": "Deliberate canonical local discard only. Local additions are lost by "
            "explicit choice. Keeping quarantine remains the default. No adoption, extraction, "
            "independent-origin claim, full-store restore or authenticated network sync "
            "is implemented by this command.",
            "runtime": {
                "module": quarantine.__file__,
                "cli_command": cli_command,
                "require_installed": require_installed,
            },
        }
        (output / "results.json").write_text(json.dumps(data, indent=2) + "\n")
        if not all(checks.values()):
            raise RuntimeError(
                "Quarantine recovery checks failed: " + str([k for k, v in checks.items() if not v])
            )
        return data
    finally:
        for node in nodes.values():
            node["conn"].close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-installed", action="store_true")
    args = parser.parse_args()
    result = run(args.output.resolve(), args.require_installed)
    print(json.dumps({"checks": result["checks"], "output": str(args.output.resolve())}))


if __name__ == "__main__":
    main()
