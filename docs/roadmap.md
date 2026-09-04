# Roadmap

StudyLoop is an early open-source release. This roadmap describes product
outcomes rather than promising dates or version numbers.

## Now: make the core loop dependable

The current release supports:

- local Study Session and Body Double workspaces with supported AI CLI agents;
- energy-aware Socratic sessions, parking, timers, and session close-out;
- flashcards, quizzes, spaced repetition, and a single recommended next action;
- local content generation from Markdown, text, and supported PDF sources;
- study plans stored as readable Markdown with session checkpoints;
- searchable session history and optional Obsidian export;
- laptop and tablet Web UI layouts.

Work in this phase is about trustworthy installation, recovery, accessibility,
and documentation. A feature is not considered ready merely because a backend
route or design document exists; the user-facing path and its evidence must work.

## Next: reduce setup and planning friction

The next product improvements are:

- a simpler installation and upgrade path than a source checkout;
- a guided planning conversation that turns a learner's own words into a useful
  plan without silently inventing goals or evidence;
- stronger continuity between active plans, Today, review, and the next session;
- a choice of second brain, so a plan and today's next action can appear where a
  learner already keeps their thinking. Obsidian is the free, local option and
  works now; support for a connected visual planner is served through the
  learner's own assistant rather than by StudyLoop holding a credential;
- clearer in-product explanations when an agent, voice backend, or optional
  integration is unavailable;
- broader manual accessibility testing and more contributor-friendly UI evidence.

## Later: broaden access carefully

These are useful directions, but they should not weaken the current local-first
workflow:

- a supported phone experience designed for the smaller screen rather than a
  compressed desktop layout;
- offline review where the data and conflict model are explicit;
- easier community-created courses and learning templates;
- localisation;
- additional agent and local-model integrations with the same session guarantees.

## Not a current promise

StudyLoop does not currently promise a hosted service, mobile app, PyPI package,
Homebrew formula, phone support, or offline Web UI. Historical implementation
plans live in the repository for maintainers, but they are deliberately excluded
from the public documentation site.

Have a workflow that should influence the order? Open an
[issue](https://github.com/NetDevAutomate/StudyLoop/issues) with the learning
problem, the device or agent involved, and what a successful outcome would look
like.
