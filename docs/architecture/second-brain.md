# Second-brain contract

The optional second-brain layer publishes read-only **projections** of study
plans and of today's study into a learner-chosen note system (Obsidian first;
xTiles through an assistant). The plan Markdown under `STUDYLOOP_PLANS_DIR`
stays the single source of truth — see
[ADR-0010](../adr/0010-second-brains-are-projections.md) for why projection was
chosen over two-way synchronisation, and the OpenSpec change
`openspec/changes/second-brain/` for the normative requirements and their
scenarios.

This page is the contract: ten clauses that the feature must satisfy, and the
check that proves each one. It is the list a reviewer walks before signing the
work off. Nothing here runs unless `second_brain.provider` is set — clause 1 is
the reason every other clause is safe to add.

Test paths are relative to `packages/studyloop/tests/`. Command checks are run
from the repository root.

## Clauses

| # | Clause | What it means | What proves it |
| --- | --- | --- | --- |
| 1 | **Optional and silent** | Absent `second_brain:` or `provider: none` ⇒ no backend module imported, no file written, no offer printed, no wizard question asked. | `test_second_brain_null.py`; `test_second_brain_cli_core.py::test_status_json_disabled_shape`; `test_second_brain_optionality.py` (`sys.modules`, directory-tree and offer guards, plus `~test_no_automatic_publish_call_sites`); the unchanged `test_setup_wizard.py` |
| 2 | **Projections, not sync** | Backends read plans and today's data and write derived notes; no backend, CLI or agent path writes the plan file. | `test_second_brain_backend_contract.py::test_operations_never_modify_plan_source`; `test_obsidian_backend.py::test_publish_plan_leaves_source_plan_byte_identical` |
| 3 | **Vault boundary** | Every write target resolves under the resolved `vault_path`; `..`, absolute folders and symlink escapes are refused before any write. | `test_obsidian_writer.py::test_path_rejects_*` (three cases); `test_second_brain_config.py::test_parent_traversal_folder_is_config_error` and `::test_absolute_folder_is_config_error` |
| 4 | **Ownership marker** | StudyLoop overwrites only files whose frontmatter carries its `studyloop:` marker with matching identity; anything else is refused with a message. | `test_obsidian_writer.py::test_existing_target_without_marker_is_refused`; `test_obsidian_backend.py::test_edited_projection_is_replaced_with_exact_warning` and `::test_renamed_projection_is_left_untouched`; `test_second_brain_templates.py::test_templates_have_no_ownership_marker` |
| 5 | **Atomic and idempotent** | Temp file plus `os.replace`; unchanged content ⇒ no write and an unchanged mtime. Idempotence is decided by comparing the rendered projection against the file's own contents, not against the `content_hash` in its marker — that value records what StudyLoop last intended to write, so a hand-edited projection would otherwise be reported as unchanged. | `test_obsidian_writer.py::test_atomic_replace_occurs_in_target_directory` and `::test_republish_preserves_existing_mode`; `test_obsidian_backend.py::test_unchanged_projection_does_not_write_or_change_mtime` and `::test_today_republish_does_not_accumulate_content` |
| 6 | **Explicit pull only** | `pull_notes` reads one user-owned sibling file and returns it; it never creates, changes or synchronises anything; the agent folds it into the plan through `studyloop plan …`. | `test_obsidian_backend.py::test_pull_notes_reads_user_owned_sibling_without_writing` and `::~test_pull_notes_missing_sibling_is_found_false_without_error`; `test_cli_brain.py::test_pull_*` |
| 7 | **CLI adapter degrades** | `use_cli` is off by default; the adapter runs only when the binary answers a probe; every failure falls back to the file writer with one WARNING, never a prompt. | `test_obsidian_cli.py` (argv shape, probe, fallback, daily stamp); `test_obsidian_cli_integration.py::test_installed_cli_answers_probe` |
| 8 | **No credential** | Obsidian needs none; xTiles stage 1 keeps OAuth in the client; this feature writes nothing to StudyLoop's secrets store. | `rg -n "secrets" packages/studyloop/src/studyloop/second_brain` prints nothing |
| 9 | **Wind-down offers once** | The offer appears only when `configured` and `supports_publish` are both true; one sentence; never repeated. | Static offer guards in `test_second_brain_optionality.py`; `test_second_brain_docs.py::test_wind_down_offer_matches_documentation`; the agent's actual cadence is confirmed at landing by a recorded wind-down transcript, because a static guard cannot prove how a language model paces a conversation |
| 10 | **Real directories unreachable from tests** | The unit suite cannot resolve the real vault or the real config directory; the run fails if either changed. | `test_obsidian_vault_isolation.py::test_real_default_vault_is_unreachable`; the session-finish hooks in `conftest.py` that snapshot and re-check both directories |

## A note on the test names

Names marked `~` above are proposed rather than observed: they were chosen while
the contract was written, before the implementing lanes landed. They are
confirmed against the real suite when the work lands, and a name that changed in
implementation is corrected here in the same commit that changes it. Every
unmarked name is expected to resolve exactly as written; `just test` is the
arbiter, not this page.
