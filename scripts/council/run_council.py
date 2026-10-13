"""Fan one brief out to a council of models through the LiteLLM gateway.

Every seat gets the *same* brief and answers independently (no seat sees
another's output), so disagreement is signal rather than echo. One receipt
per seat plus a manifest land in the output directory; nothing is
summarised here -- arbitration is the caller's job, on the record.

Run from the repo root:

    uv run --group dev python scripts/council/run_council.py \
        --brief docs/architecture/plan-integration/council/brief-plan.md \
        --out   docs/architecture/plan-integration/council/plan \
        --seat  openai.gpt-6-astra --seat grok-4.6 --seat kimi-k2-thinking

The gateway key is read from ``LITELLM_API_KEY`` or, failing that, from the
installed litellm-proxy-docker ``.env``: ``LITELLM_MASTER_KEY`` as a literal, or
``LITELLM_MASTER_KEY_REF`` as a 1Password reference resolved with ``op read``.
It is never written to any receipt.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_BASE_URL = "http://127.0.0.1:4000"
DOCKER_ENV = Path.home() / ".config/litellm-proxy-docker/.env"
ENV_KEY = "LITELLM_API_KEY"  # pragma: allowlist secret - a variable NAME, not a key
# The proxy install keeps either a literal key or, since its secrets moved to
# 1Password, a reference the ``op`` CLI resolves. Both are variable NAMES.
FILE_KEY = "LITELLM_MASTER_KEY"  # pragma: allowlist secret
FILE_KEY_REF = "LITELLM_MASTER_KEY_REF"  # pragma: allowlist secret


#: How long ``op read`` may take. Signed-in, it answers in well under a
#: second; a longer wait means it is sitting on an unlock prompt nobody will
#: answer in an unattended run, which must become an exit, not a hang.
OP_TIMEOUT_SECONDS = 60


def _env_file_values() -> dict[str, str]:
    values: dict[str, str] = {}
    if not DOCKER_ENV.exists():
        return values
    for line in DOCKER_ENV.read_text().splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip("'\"")
    return values


def _classify_op_failure(stderr: str) -> str:
    """A fixed-vocabulary reading of ``op``'s stderr -- never the text itself.

    The CLI's diagnostics are what a human needs ("not signed in", "no such
    item"), but quoting stderr verbatim is not a "never the key" guarantee, so
    the message carries one of these phrases or nothing.
    """
    text = stderr.lower()
    if "not signed in" in text or "sign in" in text:
        return "account is not signed in"
    if "isn't an item" in text or "not found" in text or "doesn't exist" in text:
        return "the reference names no item or field"
    if "unauthorized" in text or "permission" in text or "forbidden" in text:
        return "the account is not authorized for that item"
    return "see `op read` stderr"


def _resolve_reference(reference: str) -> str:
    """``op read <reference>``, or a clean exit that never quotes its output.

    stdout is the channel the secret arrives on, so on failure it is never
    echoed -- not even a fragment; stderr is classified into a fixed phrase by
    :func:`_classify_op_failure`. The remedy names both unattended paths: a
    signed-in CLI or ``OP_SERVICE_ACCOUNT_TOKEN``.
    """
    remedy = (
        f"sign in with `op signin` (or set OP_SERVICE_ACCOUNT_TOKEN for an "
        f"unattended run), or set {ENV_KEY}"
    )
    try:
        result = subprocess.run(
            ["op", "read", reference],
            capture_output=True,
            text=True,
            check=False,
            timeout=OP_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        raise SystemExit(
            f"gateway key: the 1Password op CLI is not installed, so "
            f"`op read {reference}` cannot run; install it, or set {ENV_KEY}"
        ) from None
    except subprocess.TimeoutExpired:
        raise SystemExit(
            f"gateway key: `op read {reference}` did not answer within "
            f"{OP_TIMEOUT_SECONDS}s (an unlock prompt nobody can answer?); {remedy}"
        ) from None
    except OSError as exc:
        raise SystemExit(
            f"gateway key: `op read {reference}` could not be run ({type(exc).__name__}); {remedy}"
        ) from None
    resolved = result.stdout.strip()
    if result.returncode == 0 and resolved:
        return resolved
    reason = f"exit {result.returncode}: {_classify_op_failure(result.stderr or '')}"
    raise SystemExit(f"gateway key: `op read {reference}` failed ({reason}); {remedy}")


def _api_key() -> str:
    """The gateway key: ``LITELLM_API_KEY``, else the proxy's ``.env``.

    The ``.env`` carries either the literal key or a 1Password reference
    (``op://...``) that ``op read`` resolves without a prompt when the CLI is
    signed in -- the file moved to references, which is why a runner that knew
    only the literal exited "no gateway key" beside a live gateway. The same
    reference is accepted from the environment (``LITELLM_MASTER_KEY_REF``) for
    a container or CI that injects it. The value is returned, never printed:
    an error names the reference and the CLI's reason, not the secret.
    """
    key = os.environ.get(ENV_KEY, "").strip()
    if key:
        return key
    values = _env_file_values()
    if values.get(FILE_KEY):
        return values[FILE_KEY]
    reference = os.environ.get(FILE_KEY_REF, "").strip() or values.get(FILE_KEY_REF, "")
    if reference:
        return _resolve_reference(reference)
    raise SystemExit(f"no gateway key: set {ENV_KEY} or install litellm-proxy-docker")


def _slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", model)


def call_seat(
    *,
    base_url: str,
    api_key: str,
    model: str,
    system: str,
    brief: str,
    max_tokens: int,
    timeout: float,
) -> dict:
    """One chat completion; returns a receipt dict (never raises)."""
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": brief},
        ],
    }
    req = urllib.request.Request(
        f"{base_url}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:2000]
        return {"model": model, "ok": False, "error": f"HTTP {exc.code}: {detail}"}
    except Exception as exc:
        return {"model": model, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
    elapsed = time.perf_counter() - started
    if "error" in body:
        return {"model": model, "ok": False, "error": str(body["error"])[:2000]}
    choice = body["choices"][0]
    message = choice["message"]
    content = (message.get("content") or "").strip()
    reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
    usage = body.get("usage") or {}
    return {
        "model": model,
        "ok": bool(content),
        "content": content,
        "reasoning_chars": len(reasoning),
        "finish_reason": choice.get("finish_reason"),
        "elapsed_s": round(elapsed, 1),
        "usage": {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens")},
        "error": None if content else "empty content",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--brief", required=True, type=Path, help="markdown brief sent to every seat"
    )
    parser.add_argument(
        "--system", type=Path, help="optional system prompt file (default: built-in)"
    )
    parser.add_argument("--out", required=True, type=Path, help="receipt directory (created)")
    parser.add_argument(
        "--seat", action="append", required=True, help="gateway model id (repeatable)"
    )
    parser.add_argument("--max-tokens", type=int, default=16000)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--base-url", default=os.environ.get("LITELLM_BASE_URL", DEFAULT_BASE_URL))
    args = parser.parse_args(argv)

    brief = args.brief.read_text()
    system = (
        args.system.read_text()
        if args.system
        else (
            "You are one independent seat on a technical review council. Answer the brief "
            "directly and completely in Markdown. Be specific: name files, functions, tests and "
            "measurable done-criteria. Disagree with the brief where the evidence warrants it. "
            "Do not pad, do not restate the brief, do not add pleasantries."
        )
    )
    api_key = _api_key()
    args.out.mkdir(parents=True, exist_ok=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(args.seat)) as pool:
        futures = {
            pool.submit(
                call_seat,
                base_url=args.base_url,
                api_key=api_key,
                model=seat,
                system=system,
                brief=brief,
                max_tokens=args.max_tokens,
                timeout=args.timeout,
            ): seat
            for seat in args.seat
        }
        receipts = [future.result() for future in concurrent.futures.as_completed(futures)]

    receipts.sort(key=lambda r: args.seat.index(r["model"]))
    manifest = {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "brief": str(args.brief),
        "brief_sha256": hashlib.sha256(brief.encode()).hexdigest(),
        "system_sha256": hashlib.sha256(system.encode()).hexdigest(),
        "seats": [],
    }
    for receipt in receipts:
        slug = _slug(receipt["model"])
        if receipt["ok"]:
            (args.out / f"seat-{slug}.md").write_text(receipt["content"] + "\n")
        manifest["seats"].append({k: v for k, v in receipt.items() if k != "content"})
        status = "ok " if receipt["ok"] else "ERR"
        print(
            f"[{status}] {receipt['model']:<22} {receipt.get('elapsed_s', '-'):>6}s "
            f"out={receipt.get('usage', {}).get('completion_tokens', '-')} "
            f"{receipt.get('error') or ''}",
            file=sys.stderr,
        )
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return 0 if all(r["ok"] for r in receipts) else 1


if __name__ == "__main__":
    raise SystemExit(main())
