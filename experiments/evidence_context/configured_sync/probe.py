"""Fictional databases, disposable keys and a loopback SSH forced command."""

import argparse
import getpass
import importlib.util
import json
import os
import shlex
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

from agent_session_tools.context import records
from agent_session_tools.context.lifecycle import purge_session
from agent_session_tools.context.scope import ScopePolicy, apply_policy
from agent_session_tools.context.store import ContextStore
from agent_session_tools.exporters.codex import CodexExporter
from agent_session_tools.replication import coordinator, ssh


def run(output, require_installed):
    if require_installed and (
        "site-packages" not in coordinator.__file__
        or importlib.util.find_spec("studyloop") is not None
    ):
        raise RuntimeError("An installed standalone wheel with StudyLoop absent is required")
    output.mkdir(parents=True, exist_ok=False)
    cli = Path(sys.executable).with_name("session-sync")
    if require_installed and not cli.is_file():
        raise RuntimeError("Installed session-sync executable is missing")
    cli_command = (
        [str(cli)] if cli.is_file() else [sys.executable, "-I", "-m", "agent_session_tools.sync"]
    )
    nodes = {}
    for name, peer in (("laptop", "mini"), ("mini", "laptop")):
        root = output / name
        root.mkdir()
        config = {
            "database": {"path": str(root / "sessions.db")},
            "logging": {"path": str(root / "session.log"), "level": "WARNING"},
            "memory": {
                "default_scope": "personal",
                "projects": {
                    scope: {"scope": scope, "roots": [str(root / scope)]}
                    for scope in ("personal", "work")
                },
                "sync": {"node_id": name, "peers": {peer: {"allowed_scopes": ["personal"]}}},
            },
        }
        cfg = root / "config.json"
        cfg.write_text(json.dumps(config))
        os.environ["STUDYLOOP_CONFIG"] = str(cfg)
        os.environ["SESSION_CONTEXT_SCOPE"] = "personal"
        with closing(records.connect(root / "sessions.db")) as conn:
            apply_policy(
                conn, ScopePolicy.from_config(config), actor="fictional SSH lesson", dry_run=False
            )
            native = root / "native"
            native.mkdir()
            for scope in ("personal", "work"):
                events = [
                    {"type": "session_meta", "payload": {"cwd": str(root / scope)}},
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": f"STAGE38_{name}_{scope}"}],
                        },
                    },
                ]
                (native / f"rollout-{name}-{scope}.jsonl").write_text(
                    "".join(json.dumps(v) + "\n" for v in events)
                )
            assert CodexExporter(native).export_all(conn).added == 2
        nodes[name] = {"config": config, "cfg": cfg, "db": root / "sessions.db"}
    laptop, mini = nodes["laptop"], nodes["mini"]

    def count(node, owner, scope):
        with closing(sqlite3.connect(node["db"])) as conn:
            return conn.execute(
                "SELECT count(*) FROM messages WHERE content=?", (f"STAGE38_{owner}_{scope}",)
            ).fetchone()[0]

    def invoke(*args, expected=0):
        result = subprocess.run(
            [*cli_command, *args],
            env={**os.environ, "STUDYLOOP_CONFIG": str(laptop["cfg"])},
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != expected:
            raise RuntimeError(
                f"CLI {args[0]} exit {result.returncode}: "
                f"{result.stdout[:1200]} {result.stderr[:400]}"
            )
        return result.stdout

    with tempfile.TemporaryDirectory(
        prefix=".session-replica-ssh-lesson-", dir=Path.home()
    ) as private:
        auth = Path(private)
        for name in ("host_key", "client_key", "wrong_host"):
            subprocess.run(
                ["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(auth / name)],
                check=True,
                capture_output=True,
            )
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        forced = shlex.join(
            [
                "/usr/bin/env",
                "STUDYLOOP_CONFIG=" + str(mini["cfg"]),
                "SESSION_CONTEXT_SCOPE=personal",
                *cli_command,
                "serve",
                "--peer",
                "laptop",
            ]
        )
        escaped = forced.replace("\\", "\\\\").replace('"', '\\"')
        authorized = auth / "authorized_keys"
        authorized.write_text(
            'restrict,command="' + escaped + '" ' + (auth / "client_key.pub").read_text()
        )
        authorized.chmod(0o600)
        public = (auth / "host_key.pub").read_text().split()
        known = auth / "known_hosts"
        known_text = f"[127.0.0.1]:{port} {public[0]} {public[1]}\n"
        known.write_text(known_text)
        server_config = auth / "sshd_config"
        server_config.write_text(f"""Port {port}
ListenAddress 127.0.0.1
HostKey {auth}/host_key
PidFile {auth}/sshd.pid
AuthorizedKeysFile {authorized}
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
UsePAM no
StrictModes yes
AllowUsers {getpass.getuser()}
LogLevel ERROR
""")
        laptop["config"]["memory"]["sync"]["peers"]["mini"]["ssh"] = {
            "host": "127.0.0.1",
            "user": getpass.getuser(),
            "port": port,
            "identity_file": str(auth / "client_key"),
            "known_hosts": str(known),
        }
        laptop["cfg"].write_text(json.dumps(laptop["config"]))
        with (output / "ssh-server.log").open("w") as log:
            daemon = subprocess.Popen(
                ["/usr/sbin/sshd", "-D", "-e", "-f", str(server_config)], stdout=log, stderr=log
            )
            try:
                for _ in range(100):
                    if daemon.poll() is not None:
                        raise RuntimeError("Disposable sshd did not start; inspect its private log")
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=0.05):
                            break
                    except OSError:
                        time.sleep(0.02)
                first = json.loads(invoke("push", "mini"))
                repeated = json.loads(invoke("push", "mini"))
                initial_checks = {
                    "actual_cli_ssh_transfer": count(mini, "laptop", "personal") == 1,
                    "excluded_work_never_transferred": count(mini, "laptop", "work") == 0,
                    "unchanged_retry_sends_no_body": not repeated["transfers"]
                    and bool(repeated["unchanged"]),
                }
                all_output = invoke("all")
                both = count(laptop, "mini", "personal") == 1 and count(laptop, "mini", "work") == 0
                queued = json.loads(
                    invoke("permission", "mini", "--scope", "personal", "--action", "withdraw")
                )
                withdrawn = json.loads(invoke("push", "mini"))
                withdrawal_checks = {
                    "explicit_permission_queued": queued["queued"]
                    and not queued["delivery_acknowledged"]
                    and not queued["network_attempted"],
                    "withdrawal_applied_before_bodies": count(mini, "laptop", "personal") == 0
                    and not withdrawn["transfers"],
                    "receiver_other_native_source_preserved": count(mini, "mini", "personal") == 1,
                }
                invoke("permission", "mini", "--scope", "personal", "--action", "regrant")
                restored = json.loads(invoke("push", "mini"))
                regrant_ok = count(mini, "laptop", "personal") == 1 and bool(restored["transfers"])
                with closing(records.connect(mini["db"])) as conn, ContextStore(conn)._atomic():
                    purge_session(conn, "codex_rollout-laptop-personal")
                retirement = json.loads(invoke("push", "mini"))
                retired_both = (
                    count(laptop, "laptop", "personal") == count(mini, "laptop", "personal") == 0
                )
                wrong = (auth / "wrong_host.pub").read_text().split()
                known.write_text(f"[127.0.0.1]:{port} {wrong[0]} {wrong[1]}\n")
                refused = invoke("push", "mini", expected=1)
                known.write_text(known_text)
                wrong_command = ssh.command(laptop["config"], "mini")
                wrong_command[-1] = "session-sync serve --peer impersonated"
                denied = subprocess.run(wrong_command, capture_output=True, text=True, timeout=15)
                checks = {
                    **initial_checks,
                    **withdrawal_checks,
                    "all_pushes_before_pull": all_output.index("Push mini")
                    < all_output.index("Pull mini"),
                    "all_imports_only_permitted_remote_history": both,
                    "fresh_regrant_restores": regrant_ok,
                    "push_reconciles_reverse_retirement": retired_both,
                    "wrong_host_key_refused": "complete response" in refused,
                    "caller_cannot_choose_forced_peer": denied.returncode != 0,
                    "canonical_coverage_explicit": not retirement["sync_complete"]
                    and not retirement["full_store_covered"],
                }
            finally:
                daemon.terminate()
                daemon.wait(timeout=5)
    assert all(checks.values()), checks
    data = {
        "connection": {
            "transport": "actual OpenSSH loopback",
            "strict_host_checking": True,
            "dedicated_forced_peer": True,
            "owner_ssh_configuration_changed": False,
        },
        "first_transfer": first,
        "unchanged_retry": repeated,
        "permissions": {"queued": queued, "withdrawal": withdrawn, "fresh_regrant": restored},
        "reverse_retirement": retirement,
        "checks": checks,
        "runtime": {
            "require_installed": require_installed,
            "module": coordinator.__file__,
            "cli_command": cli_command,
        },
        "limits": (
            "One configured canonical database per endpoint, complete scopes bounded to32MiB. "
            "No full-store/managed restore or full product completion. Keys, authorization "
            "file and daemon were disposable and removed; fixture databases remain for study. "
            "No owner DB/config/hooks or real peer changed."
        ),
    }
    (output / "results.json").write_text(json.dumps(data, indent=2) + "\n")
    print(
        json.dumps({"checks": len(checks), "passed": all(checks.values()), "output": str(output)})
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-installed", action="store_true")
    args = parser.parse_args()
    run(args.output.resolve(), args.require_installed)
