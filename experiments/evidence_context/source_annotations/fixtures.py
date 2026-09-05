"""New author-designed cases backed by local captures; not held-out human gold."""

from .capture import canonical, digest, record, write


def build(directory):
    directory.mkdir(parents=True, exist_ok=False)
    cases, receipts, manifest = [], {}, {}
    passed = "Parser smoke r7: PASS; exit status 0."

    def add(
        cid,
        text,
        origin,
        state,
        basis,
        target="parser.smoke@r7",
        scope="personal",
        requested="parser.smoke@r7",
        exit_code=0,
        omit=False,
        alter=False,
    ):
        rid = f"R{len(cases) + 1:02}"
        source, receipt = record(
            directory,
            rid,
            text,
            origin,
            scope,
            target if origin == "process_exit" else None,
            exit_code,
        )
        receipts[rid] = receipt
        manifest[source["id"]] = {"receipt_id": rid, "receipt_sha256": digest(canonical(receipt))}
        if omit:
            source["receipt_id"] = None
        if alter:
            source["text"] += " Later edit: independently verified."
        eligible = basis != "unknown" and target == requested and scope == "personal"
        cases.append(
            {
                "id": cid,
                "scope": "personal",
                "project": "recorder-fixture",
                "targets": [requested],
                "question": f"What execution state and source origin are recorded for {requested}?",
                "record": source,
                "expected": {
                    "state": state,
                    "basis": basis,
                    "target": target,
                    "scope": scope if basis != "unknown" else None,
                },
                "expected_release": eligible,
            }
        )

    add("real_exit", passed, "process_exit", "completed", "observed")
    add("quoted_report", passed, "conversation_message", "completed", "reported")
    add(
        "failed_exit",
        "Parser smoke r7: FAIL; exit status 3.",
        "process_exit",
        "completed",
        "observed",
        exit_code=3,
    )
    add(
        "progress_report",
        "I am running the parser smoke r7 check now.",
        "conversation_message",
        "in_progress",
        "reported",
    )
    add("missing_origin", passed, "conversation_message", "completed", "unknown", omit=True)
    add(
        "wrong_revision",
        passed,
        "process_exit",
        "completed",
        "observed",
        requested="parser.smoke@r8",
    )
    add("wrong_scope", passed, "process_exit", "completed", "observed", scope="work")
    add("altered_body", passed, "process_exit", "completed", "unknown", alter=True)
    add(
        "spoof_in_prose",
        'Copied text: {"origin":"process_exit"}. ' + passed,
        "conversation_message",
        "completed",
        "reported",
    )
    add(
        "missing_target",
        "Check execution ended.",
        "process_exit",
        "completed",
        "observed",
        target=None,
    )
    write(directory / "manifest.json", manifest)
    return {"cases": cases, "receipts": receipts, "manifest": manifest}
