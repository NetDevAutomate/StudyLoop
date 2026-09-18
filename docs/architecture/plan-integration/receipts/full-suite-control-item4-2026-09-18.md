# Full suite, matched control — item 4 GREEN · 2026-09-18

Two full `pytest` runs in parallel on this host (macOS sandbox), same command:
`uv run --group dev pytest -q -p no:cacheprovider -rfE`.

- **item 4 tree** (working tree on `feat/plan-close`, GREEN uncommitted at run time): 30 failed / 7233 passed / 4 skipped / 14 errors (952 s).
- **control** (clean worktree at the RED tip `f1c52ce8`, own `uv sync --group dev --all-packages`): 37 failed / 7191 passed / 16 skipped / 14 errors (956 s).

Sorted failure+error id sets, diffed:

- item4 − control = **∅** (zero regressions).
- control − item4 = exactly the seven item-4 RED tests (red on the control tip by construction).
- shared: **44** ids — the sandbox-environmental class (journey world guards, acceptance isolation, harness-matrix live mechanics, brain CLI, doctor second-brain vault, one agent-session-tools eval arm). Items 3 and 3b recorded 45 shared ids, but that list was never persisted (session scratch), so which id differs cannot be named here; what this run proves is only that the two trees fail on the same 44 and differ on exactly the seven REDs. The list below is committed so the next item can diff against it by name.

## Shared environmental ids

```
packages/studyloop/tests/journeys/test_journey_world_guards.py::test_a_journey_transcript_records_every_command_and_its_output
packages/studyloop/tests/journeys/test_journey_world_guards.py::test_every_world_path_lives_under_the_temp_root
packages/studyloop/tests/journeys/test_journey_world_guards.py::test_redaction_leaves_the_vault_relative_paths_a_reader_needs
packages/studyloop/tests/journeys/test_journey_world_guards.py::test_the_cli_runs_inside_the_world_not_the_host
packages/studyloop/tests/journeys/test_journey_world_guards.py::test_the_environment_handed_to_the_child_names_no_real_directory
packages/studyloop/tests/journeys/test_journey_world_guards.py::test_the_transcript_carries_no_username_or_home_path
packages/studyloop/tests/journeys/test_journey_world_guards.py::test_the_week_world_cannot_resolve_the_personal_vault
packages/studyloop/tests/journeys/test_journey_world_guards.py::test_the_week_world_cannot_resolve_the_real_config_dir
packages/studyloop/tests/journeys/test_journey_world_guards.py::test_the_week_world_starts_with_no_provider
packages/studyloop/tests/journeys/test_obsidian_learners_week.py::test_a_learners_week_in_order
packages/studyloop/tests/journeys/test_xtiles_learners_week.py::test_a_study_day_when_the_provider_cannot_publish
packages/studyloop/tests/journeys/test_xtiles_learners_week.py::test_the_canary_check_can_actually_fail
packages/studyloop/tests/journeys/test_xtiles_learners_week.py::test_the_xtiles_week_stores_no_credential
packages/studyloop/tests/journeys/test_xtiles_prompt_inputs.py::test_the_project_prompt_input_is_producible
packages/studyloop/tests/test_acceptance_isolation.py::TestRealHarnessAuthMode::test_default_mode_is_unchanged_and_records_itself
packages/studyloop/tests/test_acceptance_isolation.py::TestRealHarnessAuthMode::test_harness_home_is_real_but_every_studyloop_pointer_is_scratch
packages/studyloop/tests/test_acceptance_isolation.py::TestRealHarnessAuthMode::test_sweep_removes_the_tmux_socket_dir_even_though_it_is_outside_home
packages/studyloop/tests/test_acceptance_isolation.py::TestRealHarnessAuthMode::test_sweep_still_never_touches_the_real_home
packages/studyloop/tests/test_acceptance_isolation.py::TestScratchEnvironmentContextManager::test_swept_even_when_the_body_raises
packages/studyloop/tests/test_acceptance_isolation.py::TestScratchTmuxSocketDirIsUsable::test_a_real_tmux_session_starts_under_the_scratch_socket_dir
packages/studyloop/tests/test_acceptance_isolation.py::TestSweepGuards::test_normal_scratch_sweeps_cleanly
packages/studyloop/tests/test_acceptance_isolation.py::TestTmuxDescendantStopper::test_sweep_kills_the_scratch_tmux_server_first
packages/studyloop/tests/test_cli_brain.py::test_dry_run_reports_a_refusal_it_would_actually_hit
packages/studyloop/tests/test_cli_brain.py::test_enable_prints_the_resolved_vault
packages/studyloop/tests/test_cli_brain.py::test_publish_missing_vault_exit_1_nothing_written
packages/studyloop/tests/test_cli_brain.py::test_pull_prints_notes
packages/studyloop/tests/test_cli_brain.py::test_template_install_creates_only
packages/studyloop/tests/test_cli_brain.py::test_template_install_is_all_or_nothing
packages/studyloop/tests/test_cli_brain.py::test_template_install_refuses_existing
packages/studyloop/tests/test_config_init_second_brain.py::test_what_is_written_loads_back_cleanly
packages/studyloop/tests/test_doctor_second_brain.py::test_rows_vault_missing_warns
packages/studyloop/tests/test_fresh_install_scope.py::test_studyloop_study_exits_2_with_the_diagnostic_on_a_virgin_home
packages/studyloop/tests/test_harness_matrix_live_mechanics.py::TestAuthModeRecording::test_real_auth_scratch_records_real_auth_for_every_harness[claude]
packages/studyloop/tests/test_harness_matrix_live_mechanics.py::TestAuthModeRecording::test_real_auth_scratch_records_real_auth_for_every_harness[codex]
packages/studyloop/tests/test_harness_matrix_live_mechanics.py::TestAuthModeRecording::test_real_auth_scratch_records_real_auth_for_every_harness[grok]
packages/studyloop/tests/test_harness_matrix_live_mechanics.py::TestAuthModeRecording::test_real_auth_scratch_records_real_auth_for_every_harness[kiro]
packages/studyloop/tests/test_harness_matrix_live_mechanics.py::TestAuthModeRecording::test_real_auth_scratch_records_real_auth_for_every_harness[opencode]
packages/studyloop/tests/test_harness_matrix_live_mechanics.py::TestAuthModeRecording::test_real_auth_scratch_records_real_auth_for_every_harness[pi]
packages/studyloop/tests/test_harness_matrix_live_mechanics.py::TestAuthModeRecording::test_scrubbed_scratch_keeps_the_original_split
packages/studyloop/tests/test_obsidian_vault_isolation.py::test_an_explicit_configured_vault_still_wins_over_the_override
packages/studyloop/tests/test_obsidian_vault_isolation.py::test_real_default_vault_is_unreachable
packages/studyloop/tests/test_obsidian_vault_isolation.py::test_the_isolation_override_is_set_for_every_test
packages/studyloop/tests/test_second_brain_cli_core.py::test_status_json_obsidian_shape
packages/studyloop/tests/test_second_brain_cli_core.py::test_status_reports_a_missing_vault_without_failing
```

## Only on the control (the REDs)

```
packages/studyloop/tests/test_cli_plan_seam.py::test_plan_close_launches_the_architect_with_the_assessment_in_the_brief
packages/studyloop/tests/test_cli_plan_seam.py::test_plan_close_on_an_unfinished_plan_refuses
packages/studyloop/tests/test_now_plan_guidance.py::test_completion_action_carries_the_end_assessment_and_proposes_extend_when_concepts_are_due
packages/studyloop/tests/test_now_plan_guidance.py::test_completion_action_proposes_close_when_the_assessment_is_clean
packages/studyloop/tests/test_now_plan_guidance.py::test_completion_assessment_failure_keeps_the_sentence_and_warns
packages/studyloop/tests/test_now_plan_guidance.py::test_completion_never_changes_status
packages/studyloop/tests/test_now_plan_guidance.py::test_completion_review_does_not_count_new_topic_rows_as_due
```
