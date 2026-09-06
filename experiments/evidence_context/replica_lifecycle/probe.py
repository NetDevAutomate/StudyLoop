"""Exercise installed native capture, offers, receipts and known-recipient forgetting."""

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from agent_session_tools.context import annotations, records
from agent_session_tools.context.scope import ScopePolicy, apply_policy
from agent_session_tools.context.store import ContextStore
from agent_session_tools.exporters.codex import CodexExporter
from agent_session_tools.replication import ledger
from agent_session_tools.replication.policy import PeerPolicy, hello, negotiate


def run(output, require_installed):
    if require_installed and (
        "site-packages" not in ledger.__file__ or importlib.util.find_spec("studyloop") is not None
    ):
        raise RuntimeError("An installed standalone memory runtime without StudyLoop is required")
    output.mkdir(parents=True, exist_ok=False)
    replicas = {}
    for node, peer in (("laptop", "mini"), ("mini", "laptop")):
        config = {
            "memory": {
                "default_scope": "personal",
                "projects": {
                    k: {"scope": v, "roots": [str(output / node / v)]}
                    for k, v in (("p", "personal"), ("w", "work"))
                },
                "sync": {"node_id": node, "peers": {peer: {"allowed_scopes": ["personal"]}}},
            }
        }
        cfg = output / (node + ".json")
        cfg.write_text(json.dumps(config))
        path = output / (node + ".db")
        conn = records.connect(path)
        apply_policy(conn, ScopePolicy.from_config(config), actor="fictional lesson", dry_run=False)
        replicas[node] = {"config": config, "cfg": cfg, "path": path, "conn": conn}
    a, b = replicas["laptop"], replicas["mini"]
    os.environ["STUDYLOOP_CONFIG"] = str(a["cfg"])
    os.environ["SESSION_CONTEXT_SCOPE"] = "personal"
    archives = output / "native-laptop"
    archives.mkdir()
    for scope in ("personal", "work"):
        rows = [
            {"type": "session_meta", "payload": {"cwd": str(output / "laptop" / scope)}},
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "STAGE34_" + scope.upper() + "_CONVERSATION"}
                    ],
                },
            },
        ]
        (archives / ("rollout-" + scope + ".jsonl")).write_text(
            "".join(json.dumps(r) + "\n" for r in rows)
        )
    original = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in archives.iterdir()}
    captured = CodexExporter(archives).export_all(a["conn"])
    sid = "codex_rollout-personal"
    with ContextStore(a["conn"])._atomic(), records.policy_guard(a["conn"]):
        first = annotations.write(a["conn"], sid, "note", {"notes": "STAGE34_PERSONAL_OLD_NOTE"})
        second = annotations.write(
            a["conn"], sid, "note", {"notes": "STAGE34_PERSONAL_CORRECTED_NOTE"}
        )
    plan = negotiate(
        hello(a["conn"], PeerPolicy.from_config(a["config"], "mini")),
        hello(b["conn"], PeerPolicy.from_config(b["config"], "laptop")),
    )
    started = time.perf_counter()
    offered = ledger.prepare_offer(a["path"], a["config"], plan, "personal")
    acceptance = ledger.accept_offer(b["path"], b["config"], "laptop", offered)
    metadata_only = not b["conn"].execute("SELECT 1 FROM sessions").fetchone()
    receiver_registered = bool(
        b["conn"].execute("SELECT 1 FROM context_replica_objects").fetchone()
    )
    ledger.record_acceptance(a["path"], a["config"], "mini", offered, acceptance)
    sender_registered = bool(a["conn"].execute("SELECT 1 FROM context_replica_objects").fetchone())
    snapshot = ledger.release_content(a["path"], a["config"], "mini", offered)
    receipt = ledger.receive_content(b["path"], b["config"], "laptop", offered["id"], snapshot)
    repeated = ledger.receive_content(b["path"], b["config"], "laptop", offered["id"], snapshot)
    ledger.acknowledge_content(a["path"], a["config"], "mini", repeated)
    delivery_ms = round((time.perf_counter() - started) * 1000, 3)
    source_links = (
        b["conn"].execute("SELECT count(*) FROM context_native_message_sources").fetchone()[0]
    )
    sender_ack = (
        a["conn"]
        .execute("SELECT status FROM context_replica_offers WHERE direction='out'")
        .fetchone()[0]
    )
    cli = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "agent_session_tools.context.cli",
            "forget",
            sid,
            "--apply",
            "--db",
            str(a["path"]),
        ],
        text=True,
        capture_output=True,
        timeout=30,
    )
    if cli.returncode:
        raise RuntimeError(cli.stderr or cli.stdout)
    local_forget = json.loads(cli.stdout)
    controls = ledger.prepare_controls(a["path"], a["config"], "mini")
    retired = ledger.apply_controls(b["path"], b["config"], "laptop", controls)
    acknowledgement = ledger.acknowledge_controls(a["path"], a["config"], "mini", retired)
    # The old receipt remains evidence of a past commit. It cannot recreate bodies.
    historical = ledger.receive_content(b["path"], b["config"], "laptop", offered["id"], snapshot)
    source_gone = not b["conn"].execute("SELECT 1 FROM sessions").fetchone()
    notes_gone = not b["conn"].execute("SELECT 1 FROM context_observations").fetchone()
    old_archive = output / "native-mini-replay"
    old_archive.mkdir()
    shutil.copy2(archives / "rollout-personal.jsonl", old_archive / "rollout-personal.jsonl")
    replay = CodexExporter(old_archive).export_all(b["conn"], incremental=False)
    correction = (
        b["conn"]
        .execute(
            "SELECT previous_id FROM context_observation_supersedes WHERE observation_id=?",
            (second,),
        )
        .fetchone()
    )
    files = list(output.glob("mini.db*"))
    checks = {
        "actual_native_capture": captured.added == 2 and captured.errors == 0,
        "offer_is_not_data_receipt": metadata_only,
        "offer_contains_no_body_markers": "STAGE34_" not in json.dumps(offered),
        "offer_excludes_work_identity": "codex_rollout-work" not in json.dumps(offered),
        "receiver_registration_durable": receiver_registered,
        "sender_recipient_recorded_before_release": sender_registered,
        "native_source_rendering_binding_preserved": source_links == 1,
        "lost_receipt_recovered": repeated == receipt,
        "sender_acknowledgement_persisted": sender_ack == "acknowledged",
        "actual_local_forget_cli": local_forget["applied"],
        "controls_only_known_scope": bool(controls["retirements"])
        and all(r["scope"] == "personal" for r in controls["retirements"]),
        "replica_source_and_annotations_purged": source_gone and notes_gone,
        "remote_cleanup_acknowledged": acknowledgement["acknowledged"],
        "historical_receipt_does_not_restore": historical == receipt and source_gone,
        "actual_native_replay_suppressed": replay.forgotten == 1 and replay.errors == 0,
        "canonical_forgotten_marker_absent": all(
            b"STAGE34_PERSONAL_" not in f.read_bytes() for f in files
        ),
        "excluded_work_marker_absent": all(b"STAGE34_WORK_" not in f.read_bytes() for f in files),
        "original_native_archives_unchanged": original
        == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in archives.iterdir()},
        "content_free_correction_link_retained": correction is not None and correction[0] == first,
        "full_sync_remains_explicitly_incomplete": acknowledgement["sync_complete"] is False,
    }
    result = {
        "offer": {
            "id": offered["id"],
            "objects": offered["objects"],
            "scope": offered["scope"],
            "contains_bodies": False,
        },
        "acceptance": acceptance,
        "delivery": {"receipt": receipt, "lost_receipt_recovered": repeated == receipt},
        "forget": {"local": local_forget, "routed_controls": controls["retirements"]},
        "replica_result": {
            "receipt": retired,
            "acknowledgement": acknowledgement,
            "native_replay_forgotten": replay.forgotten,
        },
        "checks": checks,
        "timing": {
            "single_local_offer_delivery_receipt_ms": delivery_ms,
            "limit": "One fictional local run; excludes SSH "
            "and is not a throughput or engine benchmark.",
        },
        "limits": "Known-recipient canonical retirement only. "
        "Real SSH/session-sync coordinator, permission withdrawal/regrant, "
        "managed full-store/restore and unknown legacy delivery coverage remain unproved. "
        "Native fixture archives intentionally remain outside canonical erasure.",
        "runtime": {"module": ledger.__file__, "require_installed": require_installed},
    }
    for item in replicas.values():
        item["conn"].close()
    (output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    if not all(checks.values()):
        raise RuntimeError("Lifecycle demo failed: " + str([k for k, v in checks.items() if not v]))
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
