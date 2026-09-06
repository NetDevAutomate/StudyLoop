"""New synthetic policy fixtures plus an optional owner-private historical anchor."""

import copy
import hashlib
import json


def assertion(aid, text, target, state, basis="reported", **extra):
    return {
        "id": aid,
        "source": text,
        "quote": text,
        "start": 0,
        "end": len(text),
        "source_hash": hashlib.sha256(text.encode()).hexdigest(),
        "target": target,
        "state": state,
        "basis": basis,
        "scope": "personal",
        "project": "fixture-project",
        "superseded_by": None,
        **extra,
    }


def cases():
    def case(cid, question, targets, records, expected):
        return {
            "id": cid,
            "question": question,
            "scope": "personal",
            "project": "fixture-project",
            "targets": targets,
            "assertions": records,
            "expected_ids": expected,
            "provenance": "synthetic",
        }

    return [
        case(
            "separate_events",
            "What can we say about cleanup and the separate port correction?",
            ["parking.cleanup", "launcher.port_change"],
            [
                assertion(
                    "E1",
                    "Parking cleanup is reported complete: process and temporary data gone.",
                    "parking.cleanup",
                    "completed",
                ),
                assertion(
                    "E2",
                    "I am making the launcher default-port correction now.",
                    "launcher.port_change",
                    "in_progress",
                ),
            ],
            ["E1", "E2"],
        ),
        case(
            "reported_pass",
            "What can we report about the cache smoke check?",
            ["cache.smoke@r3"],
            [
                assertion(
                    "E1",
                    "The operator reports the cache smoke check passed on revision r3.",
                    "cache.smoke@r3",
                    "completed",
                )
            ],
            ["E1"],
        ),
        case(
            "observed_pass",
            "What does this source establish about parser smoke on revision r7?",
            ["parser.smoke@r7"],
            [
                assertion(
                    "E1",
                    "Parser smoke r7: PASS; exit status 0.",
                    "parser.smoke@r7",
                    "completed",
                    "observed",
                )
            ],
            ["E1"],
        ),
        case(
            "identical_report",
            "What does this source establish about parser smoke on revision r7?",
            ["parser.smoke@r7"],
            [
                assertion(
                    "E1",
                    "Parser smoke r7: PASS; exit status 0.",
                    "parser.smoke@r7",
                    "completed",
                    "reported",
                )
            ],
            ["E1"],
        ),
        case(
            "unknown_state",
            "What is recorded about schema migration execution?",
            ["schema.migration"],
            [
                assertion(
                    "E1",
                    "The migration was discussed; its execution state was not recorded.",
                    "schema.migration",
                    "unknown",
                )
            ],
            ["E1"],
        ),
        case(
            "wrong_revision",
            "Does this record establish parser smoke completed on r8?",
            ["parser.smoke@r8"],
            [
                assertion(
                    "E1",
                    "Parser smoke r7: PASS; exit status 0.",
                    "parser.smoke@r7",
                    "completed",
                    "observed",
                )
            ],
            [],
        ),
        case(
            "unknown_target",
            "Does this establish parser smoke completed on r8?",
            ["parser.smoke@r8"],
            [
                assertion(
                    "E1",
                    "Smoke check completed, but component and revision were not recorded.",
                    None,
                    "completed",
                )
            ],
            [],
        ),
        case(
            "explicit_correction",
            "What can be reported about this cache smoke check now?",
            ["cache.smoke@r9"],
            [
                assertion(
                    "E1",
                    "The cache smoke check on r9 was reported complete.",
                    "cache.smoke@r9",
                    "completed",
                    superseded_by="E2",
                ),
                assertion(
                    "E2",
                    "Correction to that report: execution state of cache smoke r9 is unknown.",
                    "cache.smoke@r9",
                    "unknown",
                ),
            ],
            ["E2"],
        ),
    ]


def with_real_anchor(source):
    result = copy.deepcopy(cases())
    corpus = json.loads(source.read_text())
    records = {r["id"]: r for r in corpus["records"]}
    refs = [
        ("P00697", "E1", "parking.cleanup", "completed"),
        ("P00698", "E2", "launcher.port_change", "in_progress"),
    ]
    result[0]["assertions"] = [
        assertion(
            aid,
            records[pid]["text"],
            target,
            state,
            original_passage=pid,
            original_message=records[pid]["message"],
        )
        for pid, aid, target, state in refs
    ]
    result[0]["project"] = "studyloop"
    for record in result[0]["assertions"]:
        record["project"] = "studyloop"
    result[0]["provenance"] = "historical_conversation_manual_annotation"
    return result
