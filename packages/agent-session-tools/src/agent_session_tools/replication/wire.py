"""Bounded, deadline-aware JSON frames over authenticated subprocess pipes."""

import json
import os
import select
import struct
import subprocess
import time
from typing import Any, Callable

from .policy import ReplicaError
from .snapshot import MAX_BYTES

MARKER = "session-replica-stdio-v1"
MAX_FRAME = MAX_BYTES + 1024 * 1024
MAX_SESSION_BYTES = 256 * 1024 * 1024
MAX_REQUESTS = 1024


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate frame key")
        value[key] = item
    return value


class Frames:
    def __init__(self, reader, writer, *, timeout: float = 120):
        self.reader, self.writer = reader, writer
        os.set_blocking(reader, False)
        os.set_blocking(writer, False)
        self.deadline = time.monotonic() + timeout
        self.transferred = 0

    def _wait(self, fd, *, write=False):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ReplicaError("Replica connection deadline exceeded")
        ready = select.select(
            [] if write else [fd], [fd] if write else [], [], remaining
        )
        if not ready[1 if write else 0]:
            raise ReplicaError("Replica connection deadline exceeded")

    def _read(self, count, *, allow_eof=False):
        result = bytearray()
        while len(result) < count:
            self._wait(self.reader)
            try:
                chunk = os.read(self.reader, min(count - len(result), 65536))
            except (BlockingIOError, InterruptedError):
                continue
            if not chunk:
                if allow_eof and not result:
                    raise EOFError
                raise ReplicaError(
                    "Replica connection ended before a complete response"
                )
            result.extend(chunk)
        return bytes(result)

    def _budget(self, size):
        self.transferred += size
        if size > MAX_FRAME or self.transferred > MAX_SESSION_BYTES:
            raise ReplicaError("Replica frame or connection byte limit exceeded")

    def read(self, *, allow_eof=False):
        size = struct.unpack("!I", self._read(4, allow_eof=allow_eof))[0]
        self._budget(size)
        try:
            return json.loads(
                self._read(size),
                object_pairs_hook=_object,
                parse_constant=lambda _: (_ for _ in ()).throw(
                    ValueError("Nonfinite JSON")
                ),
            )
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise ReplicaError("Malformed replica JSON frame") from exc

    def write(self, value, *, before_write=None):
        try:
            body = json.dumps(
                value, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        except (ValueError, TypeError, RecursionError) as exc:
            raise ReplicaError("Replica result is not bounded JSON") from exc
        self._budget(len(body))
        if before_write is not None:
            before_write()
        packet = memoryview(struct.pack("!I", len(body)) + body)
        while packet:
            self._wait(self.writer, write=True)
            try:
                written = os.write(self.writer, packet[:65536])
            except (BlockingIOError, InterruptedError):
                continue
            if not written:
                raise ReplicaError("Replica connection could not write a frame")
            packet = packet[written:]


class ProcessConnection:
    """Only production transport constructs this with the validated SSH argv.

    A subprocess adapter is also used by isolated tests; it is not an authentication
    mechanism or a user-configurable replacement for SSH.
    """

    def __init__(self, command, *, timeout: float = 120, env=None):
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        assert self.process.stdout is not None and self.process.stdin is not None
        self.frames = Frames(
            self.process.stdout.fileno(), self.process.stdin.fileno(), timeout=timeout
        )
        self.sequence = 0
        self.before_send: Callable[[str, dict[str, Any]], None] | None = None

    def call(self, operation, arguments):
        before_send = self.before_send
        self.sequence += 1
        if self.sequence > MAX_REQUESTS:
            raise ReplicaError("Replica request limit exceeded; retry remaining work")
        self.frames.write(
            {
                "protocol": MARKER,
                "sequence": self.sequence,
                "operation": operation,
                "arguments": arguments,
            },
            before_write=(lambda: before_send(operation, arguments))
            if before_send
            else None,
        )
        reply = self.frames.read()
        if (
            not isinstance(reply, dict)
            or set(reply) != {"sequence", "ok", "result"}
            or reply["sequence"] != self.sequence
            or type(reply["ok"]) is not bool
        ):
            raise ReplicaError("Invalid replica response envelope")
        if not reply["ok"]:
            raise ReplicaError(
                f"Remote replica refused {operation}; no completion is claimed"
            )
        return reply["result"]

    def close(self):
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if self.process.stdout:
            self.process.stdout.close()


def serve(endpoint, reader, writer, *, timeout=120):
    frames = Frames(reader, writer, timeout=timeout)
    for sequence in range(1, MAX_REQUESTS + 1):
        try:
            request = frames.read(allow_eof=True)
        except EOFError:
            return
        if (
            not isinstance(request, dict)
            or set(request) != {"protocol", "sequence", "operation", "arguments"}
            or request["protocol"] != MARKER
            or type(request["sequence"]) is not int
            or request["sequence"] != sequence
        ):
            raise ReplicaError("Invalid replica request envelope")
        try:
            result = endpoint.call(request["operation"], request["arguments"])
            # Recheck immediately before encoding the result into transport bytes.
            endpoint.check()
        except Exception:
            frames.write({"sequence": sequence, "ok": False, "result": None})
            raise ReplicaError("Replica request refused") from None
        frames.write(
            {"sequence": sequence, "ok": True, "result": result},
            before_write=lambda: endpoint.before_result(request["operation"], result),
        )
    raise ReplicaError("Replica request limit exceeded")
