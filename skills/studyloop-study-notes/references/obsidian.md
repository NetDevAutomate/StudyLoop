# Obsidian notes

Obsidian is a first-class destination, independent of xTiles. Ordinary Markdown
files in a vault are sufficient; do not require a plugin, MCP server, or CLI.

## Locate the vault and preserve its conventions

Use the vault and note folder the user names, or the existing source-note path
when it clearly identifies the destination. Confirm the vault root (normally
the directory containing `.obsidian`) before constructing vault-relative links.
Read applicable vault instructions and a representative existing note. Do not
change vault settings or install plugins to make generated notes work.

Keep course-specific notes with their course. Do not replace an existing large
summary when adding lesson notes. Inspect current files before choosing names,
and preserve existing metadata and learner annotations on updates.

## Adapt the shared templates

- Use one UTF-8 `.md` file per lesson plus `00-section-overview.md` in the chosen
  section folder. Avoid filename separators and filesystem-reserved characters;
  preserve the source lesson ID and sequence in properties.
- Keep valid YAML properties at the start of the file. Use strings for IDs and
  URLs, lists for tags/aliases, and ISO dates for creation/update fields. Add
  only known values. Preserve unknown properties already supplied by the user.
  Quote special characters and titles containing colons safely.
- For new Obsidian-native notes, prefer `[[vault-relative/path|Display title]]`
  links, without the `.md` suffix. Full vault-relative paths disambiguate common
  filenames such as `00-section-overview`. Preserve existing Markdown links if
  that is the user's convention; encode spaces and special URL characters in
  their destinations. Verify the target file exists rather than relying on a
  similar note title.
- Retain language-labelled fenced code and `mermaid` diagrams. Use core Obsidian
  features only unless the user asks for a particular community plugin. A small
  diagram should explain a relationship, not decorate every note.
- An optional `> [!tip] Start here` callout can highlight the first action.
  Suggested answers can use a collapsed `> [!question]- Suggested answers`
  callout so the learner can attempt retrieval before revealing them. Preserve
  any learner answers outside the generated answer key.
- Do not leak xTiles directives (`@position`, `<task>`, palette directives) into
  Obsidian notes. In Obsidian-only mode, omit xTiles IDs, links and receipts.

## Links when both destinations are requested

After xTiles returns page IDs, add `xtiles_view_id` and `xtiles_url` properties
and a normal HTTPS link in the corresponding Obsidian note. Add the reciprocal
link in xTiles only when the vault identity is known:

```text
obsidian://open?vault=<percent-encoded-vault-name>&file=<percent-encoded-vault-relative-path>
```

Encode the vault and file query values separately, including spaces, `&`, `#`,
and path separators. This opens a local app; it is not a public URL or cloud
copy, and requires that vault on the user's device. Verify that the decoded file
path resolves to the intended note inside the vault. Never put a machine-specific
absolute path in the reusable skill or claim a local link works on every device.

On a later update, reuse known page IDs after reading the corresponding xTiles
page. Preserve each destination's learner-owned content; copying the generated
body from one destination over the other is not a safe update strategy.

## Verify and report

Check YAML parsing, filled template variables, existing internal-link targets,
closed code fences, and stable note identities. Check executable examples only
after inspecting them, and describe the scope of that check accurately.

Open the lesson and overview in Obsidian reading view when app access is
available. Inspect the diagram, code, properties, internal navigation, and any
collapsed answer callout. Editing source text is not proof of rendered output.
If app access is blocked or unavailable, report file validation separately from
the pending visual check. Do not pretend a generic Markdown preview is Obsidian.

Official references: [internal links](https://help.obsidian.md/links),
[properties](https://help.obsidian.md/properties),
[Obsidian URI](https://help.obsidian.md/uri), and
[formatting syntax](https://help.obsidian.md/syntax).
