# Completed Tasks

- `BB-2026-09-14-P1` — Ubuntu support. Started, deferred, and completed
  2026-09-14. Owner: Codex; requestor and validation authority: operator.
  Original request/acceptance: [roadmap P1](../ROADMAP.md#p1--ubuntu-support).
  - Delivered in `0d842f3`: apt/dnf package selection, actionable GI dependency
    guidance, and qualified UPower initial-lid Properties query. 72 native tests,
    ShellCheck, prerequisite checks, and isolated staged installation passed.
  - Operator supplied a real installed-baseline run confirming physical lid
    closure/opening events, delayed backlight power-down, verified visible
    restoration, and inhibitor release on this Ubuntu/ARM host. That run also
    exhibited the two already-repaired battery/query defects. It is evidence
    for platform integration, not a claim that the revised binary was tested.
  - Native read-only querying verifies the corrected initial-lid method. Final
    revised-build graph and profile-transition confirmation remain explicitly
    tracked in P2/P3 and `BB-MANUAL-01`; no suspend/resume claim is made.

Record completed work with newest entries at the top. Use dated bullets and
include concise outcomes, owners, ISO 8601 completion timestamps, validation
evidence, important decisions or risk acceptances, and follow-up records.

- `BB-2026-08-13-03` — Add signed average reported battery-percentage change
  per minute and its standard deviation to each per-battery summary.
  - Requestor: Operator
  - Owner: Codex
  - Started: 2026-08-13T15:28:00-07:00
  - Completed: 2026-08-13T16:27:13-07:00
  - Outcome: every selected battery now receives an additional per-minute
    result within the existing one-to-three-line presentation budget. Wide
    output says `avg reported-gauge Δ/min` and `σ` in `pp/min`; compact output
    uses `avgΔ` and a defining footer. Falling SoC is negative, rising SoC is
    positive, and the standard deviation is nonnegative.
  - Statistics: the values are unit conversions of the already-approved,
    duration-weighted transition-rate distribution: signed average change is
    `-weighted_mean_depletion_pp_per_hour / 60`, and standard deviation is
    `weighted_sigma_pp_per_hour / 60`. Raw 15-second differences remain
    forbidden. Unsupported, short, or constant histories show `n/a` rather
    than asserting zero physical drain.
  - Durability: the per-battery structured object advances to statistics
    schema version 2 and adds unit-bearing average-change and
    standard-deviation fields in `pp/min`, using JSON `null` when gated.
  - Documentation: updated source comments, the battery, running-log, and
    terminal-output specifications, approved proposal decision history,
    generated README and man page, and project tracking.
  - Validation: 65 tests passed under Python 3.9.21, system Python 3.12.13,
    and Python 3.14.6. The reported 252-cycle session produces BAT1
    `−0.19 pp/min` average and `0.03 pp/min` standard deviation; BAT0 remains
    explicitly unavailable because it has no reported gauge transitions.
    Compilation, JSON finite-value checks, 40-column/ANSI rendering,
    generated-document reproducibility, man rendering, Bash syntax,
    ShellCheck, prerequisite and installer checks, isolated staged install,
    whitespace, ignore coverage, and FieldManual cleanliness passed.
  - Decision: this direct operator request extends the existing approved
    estimator and does not require a new proposal or FieldManual ECR. The
    existing `.local/` ignore boundary remains sufficient.

- `BB-2026-08-13-02` — Add compact, quantization-aware per-battery trend and
  gauge depletion-rate-variability statistics.
  - Requestor: Operator
  - Owner: Codex
  - Started: 2026-08-13T14:52:19-07:00
  - Completed: 2026-08-13T15:27:34-07:00
  - Authorization: implemented the approved
    [battery-statistics proposal](proposals/approved/BB-PROP-2026-08-13-02-battery-statistics.md)
    and updated the canonical
    [battery-monitoring specification](../docs/specifications/battery-monitoring.md).
  - Review: the requested electrical/lithium, Linux power, and
    statistics/data-science board rejected raw 15-second derivatives, fixed
    windows, inferred wattage, false precision, and acceleration terminology.
    After adversarial review it approved a capacity-only OLS trend plus
    interval-censored gauge-transition rates and the label `gauge
    depletion-rate variability`.
  - Outcome: handled exit now prints one to three width-aware lines per
    battery beneath the chart, or by themselves with `--no-plot`. The summary
    includes endpoints, net percentage-point change, span, coverage,
    whole-run OLS gauge trend, descriptive `R²`, duration-weighted local-rate
    sigma, contextual CV, median one-point cadence, reversals, and explicit
    gates for constant, short, mixed, or interrupted histories. ANSI output
    preserves yellow/blue battery identity and uses magenta for variability;
    plain output retains every meaning and unit.
  - Correctness: sampling and statistics use suspend-inclusive Linux
    `CLOCK_BOOTTIME`. Optional presence and status are reread per cycle.
    Missing readings, long or invalid intervals, and known status changes
    break per-battery local-rate continuity. Raw adjacent differences are
    forbidden because a one-point 15-second update would fabricate a
    `240 pp/h` impulse. Constant histories state that no whole-percentage
    change was reported and never claim zero physical draw.
  - Durability: synchronized sample records now include the timebase,
    presence, and optional kernel status. Final summary and session-end
    records contain versioned, unit-bearing per-battery statistics with JSON
    `null` and explicit validity reasons for unavailable values. Calculation
    or presentation failure cannot bypass backlight, inhibitor, or
    power-profile recovery.
  - Documentation: updated source comments and help, generated README and man
    page, battery-monitoring, running-log, and terminal-output specifications,
    approved proposal, and project tracking.
  - Validation: 65 tests passed under Python 3.9.21, system Python 3.12.13,
    and Python 3.14.6. Tests cover OLS and weighted formulas, constant and
    mixed histories, gaps, status breaks, `CLOCK_BOOTTIME`, log schema,
    40-column and ANSI rendering, `--no-plot`, and a 252-cycle regression of
    the operator's reported staircase (`11.0 pp/h`, `R² .99`, weighted
    `σ 1.8 pp/h`, median `5m15s`). Compilation, generated-document
    reproducibility, Bash syntax, ShellCheck, prerequisite and installer check
    modes, man rendering, isolated staged installation, whitespace, ignore
    coverage, and FieldManual cleanliness also passed.
  - Risk acceptance: no live persistent power, lid, suspend, hibernate, or
    backlight operation was performed. The completed implementation is ready
    for operator testing against real battery behavior.
  - Decision: optional kernel watt/energy telemetry remains a separate future
    proposal because availability, units, driver semantics, and cross-device
    comparability materially differ. FieldManual guidance was sufficient, so
    no ECR was needed. The existing `.local/` rule covers all new local state;
    `.gitignore` requires no addition.

- `BB-2026-08-13-01` — Monitor installed batteries every fifteen seconds and
  render a full-terminal-width, 25-row depletion chart at handled exit.
  - Requestor: Operator
  - Owner: Codex
  - Started: 2026-08-13T12:39:41-07:00
  - Completed: 2026-08-13T12:52:25-07:00
  - Contract: implemented the
    [battery-monitoring specification](../docs/specifications/battery-monitoring.md)
    under direct operator authorization.
  - Outcome: burnbag now discovers up to two present kernel batteries in
    stable name order, samples them before host mutation, every 15,000 ms in a
    persistent GLib loop, and once at handled teardown, and synchronizes every
    cycle to the mandatory running log. `--no-plot` suppresses only graph
    presentation, leaving samples and the final narrative summary enabled.
  - Plot: handled exit renders exactly 25 data rows at current stdout terminal
    width with an 80-column fallback. The Y transform and labels use only
    observed battery percentages; the X axis orders by monotonic time and
    labels actual local samples as `HH:mm`. Consecutive samples are connected,
    while missing observations create gaps. ANSI output uses yellow and blue
    battery lines with green overlap; plain output uses `1`, `2`, and `X`.
  - Safety: battery sysfs access is read-only. Observation failures select
    nonzero status but cannot prevent backlight restoration, inhibitor
    release, or power-profile restoration. Machines without a battery remain
    successful and omit the chart; more than two eligible devices cause an
    explicit, non-fatal selection warning.
  - Documentation: updated source comments, help, startup/shutdown narratives,
    generated README and man page, battery specification, terminal-output
    specification, running-log event coverage, and project tracking.
  - Validation: 59 tests passed under Python 3.9.21, system Python 3.12.13,
    and Python 3.14.6. Tests cover real temporary sysfs fixtures, absent,
    present, malformed, out-of-range and failed attributes, deterministic
    two-battery selection, initial/periodic/final samples, exact timer cadence,
    teardown precedence, 25-row and exact-width geometry, data-bounded scales,
    wall-clock labels, constant values, gaps, overlap colors, plain symbols,
    narrative placement, and `--no-plot`. Both host batteries (`BAT0` and
    `BAT1`) were also discovered and read through the real sysfs implementation
    without mutation. Compilation, Bash syntax, ShellCheck, prerequisite and
    installer checks, generated-document reproducibility, man rendering,
    FieldManual cleanliness, ignore coverage, and whitespace checks passed.
  - Risk acceptance: automated checks did not run a live persistent power
    session, wait through real 15-second timer firings, or render the final
    chart in the operator's actual terminal. Those integrated observations
    remain for operator testing; no live power, lid, suspend, hibernate, or
    backlight mutation was performed.
  - Decision: FieldManual guidance was sufficient and no ECR was needed. The
    existing `.local/` ignore boundary covers disposable test/Ubersight state;
    battery samples use the external runtime log, so `.gitignore` needs no new
    pattern.
  - Follow-up: the operator's hour-long live run exposed touching X-axis
    callouts. The correction and reproduction evidence are recorded in
    [BB-BUG-2026-08-13-01](bugs/closed/BB-BUG-2026-08-13-01-battery-chart-label-overlap.md).

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
