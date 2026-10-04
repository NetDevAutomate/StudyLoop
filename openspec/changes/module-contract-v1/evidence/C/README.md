# Lane C evidence — what is red-first and what is not

Every `*.red.txt` here has the exact command on line 1 and, from the C-review follow-up on,
the `HEAD` sha and UTC time on line 2. A red transcript proves the named tests failed on their
assertions before the implementation landed; a `.green.txt` is the same tests passing after.
This file exists so nobody mistakes "has a green transcript" for "was red first".

## Red-first (transcript names the test)

| Red transcript | Tests proven red | Fixed in |
| --- | --- | --- |
| `check-16-rules.red.txt` | the 33 engine tests (`NotImplementedError` from the C1 stub) | wave 0 → C2 |
| `schema-fixture-integrity.red.txt` | the 5 fixture-integrity tests, red before `feat/module-schema` merged | S2 |
| `check-engine-always-fail.red.txt` | the 33 engine tests + 6 finding-shape tests against an "always fail" validator — the meaningful red (39 failed on assertions) | C2 `c9a979e6` |
| `scaffold-passes-check.red.txt` | `test_scaffold_passes_every_rule`, `test_scaffold_carries_one_offline_echo_drill`, `test_scaffold_ships_its_own_offline_shell_test_not_python` | C3 `2a1b40e9` |
| `add-refuses-unconforming.red.txt` | `test_add_refuses_an_unconforming_module_and_leaves_the_lockfile_byte_identical` | C4 `29d14020` |
| `doctor-probes-installed-only.red.txt` | `test_no_module_installed_runs_no_probe`, `test_module_prerequisites_check_is_registered_under_deps` | C5 `00298cdd` |
| `cli-help-examples.red.txt` | `test_every_command_has_examples_that_resolve_against_the_group`, `test_help_states_exit_codes_and_the_no_network_promise` | C6 `5bfdfa0a` |
| `store-stage-then-check.red.txt` | 6 staging tests (symlink, FIFO, hard link, check-vs-publish race, digest-vs-publish race, tampered snapshot) | review fix 1 |
| `mc009-mc012-coverage.red.txt` | `test_mc009_sees_a_secret_after_a_placeholder_on_the_same_line`, the 5 `test_mc012_rejects_…` cases, `test_mc012_flags_an_empty_pycache_directory` | review fix 2–3 |
| `doctor-kubectl-version-argv.red.txt` | `test_kubectl_is_probed_with_version_client_json_and_parsed` (assertion), `test_version_argv_table_defaults_to_dash_dash_version` (red on import of the missing name, then on assertion) | review fix 4 |
| `snapshot-dirs-read-only.red.txt` | stage 1 (old code): `test_published_snapshot_directories_are_not_writable`, `test_remove_deletes_a_read_only_snapshot`, `test_re_add_drops_a_read_only_orphaned_snapshot`, `test_existing_read_only_snapshot_is_reused_on_re_add_of_identical_content` fail on `os.access(..., W_OK) is False`; stage 2 (publish seals, remove unchanged): `test_remove_deletes_a_read_only_snapshot`, `test_re_add_drops_a_read_only_orphaned_snapshot`, and the two pre-existing remove/re-add tests fail with `PermissionError` from `rmtree` | M1 Q3 (a)+(b) |

## Never red — landed green with the implementing commit

These were written alongside the code they exercise and first ran against it; no transcript
shows them failing. They are regression guards and shape pins, not red-first evidence. The
list is computed from `pytest --collect-only` minus every `FAILED` line in the red
transcripts above (at the review-fix tip).

Wave 1, C3 (`2a1b40e9`) — written after `scaffold.py` and `cli/_module.py` existed:
`test_scaffold_manifest_declares_only_what_the_drill_uses`, `test_scaffold_refuses_an_invalid_id`,
`test_scaffold_refuses_a_non_empty_destination` (the guard branches were in the first version
of the scaffold, so the module.yaml-only red left them green); all eleven `test_module_cli.py`
tests of that commit (`test_group_is_exported_but_not_registered`,
`test_help_lists_the_lifecycle_commands`, the five `test_check_*`, the four `test_new_*`).

Wave 1, C4 (`29d14020`) — only the byte-identical test was shown red; the rest ran first
against the finished store: `test_add_records_id_version_digest_and_snapshot`,
`test_snapshot_is_a_read_only_copy_that_passes_check`, `test_digest_is_content_addressed`,
`test_add_outside_a_git_checkout_records_null_provenance`,
`test_add_inside_a_git_checkout_records_remote_and_head_without_a_fetch`,
`test_checkout_without_a_remote_records_sha_and_null_remote`,
`test_list_is_lockfile_driven_and_sorted`,
`test_re_adding_the_same_id_replaces_the_entry_and_drops_the_orphaned_snapshot`,
`test_remove_is_idempotent_and_lockfile_driven`, `test_load_lockfile_rejects_a_foreign_shape`;
and the six CLI tests `test_add_installs_and_list_shows_it`, `test_add_json_prints_the_lock_entry`,
`test_add_refuses_an_unconforming_module_and_shows_the_finding`, `test_add_rejects_a_missing_path`,
`test_list_with_nothing_installed`, `test_remove_is_idempotent`.

Wave 1, C5 (`00298cdd`) — passed in the red run because the probe code already existed:
`test_probes_only_the_installed_modules_prerequisites_with_version_only`,
`test_missing_tool_fails_and_an_old_version_warns`,
`test_tool_that_rejects_version_flag_is_a_warn_not_a_fail`,
`test_probe_tool_refuses_anything_outside_the_enum`.

Review follow-up — negative-space guards that pass before and after by design:
`test_mc009_still_ignores_a_line_of_placeholders_only`, `test_mc012_does_not_flag_a_posix_shell_shebang`,
`test_add_leaves_no_staging_directory_behind` (the old code left none either),
`test_kubectl_json_without_a_client_version_is_a_warn` (old code also warned, for a different
reason).

M1 Q3 follow-up: none -- all four new tests appear in `snapshot-dirs-read-only.red.txt`.

## Not evidence of anything

`check-16-rules.green.txt`, `scaffold-passes-check.green.txt`, `add-refuses-unconforming.green.txt`,
`doctor-probes-installed-only.green.txt`, `cli-help-examples.green.txt`,
`store-stage-then-check.green.txt`, `mc009-mc012-coverage.green.txt`,
`doctor-kubectl-version-argv.green.txt`, `snapshot-dirs-read-only.green.txt`,
`schema-fixture-integrity.green.txt` are the matching
green runs plus samples (`--json` output, the lockfile, `--help`). They show the state after a
commit, not that anything was ever red. Digests in them are elided to 12 hex characters so the
commit-time entropy detector does not mistake a sha256 for a secret.
