"""Private corpus preparation and frozen retrieval variants; production DB is read-only."""

import hashlib
import json
import re
import sqlite3
import time
from collections import defaultdict
from itertools import pairwise

import numpy as np

SECRET = re.compile(
    r"AKIA[A-Z0-9]{16}|-----BEGIN .*PRIVATE KEY|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|"
    r"(?:bearer|api[_-]?key|password|secret[_-]?key)\s*[=: ]\s*['\"]?[A-Za-z0-9/+_=.-]{16,}",
    re.I,
)
FILE = re.compile(r"\b(?:[\w.-]+/)*[\w.-]+\.(?:py|md|toml|yaml|json|js|html|sql)\b")
STOP = {
    "the",
    "a",
    "an",
    "in",
    "on",
    "of",
    "to",
    "for",
    "and",
    "or",
    "is",
    "was",
    "were",
    "what",
    "why",
    "how",
    "did",
    "do",
    "does",
    "we",
    "it",
    "these",
    "that",
    "which",
    "with",
    "from",
    "as",
    "rather",
    "than",
    "through",
    "actually",
    "recorded",
}
ARMS = ("keyword", "semantic", "relationships", "combined")


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def prepare(config_path, output):
    from transformers import AutoTokenizer

    config = json.loads(config_path.read_text())
    output.mkdir(exist_ok=False, parents=True, mode=0o700)
    tokenizer = AutoTokenizer.from_pretrained(config["embedding_model"], local_files_only=True)
    allowed = {
        path.lower(): project for project, paths in config["projects"].items() for path in paths
    }
    con = sqlite3.connect(f"file:{config['db']}?mode=ro", uri=True)
    con.execute("BEGIN")
    sessions = con.execute(
        "SELECT id,source,project_path,created_at FROM sessions ORDER BY id"
    ).fetchall()
    records, skipped, session_count = [], defaultdict(int), 0
    for sid, harness, project, created in sessions:
        if (
            not project
            or project.lower() not in allowed
            or not created
            or created >= config["cutoff"]
            or sid in config["prior_excluded_sessions"]
            or not sid.startswith("codex_")
        ):
            continue
        rows = con.execute(
            "SELECT id,role,content,seq,timestamp FROM messages WHERE session_id=? "
            "AND role IN ('assistant','user') ORDER BY seq,id",
            (sid,),
        ).fetchall()
        if len(rows) < 10:
            continue
        session_count += 1
        for mid, role, content, seq, stamp in rows:
            if (
                not content
                or len(content) < 60
                or content.lstrip().startswith(("<", "# AGENTS", "You are"))
            ):
                skipped["short_or_instruction_envelope"] += 1
                continue
            offsets = tokenizer(
                content, add_special_tokens=False, return_offsets_mapping=True, truncation=False
            )["offset_mapping"]
            for first in range(0, len(offsets), 240):
                group = offsets[first : first + 280]
                if not group:
                    continue
                start, end = group[0][0], group[-1][1]
                text = content[start:end]
                if SECRET.search(text):
                    skipped["potential_sensitive_chunk"] += 1
                    continue
                if len(text) < 60:
                    continue
                records.append(
                    {
                        "id": f"P{len(records) + 1:05}",
                        "message": mid,
                        "session": sid,
                        "project": allowed[project.lower()],
                        "scope": "personal_project_allowlist",
                        "harness": harness,
                        "at": stamp or created,
                        "seq": seq,
                        "start": start,
                        "end": end,
                        "source_sha256": hashlib.sha256(content.encode()).hexdigest(),
                        "role": role,
                        "kind": "conversation_report",
                        "text": text,
                    }
                )
    con.rollback()
    con.close()
    edges = set()
    groups = defaultdict(list)
    for record in records:
        groups[record["session"]].append(record)
    for group in groups.values():
        ordered = sorted(group, key=lambda r: (r["seq"], r["start"], r["id"]))
        for a, b in pairwise(ordered):
            for x, y in ((a, b), (b, a)):
                edges.add((x["id"], y["id"], "sequence"))
    files = defaultdict(list)
    for r in records:
        for f in set(FILE.findall(r["text"])):
            files[(r["project"], f)].append(r["id"])
    # Deterministic bounded structural links, made before queries or evidence labels.
    for ids in files.values():
        ids = sorted(set(ids))
        for i, src in enumerate(ids):
            for dst in ids[max(0, i - 2) : i + 3]:
                if src != dst:
                    edges.add((src, dst, "same_file"))
    corpus = {
        "records": records,
        "edges": sorted(edges),
        "questions": config["questions"],
        "manifest": {
            "sessions": session_count,
            "records": len(records),
            "edges": len(edges),
            "skipped": dict(skipped),
            "label_status": "real development pilot; not independent holdout",
            "scope": "explicit personal-project path allowlist, not harness-derived",
            "selection": (
                "Codex root sessions only, before cutoff, instruction envelopes "
                "and potential sensitive chunks excluded"
            ),
        },
    }
    write(output / "corpus.json", corpus)
    write(output / "config.json", config)
    # Reviewer pool is selected by frozen historical episode ranges, not retrieval output.
    pools = {
        q["id"]: [
            r
            for r in records
            if r["session"] == q["review_session"]
            and q["review_seq"][0] <= r["seq"] <= q["review_seq"][1]
        ]
        if q["review_session"]
        else []
        for q in config["questions"]
    }
    write(output / "review-pools.json", pools)
    return corpus


def embed(directory):
    import torch
    from sentence_transformers import SentenceTransformer

    config = json.loads((directory / "config.json").read_text())
    corpus = json.loads((directory / "corpus.json").read_text())
    torch.set_num_threads(4)
    started = time.perf_counter()
    model = SentenceTransformer(config["embedding_model"], local_files_only=True, device="cpu")
    matrix = model.encode(
        [r["text"] for r in corpus["records"]],
        batch_size=32,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    query_vectors = model.encode(
        [q["query"] for q in corpus["questions"]],
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    np.save(directory / "vectors.npy", matrix)
    np.save(directory / "query-vectors.npy", query_vectors)
    write(
        directory / "embedding.json",
        {
            "model": config["embedding_model"],
            "dimensions": int(matrix.shape[1]),
            "seconds": time.perf_counter() - started,
            "records": len(matrix),
        },
    )


def rrf(rankings):
    scores = defaultdict(float)
    for ranking in rankings:
        for rank, rid in enumerate(ranking, 1):
            scores[rid] += 1 / (60 + rank)
    return sorted(scores, key=lambda rid: (-scores[rid], rid))


def select_pack(ranking, available, tokenizer, ceiling=1400):
    pack = []
    for rid in ranking:
        r = available[rid]
        item = {k: r[k] for k in ("id", "role", "at", "kind", "text")}
        if len(tokenizer.encode(canonical([*pack, item]), add_special_tokens=False)) <= ceiling:
            pack.append(item)
        if len(pack) == 6:
            break
    return pack


def retrieve(directory):
    from transformers import AutoTokenizer

    corpus = json.loads((directory / "corpus.json").read_text())
    config = json.loads((directory / "config.json").read_text())
    tokenizer = AutoTokenizer.from_pretrained(config["tokenizer"], local_files_only=True)
    matrix = np.load(directory / "vectors.npy")
    queries = np.load(directory / "query-vectors.npy")
    con = sqlite3.connect(directory / "retrieval.sqlite")
    con.execute("CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED,text)")
    con.executemany(
        "INSERT INTO search VALUES (?,?)", [(r["id"], r["text"]) for r in corpus["records"]]
    )
    con.commit()
    adjacency = defaultdict(set)
    for a, b, _ in corpus["edges"]:
        adjacency[a].add(b)
    outputs = []
    for qi, q in enumerate(corpus["questions"]):
        available = {
            r["id"]: r
            for r in corpus["records"]
            if r["project"] == q["project"] and r["at"] < q["asof"]
        }
        words = [
            w
            for w in re.findall(r"[A-Za-z0-9_]+", q["query"].lower())
            if w not in STOP and len(w) > 2
        ]
        expression = " OR ".join('"' + word + '"' for word in dict.fromkeys(words))
        started = time.perf_counter()
        keyword = [
            row[0]
            for row in con.execute(
                "SELECT id FROM search WHERE search MATCH ? ORDER BY bm25(search),id", (expression,)
            )
            if row[0] in available
        ]
        keyword_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        similarity = matrix @ queries[qi]
        semantic = [
            corpus["records"][int(i)]["id"]
            for i in np.argsort(-similarity, kind="stable")
            if corpus["records"][int(i)]["id"] in available
        ]
        semantic_ms = (time.perf_counter() - started) * 1000
        expanded = []
        for seed in keyword[:3]:
            expanded.append(seed)
            expanded.extend(sorted(adjacency[seed] & available.keys()))
        expanded = list(dict.fromkeys(expanded))
        rankings = {
            "keyword": keyword,
            "semantic": semantic,
            "relationships": rrf([keyword, expanded]),
            "combined": rrf([keyword, semantic, expanded]),
        }
        for arm in ARMS:
            pack = select_pack(rankings[arm], available, tokenizer)
            outputs.append(
                {
                    "question": q["id"],
                    "arm": arm,
                    "query": q["query"],
                    "pack": pack,
                    "ids": [r["id"] for r in pack],
                    "pack_tokens": len(tokenizer.encode(canonical(pack), add_special_tokens=False)),
                    "keyword_search_ms": keyword_ms,
                    "semantic_search_ms": semantic_ms,
                }
            )
    con.close()
    write(directory / "retrieval.json", outputs)
    return outputs
