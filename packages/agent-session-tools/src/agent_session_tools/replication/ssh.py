"""Dedicated-key SSH transport with a receiver-owned forced-command peer binding."""

import os
from pathlib import Path
import re

from .policy import PeerPolicy, ReplicaError
from .wire import MARKER, ProcessConnection


def command(config, peer):
    PeerPolicy.from_config(config, peer, controls_only=True)
    raw = config["memory"]["sync"]["peers"][peer].get("ssh")
    if (
        not isinstance(raw, dict)
        or not {"host", "user", "identity_file", "known_hosts"} <= set(raw)
        or set(raw) - {"host", "user", "port", "identity_file", "known_hosts"}
    ):
        raise ReplicaError(
            "Peer ssh requires explicit host, user, identity_file and known_hosts"
        )
    host, user, port = raw["host"], raw["user"], raw.get("port", 22)
    if not isinstance(host, str) or not re.fullmatch(
        r"[A-Za-z0-9:][A-Za-z0-9_.:%-]{0,252}", host
    ):
        raise ReplicaError("Invalid configured SSH host")
    if not isinstance(user, str) or not re.fullmatch(
        r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}", user
    ):
        raise ReplicaError("Invalid configured SSH user")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ReplicaError("Invalid configured SSH port")
    paths = []
    for key in ("identity_file", "known_hosts"):
        if not isinstance(raw[key], str):
            raise ReplicaError("SSH key and known-hosts paths must be explicit files")
        path = Path(raw[key]).expanduser()
        if (
            not path.is_absolute()
            or not path.is_file()
            or any(c in str(path) for c in ("\n", "\r", "%"))
        ):
            raise ReplicaError(
                "SSH key and known-hosts paths must be existing absolute files without substitutions"
            )
        paths.append(str(path))
    quoted_known_hosts = paths[1].replace("\\", "\\\\").replace('"', '\\"')
    return [
        "/usr/bin/ssh",
        "-F",
        "/dev/null",
        "-T",
        "-p",
        str(port),
        "-l",
        user,
        "-i",
        paths[0],
        "-o",
        f'UserKnownHostsFile="{quoted_known_hosts}"',
        "-o",
        "GlobalKnownHostsFile=/dev/null",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "IdentityAgent=none",
        "-o",
        "PasswordAuthentication=no",
        "-o",
        "KbdInteractiveAuthentication=no",
        "-o",
        "ClearAllForwardings=yes",
        "-o",
        "ForwardAgent=no",
        "-o",
        "ForwardX11=no",
        "-o",
        "PermitLocalCommand=no",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        "ServerAliveInterval=10",
        "-o",
        "ServerAliveCountMax=2",
        "--",
        host,
        MARKER,
    ]


def connect(config, peer):
    return ProcessConnection(command(config, peer))


def require_forced_command():
    # These variables are set by sshd. A shell-capable local owner can fabricate
    # them; this guard is not a sandbox against the owner of the machine.
    if (
        os.environ.get("SSH_ORIGINAL_COMMAND") != MARKER
        or len(os.environ.get("SSH_CONNECTION", "").split()) != 4
    ):
        raise ReplicaError("Replica serve requires its dedicated SSH forced command")
