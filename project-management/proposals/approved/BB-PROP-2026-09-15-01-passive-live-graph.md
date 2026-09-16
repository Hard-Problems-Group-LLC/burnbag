# Passive Live Battery Graph

- ID: `BB-PROP-2026-09-15-01`
- Author: Codex
- Sponsor and decision authority: Operator
- Date: 2026-09-15
- Status: Approved by explicit operator pre-approval; not implemented
- Execution status: Queued behind installer bug work. Do not begin implementation
  as part of drafting this proposal.
- Affected projects or audiences: burnbag terminal users and maintainers
- Related work:
  - Backlog item `BB-2026-09-15-GRAPH-ONLY` in [the backlog](../../backlog.md)
  - [Battery monitoring](../../../docs/specifications/battery-monitoring.md)
  - [Terminal output](../../../docs/specifications/terminal-output.md)
  - [Continuous history](../../../docs/specifications/continuous-history.md)
  - [Runtime log](../../../docs/specifications/runtime-log.md)

## Problem Statement

Operators can graph completed runs, query stored history with `--graph`, and
browse snapshots with the GTK viewer. None provides a continuously refreshed
terminal battery graph without entering a power-control run. The requested
mode should be useful on its own, including when the continuous collector is
absent, while allowing ordinary system sleep policy to operate.

Original operator request:

> Add a new mode, "graph-only", that does NOT prevent suspends or do anything
> else besides tracking and graphing the battery state, refitting and
> rerendering it to the width of the screen once every
> --graph-interval-seconds <seconds=1> seconds.

The operator also requested fixed intervals by default and an alternative
increasing interval passing through 0.1 seconds initially, 1 second at ten
seconds runtime, and 10 seconds at one hundred seconds runtime. The latter
must reject an explicit `--graph-interval-seconds`.

## Goals

- Add `burnbag graph-only` as a persistent, passive live battery display.
- Observe actual battery readings and refit the current session's graph to
  terminal width on every refresh; resize must not discard observations.
- Support the requested fixed and logarithmic interval options and exact
  curve anchors, with no ten-second cap.
- Acquire no block or delay inhibitors and make no power-profile, backlight,
  lid-policy, charging, or service changes.
- Work independently of collector availability and restore any terminal state
  changed by the display on handled exit.

## Non-Goals

- Implement or install the feature during this proposal-writing task.
- Repair the upcoming installer bugs as part of this feature.
- Change collection cadence, storage, schema, or behavior of existing services,
  `run*` modes, historical queries, or the GTK viewer.
- Add persistent history, operational logging, historical range selection,
  sleep-mode classification, lid-event overlays, or new power measurements to
  this mode.
- Infer physical power, temperature safety, or remaining runtime from integer
  battery percentages.

## Use Cases

- Run `burnbag graph-only` beside another task and see battery state updated
  every second without preventing the laptop from sleeping.
- Use `burnbag graph-only --graph-interval-seconds 2.5` for a slower fixed
  observation/display cadence.
- Use `burnbag graph-only --graph-interval-logarithmic` for rapid initial
  updates that become progressively less frequent as the session grows.
- Resize the terminal or suspend and resume normally without a power-state
  restoration operation from graph-only.

## Constraints And Assumptions

Verified against `008bd73`:

- `BatteryMonitor` provides read-only percentage discovery and sampling,
  including native capacity and energy/charge fallback, for up to two batteries.
- The existing chart renderer can render supplied observations at an explicit
  width. Existing static charts use 25 data rows and a 20-column minimum.
- `ForegroundRecorder` may start a fallback collector. Its D-Bus observer
  acquires bounded sleep/shutdown delay inhibitors to synchronize writes.
  That lifecycle cannot be reused unchanged for a strictly passive mode.
- The collector samples every five seconds. Repainting its cached snapshot
  cannot be represented as a fresh subsecond battery observation.
- The project supports Linux with distribution Python 3.9 or later. Battery
  reads and chart formatting do not themselves require PyGObject or GTK.

Design defaults selected for this proposal:

- Each scheduled refresh takes a fresh read-only battery sample. The existing
  collector, if running, continues independently and is neither reconfigured
  nor stopped. Equal percentage readings are legitimate observations; cached
  collector snapshots are not duplicated as new ones.
- History starts at this invocation and is held in memory only. This mode
  creates neither a SQLite database nor a JSONL session. Its readings are not
  automatically available to later historical queries.
- Runtime for the curve and plot uses suspend-inclusive `CLOCK_BOOTTIME`.
  Wall clock labels remain presentation-only.
- The increasing curve continues beyond 100 seconds. The previously suggested
  ten-second cap was an assistant suggestion, not an operator requirement.

## Proposed Approach

### Command-Line Contract

```text
burnbag graph-only [--graph-interval-fixed]
                   [--graph-interval-seconds SECONDS] [--no-color]
burnbag graph-only --graph-interval-logarithmic [--no-color]
```

`--graph-interval-fixed` and `--graph-interval-logarithmic` are mutually
exclusive. Omitting both selects fixed cadence. `--graph-interval-seconds`
accepts positive finite decimal seconds and defaults to `1` in fixed mode.
Reject zero, negative, nonfinite, or unrepresentable timer values. Explicit
`--graph-interval-seconds`, even `1`, conflicts with logarithmic mode; retain
whether the option was supplied instead of confusing its default with input.

All three interval options require `graph-only`. The mode cannot be combined
with service management, `--collector`, `--graph`, historical bounds, or
operational controls (`--suspend-after-minutes`, `--no-inhibit-auto-suspend`,
`--ignore-lid`, `--do-not-touch-backlight`, `--log-file`, `--prudent-writes`).
Reject `--no-plot`, since graphing is this mode's purpose. Invalid combinations
produce dependency-independent usage errors with exit status 2.

### Increasing Interval

For nonnegative elapsed runtime `t` in seconds, define the next interval in
seconds as:

```text
p = ln(10) / ln(9)
I(t) = 0.1 * (1 + t / 1.25) ** p
```

| Runtime t | Interval I(t) |
| --- | --- |
| 0 seconds | 0.1 seconds |
| 10 seconds | 1 second |
| 100 seconds | 10 seconds |
| 1,000 seconds | approximately 110.374 seconds |

The function is smooth and strictly increasing. At the first two nonzero
anchors its bases are 9 and 81, so the intervals are exactly 1 and 10 seconds
mathematically, subject to ordinary floating-point/timer precision.
`--graph-interval-logarithmic` is the requested CLI name; the documentation
must describe the actual shifted power curve rather than claim it is a pure
logarithm.

Take an initial sample and render immediately. At each iteration evaluate
the selected interval using the current runtime and schedule one next update
against a monotonic deadline. Fixed cadence should account for time spent
reading and drawing, without an accumulating extra work-time delay. After
missed deadlines, scheduling stalls, or suspend, take the next actual reading
and resume normal scheduling without a burst of fabricated catch-up samples.
No timer may wake the machine. Long intervals must remain promptly
interruptible; Ctrl-C must not wait for the next refresh deadline.

### Observation And Rendering

Use the read-only battery reader and pure rendering/statistics functions in
a separate graph-only controller. Do not construct `LidCloseManager`,
`ForegroundRecorder`, a collector, or the mandatory operational logger.
No D-Bus connection is needed. Reuse battery ordering, percentage provenance,
plain symbols, color policy, observed extrema, and missing-reading behavior.

Each live frame shows the entire observed session, current percentages, and
the active interval policy. Recompute graph geometry from the actual stdout
terminal size on every refresh. Resize-only redraws may occur sooner, but
must not create another battery observation or restart the interval curve.
Use up to 25 data rows in the live view, reducing height to fit available
space; leave existing static chart geometry unchanged. If a terminal is too
small for axes, show a bounded resize message and continue tracking until it
can display the graph again. When terminal size is unavailable, use the
existing 80-column fallback.

A capable interactive terminal replaces the live frame in place through one
terminal owner. Colorless output (`--no-color`, `NO_COLOR`), `TERM=dumb`, and
redirected output retain the existing escape-free contract by emitting
separated plain frames instead of cursor-control sequences. The adapter must
restore screen/cursor state on handled signals, exceptions, and shell job
control transitions. Avoid uncaptured diagnostic writes inside the live frame.

Keep actual observation times. A failed read remains a visible gap; a known
sleep interval or stopped process must not be drawn as continuously observed
battery history. Paired boottime/monotonic checks can identify sleep between
reads without D-Bus or journal queries; mark the intervening observation gap
without adding sleep-mode classification to this feature. The existing
quantization-aware battery summary remains available at handled exit; do not
derive raw adjacent-percentage rates from the faster sampling cadence.

### Side Effects And Failure Behavior

Treat graph-only as an observational command, explicitly outside the mandatory
operational-session logging contract. The existing collector warning envelope
must not falsely promise foreground recording for it: a valid graph-only
invocation bypasses collector probing/warnings and operates without a service.
Other invocations retain their established behavior. Document this exception
in the relevant specifications when implementation begins.

Keep an already-running collector entirely independent, including any delay
inhibitors it owns. Graph-only's guarantee concerns resources and actions of
this invocation; it cannot remove another process's inhibitors.

No installed batteries is a successful, explanatory exit. A battery read
failure is reported without inventing data; later refreshes may recover, but
the final result records the observation failure with nonzero status. Fatal
setup, clock, rendering, or output failure ends the loop with a diagnostic and
terminal cleanup. SIGINT, SIGTERM, and SIGHUP request prompt handled shutdown;
when output remains usable, leave a final static graph and battery summary.
Failure to render one must not prevent the other or terminal restoration.
No userspace cleanup or final display is promised for SIGKILL or power loss.

## Alternatives Considered

- **Repeat `--graph`:** queries durable history and can request collector
  flushes. It does not provide independent, fresh subsecond observations.
- **Reuse the operational/foreground lifecycle:** risks profile/backlight
  work, logging, fallback collection, and delay inhibitors excluded here.
- **Use only collector snapshots:** avoids duplicate reads but makes freshness
  depend on its five-second cadence and availability. Direct read-only battery
  sampling gives graph-only consistent semantics with or without the service.
- **Cap at ten seconds or use a capped spline:** adds a limit absent from the
  request. The uncapped smooth fit preserves all three requested anchors.
- **Extend the GTK viewer:** does not satisfy the requested terminal mode.

## Risks And Mitigations

- **Accidental host controls:** route graph-only before operational setup;
  prove prohibited collaborators are never entered in integration tests.
- **Misleading sample rate or drain statistics:** sample actual sysfs values,
  retain timestamps, and preserve the existing quantization-aware estimator.
- **Terminal corruption or wrapping after resize:** one renderer owns output,
  sizes every frame, and restores terminal state on every handled exit.
- **CPU and memory costs:** faster battery reads and repainting have real
  overhead. Avoid busy waiting and unnecessary redraw allocations; test long
  synthetic sessions. The initial design retains session readings in memory
  and does not promise unlimited-duration, constant-memory operation.
- **Slow later updates:** show the selected policy/current interval, keep
  interrupts responsive, and document that logarithmic mode has no cap.
- **Scope confusion:** mark this proposal approved but unimplemented; keep it
  queued behind installer repair rather than activating its implementation.

## Validation

- Curve tests establish all three anchors, smooth monotonic growth, and an
  interval greater than ten seconds after 100 seconds. Fake-clock scheduling
  covers fixed/fractional intervals, late frames, elapsed sleep and no catch-up
  burst, plus prompt interruption during a long wait.
- CLI tests cover default and explicit fixed mode, all option conflicts,
  explicitly supplied `1` with logarithmic mode, invalid values, and help/errors
  without GI or an operational session.
- Real sysfs-shaped fixtures cover one/two/no batteries, percentage fallback,
  repeated values, missing readings and recovery. Every displayed new sample
  must correspond to an actual read; display-only resize creates none.
- Integration tests exercise graph-only without a collector or GI and assert
  no inhibitor, host-state mutation, service control/probe/flush, SQLite write,
  or JSONL session. A preexisting collector is unaffected.
- PTY tests cover in-place redraw, shrinking/widening and short terminals,
  signal/job-control cleanup, final graph/summary, and failed output. Redirected,
  dumb-terminal and color-disabled output contain no terminal escapes.
- Regress existing operational modes, history queries, statistics and default
  25-row charts; run the supported Python matrix and project-owned checks.
  Synchronize generated README/man sources and staged entry-point delivery.
- An optional later operator check verifies visible resize and normal desktop
  suspend/resume. Automated tests must not suspend the host. Drafting this
  proposal is not implementation or hardware-validation evidence.

## Open Questions

No additional product approval is required for the feature scope. The operator
will supply the installer bug reports that take priority. Implementation timing
and phase allocation remain intentionally unscheduled; the assumptions above
are explicit design defaults and can be revised before execution if needed.

## Milestones

- **Proposal and queue — Codex:** publish the pre-approved design and backlog
  link. Exit with no application, installer, or runtime changes.
- **Installer work first — operator and implementation owner:** receive and
  address the upcoming installer reports before activating this feature.
- **Feature specification and execution — implementation owner:** when this
  feature is selected after installer work, allocate the next available roadmap
  phase and local slices using AGENTS.md. Add the durable contract, passive
  controller and refresh options, then complete the validation above.
- **Delivery — implementation owner:** synchronize user documentation and
  tracking, publish under the project's ACP workflow when the feature is
  delivered, and keep any physical acceptance distinct from automated evidence.

## Adoption And Rollout

This is an additive command and introduces no database or preference migration.
Existing invocations retain their behavior. Before implementation, the proposal
and backlog are the planning record; do not advertise the mode as available in
generated user help or manuals. On delivery, document its ephemeral in-memory
history, passive lifecycle, refresh policy and plain-output behavior. Rollback
removes the new command path/options without altering stored history or services.

## Decision Log

- 2026-09-02 — Operator requested graph-only and the fixed/logarithmic options,
  first asking whether a smooth curve could match the three interval anchors.
  Codex supplied the shifted power fit. No implementation followed.
- 2026-09-15 — Repository and branch checks found no graph-only implementation
  or queued record. Compatibility review identified reusable battery rendering
  and the existing foreground collector's delay-inhibitor boundary.
- 2026-09-15 — Operator agreed the feature remains useful and explicitly
  requested a pre-approved proposal, with implementation held while upcoming
  installer bugs are addressed. Status is Approved on that authority; this
  approval does not override the explicit instruction not to implement yet.
- 2026-09-15 — Recorded direct per-refresh sampling, ephemeral memory-only
  history, uncapped curve, and passive command dispatch as design defaults.
  No roadmap phase was allocated, preserving the next available number for
  whichever work is scheduled next.
