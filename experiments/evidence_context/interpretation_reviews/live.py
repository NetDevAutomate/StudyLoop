"""Opt-in three-provider synthetic review pilot; three bounded calls, no tuning loop."""

import argparse
import json
import os
import runpy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from agent_session_tools.context.provenance import Origin
from agent_session_tools.context.public import open_context

from ..arbitration_lab.runner import call_gateway

MODELS = ("llama4-maverick", "qwen3-coder", "mistral-large-3")


def prepare(output):
    helper = runpy.run_path(str(Path(__file__).parents[1] / "agent_context/probe.py"))
    conn, store, _, _, base, _, _ = helper["prepare"](output)
    source_specs = [
        ("atomic", "We chose SQLite for atomic writes.", Origin.CONVERSATION, None, None),
        (
            "benchmark",
            "No comparative database benchmark was run.",
            Origin.CONVERSATION,
            None,
            None,
        ),
        ("check", "12 tests passed", Origin.PROCESS_EXIT, '["uv","run","pytest"]', 0),
    ]
    sources = {}
    for name, body, origin, target, exit_code in source_specs:
        eid = store.capture(
            replace(
                base,
                native_key="pilot-" + name,
                body=body,
                origin=origin,
                target=target,
                exit_code=exit_code,
                revision=None,
            )
        )
        sources[name] = {
            "citation": {"evidence_id": eid, "start": 0, "end": len(body), "quote": body},
            "origin": origin.value,
            "revision": None,
            "target": target,
            "exit_code": exit_code,
        }
    definitions = [
        (
            "attribution",
            "The earlier session chose SQLite for atomic writes.",
            ["atomic"],
            ["supported"],
        ),
        (
            "overclaim",
            "SQLite was proven faster than every graph database.",
            ["atomic", "benchmark"],
            ["unsupported", "uncertain"],
        ),
        (
            "applicability",
            "The tests validate the current revision " + "b" * 40 + ".",
            ["check"],
            ["unsupported", "uncertain"],
        ),
    ]
    cases = []
    with open_context(output / "sessions.db", write=True) as context:
        for name, statement, refs, accepted in definitions:
            evidence = [sources[key] for key in refs]
            aid = context.propose(
                statement=statement,
                state="unknown",
                target=None,
                citations=[s["citation"] for s in evidence],
                producer="synthetic-author",
            )["assertion_id"]
            cases.append(
                {
                    "case_id": name,
                    "assertion_id": aid,
                    "assertion": statement,
                    "sources": evidence,
                    "accepted_verdicts": accepted,
                }
            )
    conn.close()
    prompt = (Path(__file__).with_name("PROMPT.md")).read_text()
    messages = [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": json.dumps(
                [{k: v for k, v in case.items() if k != "accepted_verdicts"} for case in cases]
            ),
        },
    ]
    frozen = {"models": list(MODELS), "max_calls": 3, "cases": cases, "messages": messages}
    (output / "frozen.json").write_text(json.dumps(frozen, indent=2))
    return frozen


def run(output, *, gateway=call_gateway):
    keys = ("STUDYLOOP_CONFIG", "SESSION_CONTEXT_SCOPE")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        return _run(output, gateway=gateway)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _run(output, *, gateway):
    frozen = prepare(output)

    def request(model):
        try:
            response = gateway(frozen["messages"], model)
            return {"model": model, "response": response}
        except Exception as error:
            return {"model": model, "error_type": type(error).__name__}

    with ThreadPoolExecutor(max_workers=2) as workers:
        responses = list(workers.map(request, MODELS))
    (output / "model-responses.json").write_text(json.dumps(responses, indent=2))
    records = []
    cases = {case["case_id"]: case for case in frozen["cases"]}
    for response in responses:
        record = {"model": response["model"], "accepted_reviews": [], "status": "failed"}
        try:
            raw = response["response"]
            if raw["finish_reason"] != "stop":
                raise ValueError("Unfinished model response")
            parsed = json.loads(raw["text"])
            if not isinstance(parsed, dict) or set(parsed) != {"reviews"}:
                raise ValueError("Wrong response fields")
            items = parsed["reviews"]
            if len(items) != len(cases) or {item["case_id"] for item in items} != cases.keys():
                raise ValueError("Missing or duplicate cases")
            # One provider's response is accepted atomically; no partial review batch.
            with open_context(output / "sessions.db", write=True) as context:
                accepted = []
                for item in items:
                    if set(item) != {"case_id", "verdict", "rationale", "citations", "limitations"}:
                        raise ValueError("Wrong review fields")
                    case = cases[item["case_id"]]
                    allowed = {s["citation"]["evidence_id"] for s in case["sources"]}
                    if any(c["evidence_id"] not in allowed for c in item["citations"]):
                        raise ValueError("Citation outside supplied case evidence")
                    value = context.review(
                        target_kind="assertion",
                        target_id=case["assertion_id"],
                        producer="gateway:" + response["model"],
                        **{k: v for k, v in item.items() if k != "case_id"},
                    )
                    accepted.append(
                        {
                            "case_id": item["case_id"],
                            "verdict": item["verdict"],
                            "within_predeclared_range": item["verdict"]
                            in case["accepted_verdicts"],
                            "review_id": value["review_id"],
                        }
                    )
            record.update(status="accepted", accepted_reviews=accepted)
        except Exception as error:
            record["error_type"] = type(error).__name__
        records.append(record)
        print(record["model"], record["status"], flush=True)
    assessments = {}
    with open_context(output / "sessions.db") as context:
        for name, case in cases.items():
            assessments[name] = context.assess(
                "SQLite tests", [case["assertion_id"]], budget_bytes=131072
            )
    report = {
        "records": records,
        "assessments": assessments,
        "claims": {
            "case_count": 3,
            "max_calls": 3,
            "prompt_tuning": False,
            "synthetic_only": True,
            "human_relevance_grade": "not_available",
            "semantic_certification": "not_established",
        },
    }
    (output / "results.json").write_text(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--live", action="store_true", help="Allow exactly three bounded gateway calls"
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("Use --live to authorize the bounded synthetic pilot")
    args.output.mkdir(parents=True, exist_ok=False)
    if not os.environ.get("LITELLM_API_KEY"):
        from dotenv import dotenv_values

        key = dotenv_values(Path.home() / ".config/litellm-proxy-docker/.env").get(
            "LITELLM_MASTER_KEY"
        )
        if not key:
            parser.error("Gateway credential unavailable")
        os.environ["LITELLM_API_KEY"] = key
    result = run(args.output.resolve())
    print(
        json.dumps(
            {
                "output": str(args.output),
                "accepted_providers": sum(r["status"] == "accepted" for r in result["records"]),
            }
        )
    )


if __name__ == "__main__":
    main()
