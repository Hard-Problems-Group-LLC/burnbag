# Completed Tasks

Record completed work with newest entries at the top. Use dated bullets and
include concise outcomes, owners, ISO 8601 completion timestamps, validation
evidence, important decisions or risk acceptances, and follow-up records.

- `BB-2026-08-07-05` — Specify and implement a mandatory synchronized running
  log for safety-relevant operational sessions.
  - Requestor: Operator
  - Owner: Codex
  - Started: 2026-08-07T18:26:39-07:00
  - Completed: 2026-08-07T18:48:58-07:00
  - Authorization: approved
    [durable-running-log proposal](proposals/approved/BB-PROP-2026-08-07-01-durable-running-log.md)
    and implemented
    [runtime-log specification](../docs/specifications/runtime-log.md).
  - Outcome: accepted operational sessions now create an append-only JSON
    Lines log under the invoking XDG state boundary, or an explicit absolute
    `--log-file`. Every record is size-checked, serialized under an exclusive
    cross-process lock, appended with direct writes, and synchronized with
    `fsync`. Session start precedes runtime initialization; mutation intent
    precedes safety-relevant host calls; handled session end follows teardown.
  - Safety: secure file opening rejects symlinks, non-regular and multiply
    linked files, wrong ownership, and unsafe parent permissions. Log failures
    stop new mutation, select nonzero status, and request shutdown, while a
    teardown phase continues backlight restoration, inhibitor release, and
    power-profile restoration without depending on the failed log. Partial
    trailing forensic bytes are preserved and separated before a later session.
  - Documentation: updated comments, help, startup/shutdown narratives,
    generated README and man page, proposal, specification, path/permission
    policy, schema, failure semantics, retention limits, and examples.
  - Validation: 46 tests passed under Python 3.9.21, system Python 3.12.13,
    and Python 3.14.6. Real-file tests covered schema, modes, ordering,
    per-record `fsync`, partial tails, explicit/default paths, write and sync
    failure, record limits, symlink/hard-link and unsafe-directory refusal,
    pre-controller finalization, and teardown precedence. A four-process test
    verified non-interleaved shared-file appends; representative fake host
    boundaries verified durable intent before power-profile, inhibitor, and
    backlight mutation. Compilation, generated-document reproducibility, help,
    prerequisite/install checks, Bash syntax, ShellCheck, man rendering,
    whitespace, FieldManual cleanliness, and diff checks passed.
  - Risk acceptance: live power-profile, inhibitor, lid, suspend, hibernate,
    and backlight mutations were not run during automated validation. The
    owned log path and real filesystem operations were exercised; real host
    lifecycle correlation remains for operator testing.
  - Decision: burnbag does not automatically rotate, truncate, upload, or
    delete logs. Retention and rename-based external rotation are operator
    responsibilities. FieldManual guidance was sufficient; no ECR was needed.

- `BB-2026-08-07-04` — Add adaptive terminal styling and a useful
  zero-argument guide.
  - Requestor: Operator
  - Owner: Codex
  - Started: 2026-08-07T17:00:54-07:00
  - Completed: 2026-08-07T17:12:15-07:00
  - Outcome: runtime statuses, startup/shutdown narratives, `--help`, usage
    errors, and the zero-argument quick-start guide now receive readable ANSI
    hierarchy when their output stream is an interactive terminal. Redirected
    streams remain plain. `--no-color`, `NO_COLOR`, and `TERM=dumb` disable
    styling globally while textual labels preserve every status meaning.
  - Compatibility: burnbag disables Python 3.14's independent argparse color
    renderer so its plain-output controls behave consistently across all
    supported Python versions. Help and command-line errors remain independent
    of PyGObject and host-state initialization.
  - Documentation: updated generated README and man-page sources and outputs,
    including exit status 2, and added the durable
    [terminal-output specification](../docs/specifications/terminal-output.md).
  - Validation: 32 tests passed under Python 3.9.21, system Python 3.12.13,
    and Python 3.14.6. Source compilation, TTY help smoke testing, explicit and
    environmental color opt-outs, generated-document reproducibility, Bash
    syntax, ShellCheck, man rendering, prerequisite/install checks, whitespace,
    git-ignore review, and diff checks passed.
  - Decision: no FieldManual ECR was needed. Its language-invariant terminal
    UI guidance covered hierarchy and the requirement not to convey meaning
    only through color; capability detection and ANSI mechanics are correctly
    project-specific.

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
