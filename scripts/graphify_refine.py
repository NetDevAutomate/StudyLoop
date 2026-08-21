#!/usr/bin/env python3
"""Refine the graphify graph after an AST rebuild.

``graphify update`` re-extracts from AST on every run, which deterministically
re-introduces two classes of malformed node:

* **primitive/builtin type nodes** — ``str``, ``int``, ``Path``, ``bool`` … are
  emitted from type annotations. They are not entities, and because a single
  ``str`` node touches hundreds of unrelated functions they act as *false
  bridges*: they glue distinct communities together, depress cohesion scores,
  and dominate the "surprising connections" section with noise such as
  ``float --uses--> GenerationTask``.
* **docstring-as-node** — whole docstrings become node labels. Per the
  extraction contract prose belongs in a node *attribute*, not its own node.
* **test-harness types** — ``MagicMock``, ``TestClient``, ``Page`` … describe
  how tests are written rather than what the system is, and surface as
  misleading "core abstractions".
* **isolated nodes** — degree 0 after the above, so unreachable by any
  traversal while still inflating community and component counts.

This script prunes both, re-clusters, and regenerates ``GRAPH_REPORT.md``.

Community IDs are remapped onto the previous assignment
(:func:`graphify.cluster.remap_communities_to_previous`) so curated labels stay
attached to the same community across runs. Without that, re-clustering
renumbers communities and labels silently describe the wrong nodes.

Curated labels live in ``.graphify-labels.json`` at the repo root — tracked in
git, so they survive ``graphify uninstall --purge`` wiping ``graphify-out/``.

Usage::

    python3 scripts/graphify_refine.py            # refine in place
    python3 scripts/graphify_refine.py --dry-run  # report only, write nothing

Run after every ``graphify update``.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path
from typing import Any

import networkx as nx
from networkx.readwrite import json_graph

try:
    from graphify.analyze import god_nodes, suggest_questions, surprising_connections
    from graphify.cluster import cluster, remap_communities_to_previous, score_all
    from graphify.export import to_json
    from graphify.report import generate
except ImportError as exc:  # pragma: no cover - environment guard
    raise SystemExit(
        f"error: graphify is not importable ({exc}).\n"
        "graphify is a standalone tool, not a studyloop dependency, so the repo\n"
        "venv does not provide it. Run this under the interpreter that has it:\n\n"
        "  just graph-refine     # resolves the right interpreter automatically\n"
        "  graphify update .     # (re)creates graphify-out/.graphify_python\n"
    ) from exc

REPO_ROOT = Path(__file__).resolve().parent.parent
GRAPH_PATH = REPO_ROOT / "graphify-out" / "graph.json"
REPORT_PATH = REPO_ROOT / "graphify-out" / "GRAPH_REPORT.md"
LABEL_STORE = REPO_ROOT / "graphify-out" / ".graphify_labels.json"
CURATED_LABELS = REPO_ROOT / ".graphify-labels.json"
DETECT_PATH = REPO_ROOT / "graphify-out" / ".graphify_detect.json"

#: Labels that are language builtins rather than project entities. Mirrors
#: ``graphify.extract._LANGUAGE_BUILTIN_GLOBALS``, which upstream applies to
#: *callees* only — type-annotation nodes slip through.
BUILTIN_LABELS: frozenset[str] = frozenset(
    {
        "str",
        "int",
        "float",
        "bool",
        "list",
        "dict",
        "set",
        "tuple",
        "bytes",
        "None",
        "Any",
        "object",
        "type",
        "complex",
        "frozenset",
        "bytearray",
        "T",
        "Path",
        "Exception",
        "BaseException",
        "ValueError",
        "TypeError",
        "RuntimeError",
        "KeyError",
        "OSError",
        "AttributeError",
        "IndexError",
        "NotImplementedError",
        "StopIteration",
        "Callable",
        "Iterable",
        "Iterator",
        "Sequence",
        "Mapping",
        "Optional",
        "Union",
    }
)

#: Source-path prefixes whose nodes are dropped regardless of ``.graphifyignore``.
#:
#: Two reasons this belongs here as well as in the ignore file:
#:
#: 1. ``graphify update`` MERGES into the existing ``graph.json`` rather than
#:    replacing it, so nodes for files that are no longer scanned linger
#:    indefinitely. Newly-added ignore rules do not retroactively evict them.
#: 2. graphify traverses hidden agent-config directories through a path that
#:    ``.graphifyignore`` does not reliably prune (``.agents/``, ``.crush/``,
#:    ``.opencode/``, ``.pi/`` are still returned by ``detect``).
#:
#: These are per-assistant copies of the tracked ``agents/`` tree, so keeping
#: them double-counts the same content under several names. ``.github/`` and
#: ``.pre-commit-config.yaml`` are deliberately NOT excluded — real project
#: configuration, not duplicated agent scaffolding.
EXCLUDED_PREFIXES: tuple[str, ...] = (
    ".agents/",
    ".claude/",
    ".kiro/",
    ".crush/",
    ".opencode/",
    ".pi/",
    ".codegraph/",
    ".understand-anything/",
    "agent/",
    "site/",
    "skills-lock.json",
    # graphify's own artefacts: the curated label store describes the graph, so
    # indexing it makes the graph a node in itself.
    ".graphify-labels.json",
    "packages/studyloop/src/studyloop/web/static/vendor/",
)


def excluded_by_path(graph: nx.Graph) -> list[str]:
    """Return nodes whose source file sits under an excluded prefix."""
    dropped: list[str] = []
    for node_id, attrs in graph.nodes(data=True):
        # removeprefix, not lstrip("./"): lstrip strips any leading "." or "/"
        # character, which rewrites ".crush/x" as "crush/x" and breaks every
        # dot-directory prefix match.
        source = str(attrs.get("source_file", "")).removeprefix("./")
        if source.startswith(EXCLUDED_PREFIXES):
            dropped.append(node_id)
    return dropped


#: External test-harness types. They describe how tests are *written*, not what
#: the system is, and because each test file gets its own node they surface as
#: misleading god nodes (``MagicMock`` reached degree 88 in a single file, high
#: enough to enter the top ten "core abstractions").
#:
#: Deliberately excluded from this list: ``FastAPI``, ``Connection``,
#: ``Request``, ``Response``. Those are external too, but they are genuine
#: architectural collaborators — "app.py constructs a FastAPI" is a fact worth
#: keeping in the graph.
TEST_HARNESS_LABELS: frozenset[str] = frozenset(
    {
        "MagicMock",
        "Mock",
        "AsyncMock",
        "NonCallableMock",
        "PropertyMock",
        "MonkeyPatch",
        "TestClient",
        "Page",
        "Browser",
        "BrowserContext",
        "CaptureFixture",
        "LogCaptureFixture",
        "FixtureRequest",
        "TempPathFactory",
    }
)

#: A label longer than this containing whitespace is treated as prose, not a
#: symbol name. Real identifiers are short and unspaced; docstrings are neither.
PROSE_MIN_LENGTH = 60


def is_prose(label: str) -> bool:
    """Return True when ``label`` looks like a docstring rather than a symbol."""
    return len(label) > PROSE_MIN_LENGTH and (" " in label or "\n" in label)


def junk_nodes(graph: nx.Graph) -> tuple[list[str], list[str], list[str]]:
    """Split nodes to prune into (builtin types, docstrings, test harness)."""
    builtins: list[str] = []
    prose: list[str] = []
    harness: list[str] = []
    for node_id, attrs in graph.nodes(data=True):
        label = str(attrs.get("label", "")).strip()
        if label in BUILTIN_LABELS:
            builtins.append(node_id)
        elif label in TEST_HARNESS_LABELS:
            harness.append(node_id)
        elif is_prose(label):
            prose.append(node_id)
    return builtins, prose, harness


#: Upper bound on how many documents may reference one symbol. Above this a
#: symbol is behaving like a generic term rather than a specific reference, and
#: linking every mention would recreate the false-bridge problem that pruning
#: primitive-type nodes solved.
MAX_DOCS_PER_SYMBOL = 30

#: Minimum symbol length considered for doc -> code linking.
MIN_SYMBOL_LENGTH = 6

_MD_LINK = re.compile(r"\]\(([^)]+\.md)[)#]")
_WIKILINK = re.compile(r"\[\[([^\]|#]+)")
#: Identifier-ish tokens in prose. Dots are included so module filenames such as
#: "settings.py" survive tokenisation as a single token.
_TOKEN = re.compile(r"[A-Za-z_][\w.]*")


def _doc_file_nodes(graph: nx.Graph) -> dict[str, str]:
    """Map each documentation file to its file-level node id."""
    docs: dict[str, str] = {}
    for node_id, attrs in graph.nodes(data=True):
        source = str(attrs.get("source_file", ""))
        label = str(attrs.get("label", ""))
        if source.endswith((".md", ".txt")) and label.endswith((".md", ".txt")):
            docs[source] = node_id
    return docs


def _unambiguous_code_symbols(graph: nx.Graph) -> dict[str, str]:
    """Return code symbols specific enough to match by name inside prose.

    Three filters, each guarding against a distinct false positive:

    * **snake_case or a ``.py`` filename only.** Single CamelCase words are
      rejected because the ambiguous ones are ordinary English: ``Settings``
      appeared in 35 documents, ``Context`` and ``Pattern`` in 32, ``FastAPI``
      in 45. Linking those would manufacture hubs, not references.
    * **unique owner.** ``__init__.py`` / ``base.py`` exist in many packages, so
      a name owned by more than one node cannot be resolved to a single target.
    * **no dunders**, which are structural rather than referential.
    """
    owners: dict[str, list[str]] = {}
    for node_id, attrs in graph.nodes(data=True):
        source = str(attrs.get("source_file", ""))
        if not source.endswith((".py", ".js", ".sh", ".mjs")):
            continue
        label = str(attrs.get("label", "")).strip().rstrip("()")
        owners.setdefault(label, []).append(node_id)

    symbols: dict[str, str] = {}
    for label, ids in owners.items():
        if len(ids) != 1 or len(label) < MIN_SYMBOL_LENGTH or label.startswith("__"):
            continue
        if "_" not in label and not label.endswith(".py"):
            continue
        symbols[label] = ids[0]
    return symbols


def link_documents(graph: nx.Graph) -> tuple[int, int]:
    """Add doc->doc and doc->code edges, returning (doc_doc, doc_code) counts.

    AST extraction cannot connect prose to code, which left 262 of 367
    components as single-document islands. Both edge kinds added here are
    derived from text actually present in the files -- no model inference:

    * doc -> doc from markdown links and wikilinks. The link is literally in
      the source, so it is tagged EXTRACTED.
    * doc -> code where a document names a specific symbol or module. The
      mention is real but the referential intent is deduced, so INFERRED.
    """
    docs = _doc_file_nodes(graph)
    symbols = _unambiguous_code_symbols(graph)
    stems = {Path(rel).stem: node for rel, node in docs.items()}

    texts: dict[str, str] = {}
    for rel in docs:
        path = REPO_ROOT / rel
        if path.exists():
            texts[rel] = path.read_text(errors="ignore")

    doc_doc = 0
    for rel, text in texts.items():
        source_node = docs[rel]
        targets: set[str] = set()
        for match in _MD_LINK.finditer(text):
            resolved = (REPO_ROOT / rel).parent / match.group(1)
            try:
                key = str(resolved.resolve().relative_to(REPO_ROOT))
            except ValueError:
                continue
            if key in docs:
                targets.add(docs[key])
        for match in _WIKILINK.finditer(text):
            target = stems.get(match.group(1).strip())
            if target:
                targets.add(target)
        for target in targets - {source_node}:
            if not graph.has_edge(source_node, target):
                graph.add_edge(
                    source_node,
                    target,
                    relation="references",
                    confidence="EXTRACTED",
                    confidence_score=1.0,
                    source_file=rel,
                    weight=1.0,
                )
                doc_doc += 1

    doc_code = 0
    # Tokenise each document once and use set membership, rather than running
    # one regex per symbol across every document. The naive form was ~5,200
    # symbols x ~210 documents of regex work and dominated runtime at over
    # three minutes -- unacceptable for something the post-commit hook runs.
    doc_tokens = {rel: set(_TOKEN.findall(text)) for rel, text in texts.items()}
    mentions: dict[str, list[str]] = {}
    for rel, tokens in doc_tokens.items():
        for label in tokens & symbols.keys():
            mentions.setdefault(label, []).append(rel)

    for label, matched in mentions.items():
        if len(matched) > MAX_DOCS_PER_SYMBOL:
            continue
        target = symbols[label]
        for rel in matched:
            source_node = docs[rel]
            if source_node == target or graph.has_edge(source_node, target):
                continue
            graph.add_edge(
                source_node,
                target,
                relation="references",
                confidence="INFERRED",
                confidence_score=0.7,
                source_file=rel,
                weight=1.0,
            )
            doc_code += 1
    return doc_doc, doc_code


def link_tests(graph: nx.Graph) -> int:
    """Link ``test_foo.py`` to ``foo.py`` where no edge already exists.

    Most test modules are already connected through their imports; this catches
    the remainder, where a test exercises a module via fixtures or monkeypatched
    indirection that AST extraction cannot see. The pairing is a naming
    convention rather than a statement in the source, so INFERRED -- but a
    strong one, hence a high confidence score.
    """
    file_nodes: dict[str, str] = {}
    for node_id, attrs in graph.nodes(data=True):
        source = str(attrs.get("source_file", ""))
        label = str(attrs.get("label", ""))
        if source.endswith(".py") and label.endswith(".py"):
            file_nodes[source] = node_id

    modules = {
        Path(rel).stem: node
        for rel, node in file_nodes.items()
        if not Path(rel).stem.startswith("test_")
    }

    linked = 0
    for rel, node in file_nodes.items():
        stem = Path(rel).stem
        if not stem.startswith("test_"):
            continue
        target = modules.get(stem.removeprefix("test_"))
        if target is None or target == node or graph.has_edge(node, target):
            continue
        graph.add_edge(
            node,
            target,
            relation="tests",
            confidence="INFERRED",
            confidence_score=0.9,
            source_file=rel,
            weight=1.0,
        )
        linked += 1
    return linked


def previous_assignment(graph: nx.Graph) -> dict[str, int]:
    """Read the existing node -> community mapping off the loaded graph."""
    mapping: dict[str, int] = {}
    for node_id, attrs in graph.nodes(data=True):
        community = attrs.get("community")
        if community is not None:
            mapping[node_id] = int(community)
    return mapping


def load_curated_labels() -> dict[int, str]:
    """Load hand-authored community labels from the tracked curated file."""
    if not CURATED_LABELS.exists():
        return {}
    raw: dict[str, Any] = json.loads(CURATED_LABELS.read_text())
    return {int(k): str(v) for k, v in raw.items()}


def load_detection() -> dict[str, Any]:
    """Return a freshly computed corpus detection for the report header.

    The cached ``graphify-out/.graphify_detect.json`` is NOT trusted: it is
    written once per full skill run and can be months old, which made the
    report's "Corpus Check" section quote a file/word count from a corpus that
    no longer exists (and predates the .graphifyignore exclusions). Detection
    is a filesystem walk of a few seconds, so recompute it and fall back to the
    cache only if that fails.
    """
    try:
        from graphify.detect import detect

        return detect(REPO_ROOT)
    except Exception:  # pragma: no cover - fall back to cache when detect fails
        if DETECT_PATH.exists():
            return json.loads(DETECT_PATH.read_text())
        return {
            "total_files": 0,
            "total_words": 0,
            "needs_graph": True,
            "warning": None,
            "files": {"code": [], "document": [], "paper": []},
        }


def component_stats(graph: nx.Graph) -> tuple[int, float]:
    """Return (component count, share of nodes in the largest component)."""
    undirected = nx.Graph(graph)
    sizes = [len(c) for c in nx.connected_components(undirected)]
    if not sizes:
        return 0, 0.0
    return len(sizes), 100.0 * max(sizes) / graph.number_of_nodes()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change without writing any files",
    )
    parser.add_argument(
        "--resolution",
        type=float,
        default=1.0,
        help="Leiden resolution; <1.0 yields fewer, larger communities "
        "(measured effect on this repo is marginal)",
    )
    args = parser.parse_args()

    if not GRAPH_PATH.exists():
        print(f"error: {GRAPH_PATH} not found - run 'graphify update .' first")
        return 1

    data = json.loads(GRAPH_PATH.read_text())
    graph = json_graph.node_link_graph(data, edges="links")
    built_at_commit = data.get("built_at_commit")

    before_nodes = graph.number_of_nodes()
    before_edges = graph.number_of_edges()
    before_components, before_largest = component_stats(graph)
    previous = previous_assignment(graph)

    builtins, prose, harness = junk_nodes(graph)
    stale_paths = excluded_by_path(graph)
    graph.remove_nodes_from(builtins + prose + harness + stale_paths)

    # Link prose to code before dropping isolates and clustering, so the new
    # edges both rescue would-be isolates and inform community detection.
    doc_doc, doc_code = link_documents(graph)
    test_links = link_tests(graph)

    # Drop nodes left with no edges. A relationship graph gains nothing from
    # them: they can never appear in a traversal, yet each becomes its own
    # single-node "community" and inflates the community and component counts.
    # Done after label pruning so nodes orphaned by that step are caught too.
    isolated = [n for n in graph.nodes() if graph.degree(n) == 0]
    graph.remove_nodes_from(isolated)

    communities = cluster(graph, resolution=args.resolution)
    if previous:
        communities = remap_communities_to_previous(communities, previous)
    cohesion = score_all(graph, communities)

    curated = load_curated_labels()
    labels = {cid: curated.get(cid, f"Community {cid}") for cid in communities}

    after_components, after_largest = component_stats(graph)
    median_cohesion = statistics.median(cohesion.values()) if cohesion else 0.0
    before_communities = len(set(previous.values()))

    print(
        f"pruned {len(builtins)} builtin-type + {len(prose)} docstring "
        f"+ {len(harness)} test-harness + {len(stale_paths)} excluded-path "
        f"+ {len(isolated)} isolated nodes"
    )
    print(f"  nodes       {before_nodes} -> {graph.number_of_nodes()}")
    print(f"  edges       {before_edges} -> {graph.number_of_edges()}")
    print(
        f"  linked      +{doc_doc} doc->doc (EXTRACTED), +{doc_code} doc->code "
        f"(INFERRED), +{test_links} test->module (INFERRED)"
    )
    print(f"  communities {before_communities} -> {len(communities)}")
    print(f"  median cohesion       {median_cohesion:.3f}")
    print(f"  components  {before_components} -> {after_components}")
    print(f"  largest component     {before_largest:.1f}% -> {after_largest:.1f}% of nodes")
    applied = sum(1 for cid in communities if cid in curated)
    print(f"  curated labels applied {applied}/{len(curated)}")

    if args.dry_run:
        print("\ndry run - no files written")
        return 0

    gods = god_nodes(graph)
    surprises = surprising_connections(graph, communities)
    questions = suggest_questions(graph, communities, labels)

    report = generate(
        graph,
        communities,
        cohesion,
        labels,
        gods,
        surprises,
        load_detection(),
        {"input": 0, "output": 0},
        str(REPO_ROOT),
        suggested_questions=questions,
        built_at_commit=built_at_commit,
    )
    REPORT_PATH.write_text(report)
    # force=True: pruning legitimately shrinks the graph, which to_json
    # otherwise refuses as a suspected bad rebuild.
    to_json(
        graph,
        communities,
        str(GRAPH_PATH),
        force=True,
        built_at_commit=built_at_commit,
    )
    LABEL_STORE.write_text(json.dumps({str(k): v for k, v in labels.items()}, indent=2))
    print(f"\nwrote {GRAPH_PATH.name}, {REPORT_PATH.name}, {LABEL_STORE.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
