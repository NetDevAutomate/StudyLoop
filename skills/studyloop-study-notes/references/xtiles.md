# Presenting study notes in xTiles

Use the connected xTiles tools by capability; client-specific tool prefixes vary.
MCP authentication belongs to the client, not this skill. A local Markdown-only
run must not require xTiles authentication.

## Discover and read first

1. Check `xtiles_list_workflows` for a suitable current recipe. Adapt a relevant
   recipe to the requested existing project rather than creating another tracker.
2. Read `xtiles_get_docs` for `xtiles://guide/markdown/overview`, `/canvas`,
   `/blocks`, and `/collections` before constructing import Markdown. These
   guide suffixes are relative to `xtiles://guide/markdown`.
3. Confirm access with identity and project-list reads. Use the user's selected
   project or a clearly matching existing study project. Read project structure
   and candidate page content to deduplicate by stable note ID and source.

## Map the note

- `##` starts a page, `###` starts a tile. Local frontmatter is not page content.
  Do not send an ordinary note's heading hierarchy unchanged.
- One page per lesson, plus a section-overview page. A reusable template page
  may contain clear authoring prompts because the user explicitly requested a
  template; distinguish it from generated lesson content.
- Put a short `Start here` tile first. Group the remaining material into
  foundations, core concept, walkthrough/principles, recall prompts, suggested
  answers, learner observations, and sources as appropriate. Answers belong
  below the questions, not in an adjacent first-screen tile.
- Keep the overview small: start point, section purpose, lesson map, sources and
  coverage. A long lesson map can occupy a full-width tile.
- The documented importer strips backticks and does not preserve code styling.
  Keep runnable code and Mermaid in the full Markdown note. In xTiles explain
  the transformation in prose or a short quote and link the full note when a
  companion note exists; do not claim executable-code or diagram fidelity.
  If the user needs full code
  in xTiles, verify a supported rendering route before promising it.
- In xTiles-only mode, keep the lesson useful without Obsidian: include the
  explanation, before/after behaviour, walkthrough, retrieval prompts, answers,
  and sources in the page. If full code or diagrams are important, explain the
  formatting constraint and deliver companion Markdown in the chat or an
  already-authorised local output. Do not fabricate a full-note link or require
  a vault. The user can choose whether to add a companion destination.
- When adapting an Obsidian note, resolve wikilinks to actual corresponding
  xTiles page URLs where available. Translate callouts to ordinary tile text
  and preserve the question/answer separation. Do not paste raw wikilinks,
  callout markers, embeds, YAML properties, or Obsidian-only block IDs into
  xTiles as if they were supported controls. Use readable text when no target
  page exists, and record the missing link rather than inventing one.
- Use an Obsidian URI only with a known vault and vault-relative file path,
  percent-encoding both values. Label it as a local Obsidian link; it requires
  that vault on the device. Otherwise use an authorised accessible document URL
  or plain location text. Never upload private notes just to manufacture a link.
- Put each link on its own line. A table belongs under a tile heading; directly
  under the page heading it can become a collection. Collection rows cannot be
  written through the currently documented MCP tools.
- Separate paragraphs with blank lines: adjacent lines can merge into one block.
  Numeric table columns may discard leading zeros (`002` becomes `2`). Keep
  padded identifiers in titles or use a text label at initial creation if that
  formatting matters. Patching text into an existing numeric column is rejected;
  preserve the correct numeric values rather than repeatedly retrying the patch.
- Respect the documented 40-block tile limit; split long content. Keep each
  tile focused and use whitespace rather than cramming in a full course chapter.

## Saved templates versus template pages

Creating a page containing a reusable layout does not register it in xTiles'
My Templates gallery. For a template request, distinguish these two delivery
steps explicitly. The currently exposed MCP tools create pages but have no
Save as Template operation; recheck capabilities before claiming otherwise.

After preparing and verifying the blank lesson and overview pages, use an
authenticated browser, if available, to open each page tab's three-dot menu
and select Save as Template. Check My Templates before saving to avoid
duplicates, then verify the saved entries. If browser access is unavailable,
return direct links to the prepared pages and those exact remaining steps;
report gallery registration as incomplete. Do not save the user's entire study
project or a filled lesson pilot as a template by accident.

Official instructions: [How to Make and Save Your Own Templates](https://help.xtiles.app/en/articles/8374545-how-to-make-and-save-your-own-templates).

## Write and verify

Use `xtiles_create_view_from_markdown` for missing pages. Use read-then-patch for
updates: `xtiles_get_view_content` followed by unique exact replacements through
`xtiles_patch_view_content`. Do not rebuild a whole page over user annotations.
Never patch `##` titles; use the appropriate page-metadata tool to rename them.

After creating, read content, layout and tile styles. `@position` is only an
import hint. Use `xtiles_set_page_layout` with real tile IDs and returned grid
bounds to set non-overlapping rectangles. Use a restrained pair such as SAIL and
ATHENS_GRAY with LIGHTER_HEADER styling. Read layout/styles back to verify.
On existing pages, leave unrelated tiles and their positions/styles alone.

Store actual returned page IDs/URLs with the local notes or a private receipt,
so a rerun can target the same pages. Link lessons and overview only after their
IDs exist. A group is optional; group only the pages created for this request.
In xTiles-only mode with no authorised local output, put the stable note ID and
source locator in the page and return its real URL in chat; use those plus the
project structure to find it again. Local storage is not a prerequisite.

After an ambiguous write failure, read project structure to determine whether
the page exists before retrying. On authentication or permission denial, stop
dependent writes, retain local notes, and report the actual error. If creation
works but styling/editing fails, link the created page and state the partial
result; do not create another page as a workaround.

Read-back confirms stored content and layout, not appearance. Visually inspect
the page when browser access is available, including links, clipped text, and
question/answer order. Report visual checks separately when unavailable.
