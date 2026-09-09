# Glossary & Acronyms — Session Weaver / storage PoC

Plain-English definitions for every acronym and term of art used in this
directory's documents (RESULTS-*.md, finding-*.md, plans, diagrams).

## Scoring & retrieval

| Term | Meaning |
|---|---|
| **recall@5** | Of all benchmark questions, the fraction where at least one correct session appeared in the top-5 results. Higher = better (0–1). |
| **MRR@5** | Mean Reciprocal Rank: where the first correct hit ranked — 1st=1.0, 2nd=0.5, 5th=0.2, missed=0, averaged over questions. Rewards ranking the answer at the top. Higher = better. |
| **FTS / FTS5** | Full-Text Search, SQLite's built-in text index (version 5). Finds documents by keywords, ranked by BM25. |
| **BM25** | The standard keyword-relevance ranking formula FTS5 uses (term frequency × rarity, length-normalised). Lower BM25 score = better match in SQLite's convention, but our tables always report recall/MRR where higher is better. |
| **RRF** | Reciprocal Rank Fusion: merges two or more ranked lists by scoring each item 1/(60+rank) per list and summing. Simple, robust way to combine keyword and vector results without tuning weights. |
| **Embeddings / vectors** | Numeric representations of text (here 384 numbers per message, model bge-small-en-v1.5) where similar meaning ⇒ nearby vectors. Enables "paraphrase" search that keyword matching misses. |
| **AND→OR planner** | Our query strategy: first require ALL question terms (precise), and only if that returns too few results, fall back to ANY term (broad). |
| **Hybrid (H)** | RRF fusion of the FTS planner and embeddings — the measured best retrieval candidate. |
| **Gold / gold set** | The benchmark's answer key: for each question, the session(s) verified to contain the answer. |
| **K / P / R questions** | Benchmark categories: Keyword-friendly, Paraphrase (different wording than the source), Relational (multi-hop, connects facts). |
| **xfail** | pytest marker: a test EXPECTED to fail, documenting a known limitation; "strict" means the suite errors if it unexpectedly passes. |

## Ontology & knowledge

| Term | Meaning |
|---|---|
| **Ontology** | A formal model of a domain: classes (kinds of things), their attributes, and named relationships between them — plus the instances that conform to it. |
| **T-Box** | "Terminology box": the schema half of an ontology — classes, attributes, properties with domain→range. Ours: 7 classes, 6 properties. |
| **A-Box** | "Assertion box": the instance half — actual individuals and relation triples. Ours: 13,528 individuals, 29,475 relations at 5,813 sessions (`ontology-tier1-baseline.json`, 2026-09-08); the live graph grows with the archive. |
| **Triple** | One relation fact: subject → predicate → object (e.g. session:X —touched→ artifact:Y). |
| **Domain / range** | A property's typing rule: which class the subject (domain) and object (range) must belong to. "0 violations" = every triple obeys its property's typing. |
| **Individual** | One concrete instance of a class (a specific session, file, command). |
| **Entity resolution** | Recognising that mentions in different sessions refer to the same individual — how unrelated conversations become a connected graph. |
| **Tier-1** | Deterministic ontology population at ingest: parsed from data by code, no LLM, $0 (projects, artifacts, commands, test runs). |
| **Tier-2** | Concepts authored by the session's own agent at wind-down (Decision, Finding, Problem, Preference, Procedure) — judgment-requiring knowledge. Stored in the concept sidecar (`context_concepts`), quote-bound to evidence by a SQL trigger. **Not** part of the ontology graph: there is no `Decision` class and no property whose range is a concept. |
| **Wind-down** | The end-of-session step where the agent records what was learned/decided while it still has full context. Writes JSON → SQLite via `memory_winddown`; never writes OKF. |
| **OKF** | Open Knowledge Format (Google Cloud, 2026): knowledge as plain Markdown files with an eight-key YAML frontmatter (type, title, description, tags, sources, verified, confidence, actor). The PoC authored 2,035 such files; in Phase 2 it is a **frozen, import-only legacy format** (`concept import-okf`), and 0 of 2,033 imported concepts bound to an exact citation. The frontmatter has no cross-link syntax. |
| **Frontmatter** | The YAML metadata block between `---` markers at the top of a Markdown file. |
| **Provenance** | The trail from a derived fact back to its sources (which session/messages it came from, extracted by what, when). |

## Project & process

| Term | Meaning |
|---|---|
| **PoC** | Proof of Concept — a small build to answer a design question with evidence. |
| **MCP** | Model Context Protocol — the standard by which agents call external tools (e.g. the session-db query server). |
| **ADR** | Architecture Decision Record — a short document capturing one decision and its rationale. |
| **WP-n** | Work Package n — a unit of work in the phase plans. |
| **BL-n** | Backlog item n (BL-1 sync tiebreak, BL-2 repair dedup, BL-3 verified hooks, BL-4 sync fixes). |
| **Gate** | A verification checkpoint that must pass before proceeding (Phase 0 had gates 1–3 plus a council gate). |
| **Council** | Multi-model review through the LiteLLM gateway: independent reviewer models plus a judge model arbitrating. |
| **Harness** | A coding-agent tool that produces sessions: Claude Code, Codex, Kiro CLI, OpenCode, pi, Grok. |
| **Cutover** | The switch from the old sessions.db to the freshly rebuilt one (old preserved as sessions-orig.db). |
| **Day-1 DB** | The rebuilt sessions.db: fresh native export + merged history + ontology tables, zero empty rows. |

## Storage & sync

| Term | Meaning |
|---|---|
| **WAL** | Write-Ahead Logging — SQLite's journal mode; explains the -wal/-shm sidecar files and why raw `cp` of a live DB is unsafe. |
| **Online Backup / .backup** | SQLite's safe way to copy a live database (consistent snapshot, WAL-aware). |
| **FK** | Foreign Key — a row referencing another table's row; "FK check empty" = no dangling references. |
| **quick_check** | SQLite's fast integrity check ("ok" = structurally sound). |
| **LWW** | Last-Writer-Wins — conflict rule where the newest change survives; the planned machine_id+seq tiebreak makes it decidable. |
| **Tombstone** | A "deleted" marker kept so other machines learn about the deletion during sync instead of resurrecting the row. |
| **Anti-resurrection filter** | sync.py:586-590 — merge SQL refuses to re-insert empty-content rows absent at the destination. |
| **Idempotent** | Running the operation again changes nothing (second apply/sync = no-op). Key safety property we test for. |
| **SAST** | Static Application Security Testing (bandit) — scans source for security bugs without running it. |
| **launchd sweep** | The macOS scheduled job running session-export every 4 h so history is captured even when hooks miss. |
