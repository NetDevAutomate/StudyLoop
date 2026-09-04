# Per-harness notes for `studyloop-xtiles-wind-down`

`SKILL.md` is the same in every harness, deliberately. The offer rule is
safety-relevant — offer once, only behind both gates, otherwise say nothing — and
five separately maintained copies of a rule like that drift. So the *procedure* is
shared and only the mechanics below differ.

## Where it is installed

`studyloop install agents` installs the skill **once** into
`~/.agents/skills/studyloop-xtiles-wind-down/`, then symlinks that directory into
each supported harness's own skills location. One hub, several views of it: an edit
lands everywhere at once, and `studyloop install agents --uninstall` unwinds it in
one place.

| Harness | Skills location | Verified |
| --- | --- | --- |
| Codex | `~/.agents/skills/` — the hub itself, read natively; no extra link needed | <https://developers.openai.com/codex/skills>, 2026-09-03 |
| Kiro CLI | `~/.kiro/skills/` | this repository already installs four skills there |
| Claude Code | `~/.claude/skills/` | the Agent Skills convention |
| OpenCode | `~/.config/opencode/skills/` | <https://opencode.ai/docs/skills/>, 2026-09-03 |
| pi | not verified — no skills-directory documentation found | — |

`~/.agents/skills/` is not a StudyLoop invention: Codex reads it as its USER scope,
and OpenCode lists it as a global search path. Using it as the hub means Codex is
served by the hub alone, and it is why the hub is that directory rather than
somewhere under `~/.studyloop/`.

pi gets a self-gated paragraph in its `AGENTS.md` instead. When a pi skills
directory is documented, that paragraph is replaced by a link like the others.

## How you invoke it

| Harness | Invocation |
| --- | --- |
| Codex | `/skills`, or `$studyloop-xtiles-wind-down` in a prompt; also selected implicitly from the description |
| Claude Code | selected from the description when the wind-down phase matches |
| OpenCode | listed in the `skill` tool; loaded with `skill({ name: "studyloop-xtiles-wind-down" })` |
| Kiro CLI | loaded from the skills directory when the description matches |

## Frontmatter

`name` and `description` only. That intersection is what every harness here
accepts: OpenCode recognises exactly `name`, `description`, `license`,
`compatibility` and `metadata` and ignores anything else, and Codex requires `name`
and `description`. `name` must match this directory's name (an OpenCode rule) and
does.

Codex additionally supports an optional `agents/openai.yaml` for display metadata
and invocation policy. Deliberately not shipped: it would apply to one harness only,
and there is nothing to configure that the description does not already say.
