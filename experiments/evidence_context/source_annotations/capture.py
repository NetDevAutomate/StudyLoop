"""Disposable local recorder. A manifest is a trust root, not remote attestation."""

import hashlib
import json
import subprocess
import sys


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def record(directory, rid, text, origin, scope="personal", target=None, exit_code=0):
    context = {"scope": scope, "project": "recorder-fixture", "target": target}
    receipt = {"id": rid, "origin": origin, "context": context}
    if origin == "process_exit":
        # This program emits controlled fixture text; it tests capture, not an application.
        script = directory / "emitter.py"
        if not script.exists():
            script.write_text(
                "import json, sys\nfrom pathlib import Path\n"
                "s=json.loads(Path(sys.argv[1]).read_text())\n"
                "print(s['stdout'], end='')\n"
                "sys.exit(s['exit_code'])\n"
            )
        spec = {"context": context, "stdout": text, "exit_code": exit_code}
        spec_file = directory / f"{rid}-invocation.json"
        write(spec_file, spec)
        result = subprocess.run(
            [sys.executable, str(script.resolve()), str(spec_file.resolve())],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            cwd=directory,
        )
        receipt.update(
            returncode=result.returncode,
            stderr=result.stderr,
            program_sha256=digest(script.read_text()),
            invocation_sha256=digest(spec_file.read_text()),
        )
        text = result.stdout
    receipt["body_sha256"] = digest(text)
    write(directory / f"{rid}.json", receipt)
    return {"id": "S" + rid[1:], "text": text, "receipt_id": rid}, receipt


def resolve(record, receipts, manifest):
    rid = record.get("receipt_id")
    if rid is None:
        return None, "missing_receipt"
    binding = manifest.get(record["id"])
    if binding is None or binding["receipt_id"] != rid:
        return None, "receipt_binding_mismatch"
    receipt = receipts.get(rid)
    if receipt is None or receipt.get("id") != rid:
        return None, "unknown_receipt"
    if binding["receipt_sha256"] != digest(canonical(receipt)):
        return None, "receipt_changed"
    if receipt.get("body_sha256") != digest(record["text"]):
        return None, "body_changed"
    if receipt.get("origin") not in {"process_exit", "conversation_message"}:
        return None, "unknown_origin"
    if receipt["origin"] == "process_exit" and type(receipt.get("returncode")) is not int:
        return None, "missing_exit_status"
    return receipt, None
