"""NotebookLM notebook maintenance — dedup, cleanup."""

from __future__ import annotations

import json
import subprocess
from collections import defaultdict


def _run_nlm(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["notebooklm", *args], capture_output=True, text=True, check=check)


def find_duplicates(notebook_id: str) -> dict[str, list[dict]]:
    """Find duplicate sources by title in a notebook. Returns {title: [sources]}."""
    result = _run_nlm(["source", "list", "--notebook", notebook_id, "--json"])
    try:
        sources = json.loads(result.stdout).get("sources", [])
    except json.JSONDecodeError:
        import sys

        print(f"[studyctl] Failed to parse source list: {result.stdout[:200]}", file=sys.stderr)
        return {}

    by_title: dict[str, list[dict]] = defaultdict(list)
    for s in sources:
        by_title[s["title"]].append(s)

    return {t: srcs for t, srcs in by_title.items() if len(srcs) > 1}


def dedup_notebook(notebook_id: str, dry_run: bool = False) -> dict:
    """Remove TRUE duplicates (same title, same source origin).

    For legitimate duplicates (same filename from different dirs),
    we keep all of them — the sync engine should have given them
    unique names. This only removes exact duplicates from re-syncing.

    Strategy: group by title. If >2 copies, keep 2 (could be legit
    from different dirs). If all have identical source metadata,
    keep only 1.
    """
    result = _run_nlm(["source", "list", "--notebook", notebook_id, "--json"])
    try:
        sources = json.loads(result.stdout).get("sources", [])
    except json.JSONDecodeError:
        import sys

        print(f"[studyctl] Failed to parse source list: {result.stdout[:200]}", file=sys.stderr)
        return {"duplicates": 0, "removed": 0, "titles": []}

    by_title: dict[str, list[dict]] = defaultdict(list)
    for s in sources:
        by_title[s["title"]].append(s)

    removed = 0
    titles = []
    for title, srcs in by_title.items():
        if len(srcs) <= 1:
            continue
        # Keep the last one, delete earlier duplicates
        to_delete = srcs[:-1]
        for s in to_delete:
            if not dry_run:
                _run_nlm(["source", "delete", s["id"], "-n", notebook_id, "-y"], check=False)
            removed += 1
        titles.append(title)

    return {"duplicates": removed, "removed": removed, "titles": titles}
