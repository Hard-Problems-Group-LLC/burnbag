# Ubuntu, ARM, and lifecycle reliability roadmap

Owner: burnbag maintainers. Authorized by the operator on 2026-09-14.

## Phase 1000 — Relative history durations

Authorized 2026-09-15. Phase and slice IDs now follow the spaced numbering
policy in AGENTS.md; published P1–P10 references remain stable. Manual validation
is now phase 9000 under the operator's subsequent renumbering instruction.
Current status: all four slices complete, verified 2026-09-15. Numbering
guidance was committed before feature implementation. All 378 native tests
pass; Python 3.9.21 and 3.14.7 each pass 359 compatibility tests with two
expected native-GI skips. Staged installed queries and manual copies pass.
Existing manual checks remain pending under phase 9000.

- **1000 — Numbering and contract:** publish the numbering rule and define
  unambiguous duration grammar, units, range bounds and option conflicts.
- **2000 — Duration parsing and range calculation:** support numeric and
  English quantities, case/space variants, seconds through millennia, and
  right-aligned colon time (M:SS or H:MM:SS); preserve one common end instant.
- **3000 — CLI and documentation:** add `--last DURATION` to historical
  graphs, synchronize help/README/man/specifications, and preserve warning
  envelopes and read-only history behavior. Verify installation of the generated
  manual in every mode and service scope.
- **4000 — Verification and publication:** test every requested example,
  unit families, invalid/overflowing values, CLI conflicts and real SQLite
  selection; publish evidence and ACP the completed phase.

Acceptance: every provided five-hour spelling selects the same interval;
`5:00` selects five minutes; a valid duration ends at invocation time. Errors
are actionable, and existing `--from`/`--to` behavior remains available.
The operator selected calendar subtraction for months and larger units:
preserve local date/time and adjust for month-end. Smaller units use elapsed
time. The [duration contract](docs/specifications/duration-ranges.md) specifies
compound values, daylight-saving transitions and representable bounds.

## Continuous monitoring extension — authorized 2026-09-15

The operator approved the batching policy and optional SQLite-backed systemd
collector, then instructed full implementation. The canonical contract is
[continuous history](docs/specifications/continuous-history.md).

Current delivery status (2026-09-15): P6–P10 implementation and automated
verification are complete and delivered by phase ACP. All 344 native tests pass;
Python 3.9.21 and 3.14.7 each pass 325 compatibility tests with two expected
native-GI skips. Isolated background/shared foreground collectors recorded real
ARM measurements; a complete CLI/SQLite/GLib test verified Ctrl-C reporting.
The operator confirmed development installation, active/enabled system service,
collector readiness and the first historical graph on 2026-09-15: seven valid
readings over 30 seconds. Warning/fallback checks and physical sleep remain in
BB-MANUAL-03, alongside earlier P2 and phase 9000 checks. The
[phase stack](project-management/state/phase-slice-stack.md) retains detailed
state and generates Ubersight, now awaiting BB-MANUAL-01/02/03 observations.

- **P6 — Durable telemetry:** slice 1000 specify approved behavior; slice 2000
  implement SQLite schema, safe paths and bounded batched writer; slice 3000
  implement sensor collection and merged history queries; slice 4000 verify
  real storage/failure paths.
- **P7 — Collector services:** slice 1000 enforce global ownership and
  readiness; slice 2000 collect events/sleep with bounded lifecycle flushes;
  slice 3000 coordinate foreground fallback and prudent-write requests; slice
  4000 test concurrent clients, failures and handoff without host mutations.
- **P8 — CLI and history graphs:** slice 1000 add service actions, scope
  inference and warning envelopes; slice 2000 connect existing run graphs to
  collector observations; slice 3000 add arbitrary-time merged history graphs;
  slice 4000 verify all CLI exit paths.
- **P9 — Installation and documentation:** slice 1000 install system/user
  units and supporting modules; slice 2000 add scoped history-preserving
  uninstallation; slice 3000 synchronize specifications, generated README/man
  and installer; slice 4000 verify staging, dev paths and failure recovery.
- **P10 — Integration and handoff:** slice 1000 run full
  native/compatibility/static checks; slice 2000 conduct read-only real
  sampling and isolated daemon smoke tests; slice 3000 publish bounded
  operator service/sleep checks and ACP all phase work.

Proceed automatically across independent slices; ACP each completed phase and
each phase deferred for manual completion, without another review gate. The
earlier P2 and phase 9000 physical checks remain pending rather than being replaced.

This is the canonical design and acceptance plan for the five requested phases.
Current phase/slice state and Ubersight regeneration instructions live in
[the delivery stack](project-management/state/phase-slice-stack.md). Primary
task lifecycle records remain in `project-management/`. This root roadmap is
an explicit operator-requested specialization of FieldManual's default location.

## Execution and publication

Complete automatable work first. Continue independent later phases while
earlier hardware checks await the operator, then close the earlier phases when
their evidence arrives. Record bounded manual checks in
`project-management/ai-human-requests.md`; never equate simulation with live
hardware validation. ACP means add the exact phase files, commit, and push to
the configured upstream, without another review gate. Do this at phase
completion and when handing a phase off for later manual completion. Preserve
unrelated changes and do not publish private workstation details.

## P1 — Ubuntu support

Original request: “This is the first Ubuntu system on which burnbag has been
tested. Investigate, test, and address any issues uncovered. Ask for manual
testing when needed, but address anything you can address on your own first.”

- **1000 Inventory:** inspect distribution Python, native bindings, available
  system services, and current automated baseline.
- **2000 Portability:** support Ubuntu/Debian prerequisite packages and package
  selection while retaining Fedora/RHEL behavior. Keep help independent of GI.
- **3000 Verification:** test package selection/failure paths with isolated
  commands, run real non-mutating prerequisite checks and staged installation.
- **4000 Hardware:** collect real desktop/backlight/lid confirmation after
  software fixes are available; publish a manual handoff if needed.

Acceptance: distro-appropriate actionable setup; native GI loads on this
Ubuntu system; tests and staged executable pass; manual limitations recorded.

## P2 — ARM platform support

Original request: “This is the first ARM platform running burnbag. Review
~/AI-ASSISTED-ADMIN if you want platform details, or go get them yourself
(you're authorized). Investigate, test, and address any issues uncovered.
As before, address what you can, then ask for manual testing.”

- **1000 Inventory:** inspect CPU architecture and actual kernel power-supply,
  backlight, logind, UPower, and profile capabilities without changing hardware.
- **2000 Compatibility:** repair demonstrated sysfs/API assumptions using
  documented, validated fallbacks, with explicit telemetry provenance.
- **3000 Verification:** run native ARM tests plus representative driver-shaped
  fixtures and read-only real battery discovery/sampling.
- **4000 Hardware:** verify visible backlight restoration, lid behavior, and
  available power profiles, and supervised suspend/resume with the operator;
  avoid claiming unsupported modes.

Acceptance: meaningful battery observations on this ARM host; no x86-only
assumptions; unavailable hardware capabilities are clear; automated and manual
evidence remain distinct. Battery statistics describe reported/derived SoC,
never inferred electrical power or battery health.

## P3 — Reliable shutdown graph and summary

Original request: with `--ignore-lid`, Ctrl-C ends the program but the graph is
missing. “The same material-- the graph and the summary information-- should
be displayed in all shutdown cases for which the program meaningfully start
operations.”

- **1000 Reproduce:** trace actual telemetry and subprocess signal behavior.
- **2000 Lifecycle:** define operational start, centralize handled finalization,
  and preserve final sample, graph, and summary across signals and errors.
- **3000 Regression:** exercise actual GLib/subprocess signal delivery with
  external hardware boundaries substituted, including `--ignore-lid`.
- **4000 Confirmation:** ask the operator to verify the original visible symptom
  using the verified checkout or development launcher; retain explicit
  `--no-plot` and unavailable-output semantics.

Acceptance: every handled operational exit attempts reporting after safe
restoration, with no duplicate summaries or bypassed log finalization. Help and
rejected commands do not create operational reports. SIGKILL/power loss cannot
execute userspace reporting; unavailable batteries and broken output are
reported honestly rather than fabricating data.

## P4 — Error and exception hardening

Original request: “After this, do a general pass to harden and improve error
and exception handling and reporting for the program in general, and its
installation scripts and supporting materials.”

- **1000 Audit:** inspect setup, timers, callbacks, mutations, teardown, terminal
  writes, runtime logs, installer arguments, and partial installation failures.
- **2000 Runtime:** isolate cleanup actions, bound external calls, handle
  callback/signal/report failures, and use actionable nonzero outcomes.
- **3000 Installer:** fail before mutation on invalid input, preserve unmanaged
  paths, contain staging, and diagnose/clean up partial operations.
- **4000 Verify:** add failure-injection regressions for demonstrated risks and
  run the full suite and shell/static checks.

Acceptance: failure in one observer or cleanup action cannot silently skip the
remaining recovery actions; diagnostics identify the failed boundary without
exposing secrets; installer failures do not falsely claim success.

## P5 — Documentation and installation consistency

Original request: “Improve and synchronize documentation, man pages, and the
installer.”

- **1000 Contracts:** align supported systems, telemetry sources, signal/exit
  behavior, capability limits, logging, and recovery guidance.
- **2000 Generated docs:** update `makedocs.py`, regenerate README/man page,
  and check help/man/source consistency and reproducibility.
- **3000 Delivery:** validate standard/staged/dev installer paths; install the
  verified application and manual for operator checks when needed. The operator
  selected self-installation with `./install.sh --mode dev` on 2026-09-14;
  delivery readiness and exact launcher instructions complete the agent slice.
- **4000 Closeout:** publish evidence and exact remaining manual steps, refresh
  tracking, and ACP this phase.

Acceptance: the delivered executable, CLI, README, manual, specifications, and
installer describe the same behavior; the operator has a bounded validation
procedure and all automated work is published.

## 9000 — Manual validation and final closure

Renamed from phase V on 2026-09-15 at the operator's direction. Its six
assigned slices now use local IDs 1000 through 6000 in the same order; scope,
acceptance evidence and open human requests retain their existing status.

Collect the requested physical observations, address any defects they expose,
rerun affected automated checks, close linked human requests and deferred
phases, and ACP the resulting closure. Until then the overall delivery remains
awaiting manual validation, even when every automated slice is complete.

Continuous-service acceptance is tracked separately within phase 9000:

- **4000 — Installed collector and initial history:** passed 2026-09-15. The
  operator installed dev mode, verified the system service active/enabled and
  collector ready, and displayed system history with seven valid observations.
- **5000 — Warning envelope and foreground fallback:** next operator check;
  stop the service, verify help warnings and a prudent foreground run, query
  merged history, then restart and verify readiness.
- **6000 — Continuous service sleep coverage:** pending supervised desktop
  suspend/wake with the background collector running and no foreground run.

These checks do not replace the earlier profile/backlight and physical ARM
sleep observations in BB-MANUAL-01/02.

### Operator follow-up during 9000

On 2026-09-14, after the ordinary lid/backlight and axis-extrema checks passed,
the operator requested `BB-2026-09-14-02`: for `--ignore-lid`, report separate
numbers of detected close/open transitions and show their times as magenta
(close) and yellow (open) vertical graph lines. Preserve event timing and
counts for switch troubleshooting, keep battery observations visible, and
provide distinct plain-output markers and explicit overlap behavior. This is
an authorized addition to phase 9000, slice 2000; it does not change the battery estimator or
remove the outstanding physical profile/suspend checks.

The operator then requested `BB-2026-09-14-03`: check the entire run for actual
suspend periods before assembling the exit report, and mark those regions as
full-height blocks of white capital `S` characters on a red background.
Phase 9000, slice 2000 now covers a read-only clock observer from application entry through the
post-recovery reporting snapshot, verified suspend-time accounting, approximate
interval placement with explicit uncertainty, full-run graph coverage, and
plain-output and no-plot behavior. Automated checks precede publication;
the existing supervised phase P2, slice 4000 suspend check also verifies the visible blocks.

The related `BB-2026-09-14-04` follow-up distinguishes verified hibernation
with full-height green `H` on magenta and reserves black `0` on dark gray for
future powered-off regions. Clock evidence continues to establish actual sleep;
a bounded read-only journal lookup may classify its mode from an unambiguous
successful systemd sleep operation. Missing, failed, or ambiguous mode evidence
retains `S` with an explicit unverified-mode qualification. Shared suspend and
hibernate columns preserve both encodings. The reserved powered-off style adds
no current detector or generated powered-off region. Synchronize contracts,
generated documentation, tests, and tracking before the authorized ACP.


## Phase 3000 — GTK 4 history viewer

Authorized 2026-09-15. The operator requested a GNOME helper application for
system and user telemetry, with graph and table views, synchronized navigation,
search/zoom/pan, native window controls, F11 graph fullscreen, and opt-in Unix
socket UI automation with keyboard/mouse input and screenshot capture. The
manual validation work formerly assigned phase 2000 was renumbered phase 9000
to reserve phase 3000 for this effort; the six local slice IDs are unchanged.
The accepted interface and data contract is
[GTK 4 history viewer](docs/specifications/history-viewer.md).

- **1000 — Data and automation contract:** specify read-only access to both
  SQLite stores, dynamic measurement columns, keyset paging, socket protocol,
  screenshot boundaries, input routes and security limits.
- **2000 — Native application shell:** build GTK 4 startup, GNOME decorations,
  minimize/restore/maximize/close behavior, explicit F11 graph fullscreen, and
  the two-tab notebook foundation.
- **3000 — Graph and table experience:** render full available history by
  default with a bounded, extrema-preserving overview and a global measurement
  catalog; page table rows on demand; implement bidirectional navigation.
- **4000 — Automation and controller:** add opt-in Unix socket requests, a
  matching controller command, keyboard/mouse operations, state inspection and
  client-area PNG capture through the same action handlers as human input.
- **5000 — Delivery integration:** include launchers, dependency checks,
  documentation and installation/uninstallation behavior.
- **6000 — Verification and handoff:** automated data/UI/protocol checks,
  GNOME session tests for real window-manager controls and F11, performance and
  large-history checks, then ACP completed work and request the pending GNOME checks in
  BB-MANUAL-04 (project-management/ai-human-requests.md).

Slices 1000–5000 are complete. The graph summarizes all available history,
measurement fields are discovered across all records, and the table remains
continuously paged with a total-row status. User feedback caught the initial
first-page-only graph/catalog; the correction is verified by 408 tests and a
live X11 check of 5,553 system rows. Installer checks, generated documentation,
and viewer manual validation pass. Phase 3000, slice 6000 is active for visible
GNOME title-bar checks tracked by BB-MANUAL-04. ACP this corrected work while
those manual checks remain deferred.

## Phase 3100 — Viewer data completeness and time ranges

Authorized 2026-09-15. Investigate missing system/user history in the actual
installed viewer, correct the reader/rendering/launch paths, and add initial
time selection with `--last` and an optional `--only` boundary.

- **1000 — Reproduce and trace sources:** compare installed and checkout
  commands, service database locations, raw row counts and displayed history;
  distinguish absent stores from unreadable stores and rendering omissions.
- **2000 — Repair complete history delivery:** fix development command
  selection, source diagnostics, paging and graph continuity/detail. Verify
  both stores with real SQLite fixtures and the actual system history.
- **3000 — Initial and locked ranges:** reuse the terminal duration/calendar
  implementation for `--last` (and ISO `--from`/`--to`). Capture now once;
  without `--only`, navigation can leave the initial viewport. With `--only`,
  queries/search and all navigation stay inside its fixed outer bounds; zoom
  within those bounds remains available. Reject `--only` without a range.
- **4000 — Verify and publish:** regression and actual GTK automation tests,
  staged command/manual installation, documentation and Ubersight updates,
  followed by ACP. Preserve existing manual requests in phases 3000/9000.

Acceptance: the real installed command can select the same development code
as burnbag; both readable databases contribute their nonconflicting data;
empty/failed sources are identified by path; graph rendering preserves real
gaps and isolated points at broad and narrow ranges. Range selection and
locking work identically through controls and automation. Database contents
remain unchanged by viewing.

Initial delivery 2026-09-15: slices 1000–4000 are delivered. The bare viewer was an
older installed build because dev mode only published the terminal launcher.
All three commands now follow the selected checkout. Rendering preserves flat
tails and isolated samples, zoom queries detail, and source diagnostics expose
actual paths and counts. The system store is intact; the operator's ordinary
user SQLite store is absent (the older JSON-lines running log is separate).
Both sources merge correctly in real SQLite/GTK fixtures.

Verification: 426 native tests including actual GTK/socket/frame tests pass;
Python 3.9.21 and 3.14.6 each pass 407 tests with five explicit GI/GUI skips.
The final staged viewer's five-hour range matches direct SQLite queries exactly:
3,572 records and 3,568 battery samples. Installer/launcher/manual, shellcheck,
generated-document and whitespace checks pass. See
[completion evidence](project-management/completed-tasks.md) and
[the resolved defect](project-management/bugs/closed/BB-BUG-2026-09-15-01-viewer-history-visibility.md).
The operator retains installation with `./install.sh --mode dev`;
phase 3000's visible GNOME controls and phase 9000's manual checks remain open.

- **5000 — Authoritative installation mode:** completed follow-up on 2026-09-15.
  The clarified contract makes dev mode select checkout code for all three user
  commands and either service scope; standard mode selects installed copies
  and retires managed dev launchers. No selection prompt, legacy flag or
  environment override may contradict the mode. The system dev service uses
  a private read-only checkout mount under its normal account. Unmanaged-file
  protections, PATH verification and read-only checks remain enforced.
  Verification: 80 affected tests pass on Python 3.13.7, 3.9.21 and 3.14.6,
  including code edits, both mode transitions, source-independent installed
  execution, all command entry points, both service scopes and unit validation.
  Help, manuals and tracking agree. [FieldManual ECR-003](ECRs/FieldManual/open/burnbag-ECR-2026-003-authoritative-installation-mode.md)
  records the strong reusable guidance; it is drafted, not yet submitted.
  Actual system installation/activation remains the operator's action.

## Phase 4000 — Persistent viewer field selection

Authorized 2026-09-15. Replace the measurement drop-list with **Fields...**.
The modal dialog has Graph and Table pages, each using two columns of named
checkboxes. Choices are independent; Date and Time remain the first table
columns. OK saves and applies both selections together; Cancel, Escape and
window close discard the draft. No graph/table changes occur while editing.

- **1000 — Dialog and durable selection:** atomic per-user preferences at
  `$XDG_CONFIG_HOME/burnbag/viewer.json` (default `~/.config/burnbag/viewer.json`),
  staged edits, multi-field graph panels and table visibility. Preserve names
  absent from the current snapshot; report corrupt/unwritable preferences.
- **2000 — Automation and verification:** expose dialog state, checkbox edits,
  OK/Cancel and captures through the existing socket; verify persistence across
  real launches, cancellation, empty selections and failures using isolated data.
- **3000 — Documentation and publication:** synchronize manuals, specifications,
  roadmap and live tracking; ACP after automated acceptance. Existing physical
  GNOME checks remain deferred independently.

Acceptance: saved selections survive restarts; all discovered fields are
available (numeric measurements for graphs); plots retain separate scales,
extrema labels and shared time navigation; changing fields preserves viewport,
search and table selection. Failed saves leave the dialog open without applying.

Completed 2026-09-15: all three slices delivered. Verification passes 116 native
affected tests (including eight real GTK/socket/frame cases) and 108 non-GTK
tests on each compatibility interpreter, Python 3.9.21 and 3.14.6. Real launches
prove save/cancel/close, restart persistence, failure recovery, empty selections,
multiple plots and preserved navigation. Generated documentation, viewer manual,
staged installation and tracking checks pass; captured dialog/graph frames were
visually inspected. No host installation or operator preferences were changed.
Earlier GNOME and hardware acceptance stays with phases 3000/9000.

## Phase 5000 — Standard installer recovery

Authorized 2026-09-15 following the reported `sudo ./install.sh` failure:
`Standard command directory is not on PATH: /usr/local/bin`.

- **1000 — Reproduce:** reproduce the restricted-PATH validation failure
  without host installation; inspect privileged versus operator identity.
- **2000 — Repair:** separate privileged installed-file verification from
  user-shell command lookup and resolve the sudo caller's home for managed
  launcher retirement. Preserve unmanaged files and ordinary PATH guards.
- **3000 — Verify:** exercise private installations, mode transitions,
  restricted PATH, explicit homes, and failure paths; run regression checks.
- **4000 — Document and hand off:** synchronize installation contracts,
  generated help/manuals, tracking, and AGENTS.md Ubersight guidance. Keep
  deployment and existing physical checks distinct from automated evidence.

Acceptance: standard installation does not depend on sudo's PATH containing
the destination bin directory, does not add user directories to root's PATH,
and verifies installed commands without claiming to know the caller's shell
lookup. Only managed development launchers are retired. User-service and dev
installation retain their non-root requirements. Graph-only remains queued.

Completed 2026-09-15: all four slices verified and handed off. Native discovery
runs 453 tests with eight opt-in GUI skips; all other cases pass. All 88 affected
tests pass on Python 3.9.21 and 3.14.6; syntax, shellcheck, generated docs,
manuals and read-only preflight pass. Operator acceptance subsequently passed
at 2026-09-15T22:57:52-07:00: `sudo time ./install.sh` succeeded, and after
`hash -r` all three commands resolved under `/usr/local/bin`. BB-MANUAL-05 is
closed; earlier GNOME and hardware checks remain separate. See
[the resolved installer bug](project-management/bugs/closed/BB-BUG-2026-09-15-02-sudo-installation.md).

## Phase 6000 — Shared-rectangle viewer traces and unit axes

Authorized 2026-09-15. Replace tiled plots with one exact plotting rectangle
for every selected trace. Live viewer updates are backlog-only, not part of
this phase. Preserve snapshot reads, field preferences and existing navigation.

- **1000 — Contract and unit taxonomy:** specify explicit physical units and
  meaningful synthetic units for otherwise ambiguous numeric fields. Percentages
  from both batteries share one unit; unrelated unknown fields do not. Allocate
  axes in deterministic selected-field order. Record live updates in the backlog.
- **2000 — Shared ranges and ticks:** group selected visible observations by
  unit; each group's range contains every displayed value, including extrema
  preserved by reduction. Support flat, empty, negative and tiny/large ranges.
  Aim for ten divisions, reducing count to keep tick labels at least 1.5 label
  heights apart; format distinct, readable values without clipping extrema.
- **3000 — One rectangle and axis strips:** lay out the first unit at outer
  left, second at outer right, third inward on the left, and continue alternating.
  All traces use exactly the same X/Y pixel rectangle with unit-specific Y
  transforms. Center unit labels along strips, rotated 90 degrees counter-clockwise.
  Provide an explicit resize/fewer-fields message when labels cannot fit.
- **4000 — Color key and interaction:** draw distinct trace colors and a
  lower-center in-plot key with a 50%-alpha background and matching colored
  labels. Keep the key within the rectangle. Use the shared geometry for hit
  testing, nearest-trace observation selection, dragging, focus and fullscreen.
- **5000 — Verification:** test grouping, collective autoranges, strip order,
  tick spacing and legend geometry; capture real Cairo/GTK frames, inspect them,
  and exercise multi-unit navigation, resize/fullscreen and saved selections.
  Regress source merging, gaps, range locks and staged installation.
- **6000 — Documentation and delivery:** synchronize the viewer specification,
  generated README/manual, automation contract, tests, task records and Ubersight;
  ACP verified work while leaving existing physical checks independently open.

Acceptance: BAT0/BAT1 percentages align on one shared scale; watts, watt-hours
and temperatures each autorange independently on the same plot rectangle.
Every selected field is keyed by color, axes alternate outside-in, rotated
unit titles and intermediate ticks remain legible, and interactions use the
same transforms as drawing. No live-refresh implementation or service change.

Current status: all six slices complete. Native discovery ran 464 tests with
nine opt-in GUI skips; all nine real GTK frame/interaction cases pass with
isolated PyGObject 3.50 bindings. Python 3.9/3.14 compatibility suites and
static/documentation checks pass. The host's pre-existing older-binding capture
limitation is recorded separately, without changing its packages. Existing
GNOME/hardware checks remain open. See [completed evidence](project-management/completed-tasks.md)
and [the viewer specification](docs/specifications/history-viewer.md).
