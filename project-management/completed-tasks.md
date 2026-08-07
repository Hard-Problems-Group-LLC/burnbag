# Completed Tasks

Record completed work with newest entries at the top. Use dated bullets and
include concise outcomes, owners, ISO 8601 completion timestamps, validation
evidence, important decisions or risk acceptances, and follow-up records.

- `BB-2026-08-07-03` — Add default delayed backlight control with an explicit
  opt-out and verified restoration.
  - Owner: Codex
  - Started: 2026-08-07T11:48:08-07:00
  - Completed: 2026-08-07T11:59:13-07:00
  - Outcome: persistent `run*` modes now snapshot all kernel screen-backlight
    devices, turn them off three seconds after process startup, verify the off
    state, and restore and verify a nonzero brightness through one idempotent
    handled-exit teardown. `--do-not-touch-backlight` bypasses discovery and
    mutation. Mutation, verification, compensation, restoration, and setup
    failures are explicit and return nonzero.
  - Documentation: added the durable
    [backlight lifecycle specification](../docs/specifications/backlight-lifecycle.md)
    and updated help, startup/shutdown narratives, generated README, man page,
    comments, options, examples, failure status, and hard-kill limitations.
  - Validation: 18 focused lifecycle, lid, and installer tests passed under
    Python 3.9.21, system Python 3.12.13, and pyenv Python 3.14. Generated docs
    were reproducible; compilation, help, prerequisite/install checks, Bash
    syntax, ShellCheck, man warnings, credential scan, whitespace, and diff
    checks passed.
  - Risk acceptance: no live D-Bus backlight mutation was performed because it
    changes workstation hardware state. Real Fedora/RHEL logind policy, driver
    behavior, three-second timing, visual power-down, and verified restoration
    remain for operator testing.
  - Follow-up: `burnbag-ECR-2026-002` remains open and unsubmitted to request
    language-invariant FieldManual guidance for reversible host-state changes.

- `BB-2026-08-07-02` — Add opt-in `--ignore-lid` run-mode behavior.
  - Owner: Codex
  - Started: 2026-08-07T09:41:12-07:00
  - Completed: 2026-08-07T09:44:47-07:00
  - Outcome: added an off-by-default `--ignore-lid` option for run modes.
    Lid-open events continue to cancel the active safety countdown but no
    longer end the event loop when the option is enabled; later lid closures
    start fresh countdowns. Updated comments, narratives, help, README,
    generated man page, and usage examples.
  - Validation: three focused lifecycle/narrative tests passed under system
    Python 3.12 and pyenv Python 3.14; source compilation, help smoke tests,
    generated-document reproducibility, man-page rendering, staged-install
    help, shell checks, whitespace checks, and diff checks passed.
  - Risk acceptance: live lid signals, suspend timers, D-Bus inhibitors, and
    power operations were not exercised because they change workstation
    state; their boundaries were tested with focused fakes.

- `BB-2026-08-07-01` — Add prerequisite and application installers.
  - Owner: Codex
  - Started: 2026-08-07T09:10:32-07:00
  - Completed: 2026-08-07T09:17:45-07:00
  - Outcome: added an RPM-aware prerequisite installer, standard and
    repository-local development installation modes, explicit distribution
    Python selection, dependency-independent help and argument validation,
    and generated README/man-page installation guidance.
  - Validation: passed `bash -n`, ShellCheck, prerequisite `--check`, standard
    and both dev-mode check spellings, source compilation, system-Python and
    pyenv help smoke tests, argument-order regression checks, man-page warning
    checks, generated-document reproducibility, and isolated staged standard
    and development installs under `.local/tmp/`.
  - Risk acceptance: live suspend, hibernate, inhibitor, and power-profile
    operations were not exercised because they change workstation state; the
    installer itself was not run against live system destinations.
  - Follow-up: `burnbag-ECR-2026-001` remains open and not yet submitted to
    FieldManual for language-invariant installer and prerequisite guidance.
