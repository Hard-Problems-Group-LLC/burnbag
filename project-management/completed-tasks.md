# Completed Tasks

- `BB-2026-09-15-5000` — Standard installer recovery under sudo.
  Started and completed 2026-09-15; owner: Codex; direct operator request.
  - All four phase 5000 slices are complete. Reproduced the missing
    `/usr/local/bin` PATH failure; the privileged preflight and post-install
    checks incorrectly assumed root's PATH described the operator's shell.
  - Root verifies installed executable files independently of PATH and reports
    the user-shell lookup check honestly. Non-root PATH guards remain. Sudo
    caller UID/name are validated before selecting the account home; explicit
    `--user-home` overrides it. Only managed dev launchers are retired, after
    verifying all three installed commands; unrelated root/user files remain.
  - Eight added regression tests cover full isolated publication and installed
    execution after moving the checkout, restricted/competing root PATH,
    identity and explicit-home handling, unmanaged preservation, check-only,
    incomplete publication, and root dev/user-service rejection. Real file
    deployment uses the service helper's staging mode, not host services.
  - Native Python 3.12.13 discovery: 453 tests run, eight expected opt-in GUI
    skips, all others pass. All 88 affected tests pass on Python 3.9.21 and
    3.14.6. Initial sandbox socket/ownership failures disappear outside the
    sandbox. Bash syntax, shellcheck, generated documents, both manual pages,
    whitespace, native prerequisites and ordinary read-only preflight pass.
  - AGENTS.md now explicitly requires synchronized Ubersight guidance/status,
    thousands-spaced phases and per-phase slices restarting at 1000. Roadmap,
    live status, installation contracts, README and manual are synchronized.
  - The agent did not perform a privileged host installation. The operator
    subsequently confirmed successful `sudo time ./install.sh` and all three
    normal-shell command paths under `/usr/local/bin`, after `hash -r`.
    Live acceptance passed at 2026-09-15T22:57:52-07:00, closing
    [BB-MANUAL-05](ai-human-requests.md). See
    [the closed bug](bugs/closed/BB-BUG-2026-09-15-02-sudo-installation.md).
    Existing GNOME/hardware checks remain open. Graph-only is approved and
    queued, with no implementation changes.

- `BB-2026-09-15-4000` — Persistent viewer field selection.
  Started and completed 2026-09-15; owner: Codex; direct operator request.
  - All three phase 4000 slices are complete. Fields... replaces the drop-list
    with a modal Graph/Table notebook, two checkbox columns per page, full-name
    tooltips and scrolling. Choices are independent; Date/Time stay visible.
    Multiple plots retain independent scales, axis extrema and shared navigation.
    The data reader loads selected series in one pass through the viewport.
  - OK atomically saves private XDG preferences and applies both selections;
    Cancel, Escape and window close discard drafts. Failed saves leave the
    dialog open and both views unchanged. Empty selections, corrupt preferences,
    unavailable saved fields and newly discovered fields have explicit behavior.
    Changes retain viewport/locks, search, rows and selection.
  - Existing Unix automation now supports dialog opening, tabs, checkbox edits,
    OK/Cancel, state and active-dialog captures through the actual widgets.
    Background automation is blocked while the dialog is modal. The existing
    single-series command remains available as a transient selection.
  - Validation: 116 affected tests pass on native Python 3.13.7, including eight
    actual GTK/socket/frame cases on a private Xvfb display and staged installer
    checks. All 108 non-GTK cases pass on Python 3.9.21 and 3.14.6. Tests use
    ResourceWarning as error and private SQLite/XDG fixtures. GUI cases cover
    both sources, cancellation and close, write failures, empty/multiple choices,
    process restarts, actual plotted pixels, range locks and navigation. The
    final warning/dispatch refinements pass all eight GTK cases again.
    Man rendering, generated-doc consistency and whitespace checks pass.
  - Inspected captured Graph/Table dialog frames and the multiple-plot frame.
    README, viewer manual, specification, ROADMAP and Ubersight are synchronized.
    No host installation or user preferences were changed. The existing
    GNOME decoration and hardware checks remain deferred under phases 3000/9000.

- `BB-2026-09-15-DEV-DEFAULT` — Authoritative installation mode for commands and services.
  Started and completed 2026-09-15; owner: Codex; direct operator clarification.
  - Phase 3100, slice 5000 is complete. `--mode dev` selects checkout code for
    all three bare commands and either service scope without a second prompt.
    Standard mode is the default, retires managed dev launchers and selects
    complete installed copies. Conflicting legacy selections are rejected;
    the obsolete environment policy cannot override mode. Checks and staging
    remain non-mutating, and unmanaged conflicts fail before publication.
  - A system dev unit runs as burnbag using a private read-only directory bind
    of the checkout, retaining home isolation and following atomic file edits.
    User dev units execute the checkout directly. Standard units and modules
    use installed copies. Active-service restart and deliberate stopped/disabled
    preferences retain the existing lifecycle policy.
  - Verification: all 80 affected installer/service/prerequisite/tracking tests
    pass on Python 3.13.7, 3.9.21 and 3.14.6 with ResourceWarning as error.
    A real installer/helper transition fixture changes checkout code, switches
    to standard, moves the checkout aside and executes all three installed
    commands plus service-module imports, then switches back to dev. Only
    external identity/service-manager boundaries are substituted. Both scopes'
    rendered units follow mode; systemd accepts the actual system-dev mount
    unit. Special-character paths, conflicting legacy settings, PATH shadowing,
    read-only checks, manual delivery and unrelated-file preservation pass.
  - Bash syntax, shellcheck, generated-document consistency, both man pages,
    read-only dev/standard checks with explicit operator identity, and whitespace
    pass. Live namespace execution was not available to the unprivileged test
    process; no host installation or service activation was performed. The
    operator retains `./install.sh --mode dev` and existing manual acceptance.
  - Wrote [burnbag-ECR-2026-003](../ECRs/FieldManual/open/burnbag-ECR-2026-003-authoritative-installation-mode.md)
    with normative mode semantics and a verification matrix. It supersedes
    ECR-001's optional activation policy only; no target acknowledgement or
    transport is claimed. FieldManual's submodule is unchanged. README, man,
    specifications, ROADMAP and live Ubersight are synchronized for ACP.

- `BB-2026-09-15-3100` — Viewer history visibility and time ranges.
  Started and completed 2026-09-15; owner: Codex; direct operator instruction.
  - All four phase 3100 slices are complete. The PATH viewer matched the old
    `4cdf4ba` build; development installation published only the terminal user
    launcher. The system SQLite store was readable with more than 6,000 records.
    The operator's normal user SQLite store is absent and its user service is
    not installed; the older JSON-lines narrative is not telemetry history.
    No data loss was established. See [resolved defect](bugs/closed/BB-BUG-2026-09-15-01-viewer-history-visibility.md).
  - Dev install now manages viewer/controller launchers together with burnbag,
    verifies command resolution and preserves unmanaged files. Manifests cover
    removal of all three. GTK/Cairo prerequisites and installed manuals agree.
  - Rendering retains first/last/extrema and raw continuity, visible singleton
    points, and viewport-specific detail. Graph clicks reach rows beyond the
    first page. Local-time search survives GTK filtering, series selection is
    preserved, source failures remain visible, and snapshots bound concurrent
    collector appends. Capture uses in-memory PNGs without writing near the
    installed executable. Both history stores remain read-only.
  - `--last` reuses all terminal duration/calendar semantics; ISO `--from` and
    `--to` are supported. With no flags the viewer opens all available history.
    Without `--only`, the supplied interval is the initial view. With `--only`,
    graph/table/search queries and all navigation stay inside its inclusive
    fixed limits while allowing zoom within them. `--only` alone fails before
    GTK initialization. Native and automated controls share range handling.
  - Validation: 426 tests pass on native Ubuntu/aarch64 Python 3.13.7 including
    actual GTK frames, two-source fixtures, cross-page navigation, search,
    series selection, drag/pan/zoom/reset and F11. Python 3.9.21 and 3.14.6
    each pass 407 tests with five expected GI/GUI skips and ResourceWarning
    treated as an error. One search failure on the shared desktop was not
    reproduced in 15 repetitions on a private Xvfb display; full-suite GUI
    verification now runs on that isolated display to exclude operator input.
  - The final staged executable reads the real system history and matches an
    independent SQLite query exactly for its five-hour snapshot: 3,572 records
    and 3,568 numeric battery observations, with a verified 1100x720 graph PNG.
    The real operator user path is explicitly selected for this check and is
    reported missing. Both sources contribute in separate real SQLite fixtures.
    Installer/launcher and manual tests, Bash syntax, shellcheck, prerequisite
    and installer read-only checks, generated docs, groff and whitespace pass.
  - ROADMAP/specifications/Ubersight are synchronized. Host installation and
    services were not changed; the operator retains deployment using
    `./install.sh --mode dev --dev-command local`. Existing GNOME controls
    (phase 3000) and hardware/fallback requests (phase 9000) remain deferred.
    Phase ACP proceeds under the standing authorization without another review.

- `BB-2026-09-15-LOCAL-SLICES` — Use local slice numbers within each phase.
  Completed 2026-09-15; owner: Codex; direct operator clarification.
  - Slice IDs and displayed names now use local numbers `1000`, `2000`,
    `3000`, and so on, without embedding their phase. Each phase owns its
    slice namespace; prose supplies the phase separately when needed.
    This also converts legacy numbered slices to local 1000-step numbers.
  - Phase 1000 retains slices 1000–4000. Phase 2000 retains slices 1000–6000,
    with slice 5000 awaiting operator warning/fallback results. The naming
    correction changes no work scope, acceptance evidence, or manual state.
    Historical task, request and bug IDs remain unchanged.
  - Updated the producer to identify slices by owning phase and local ID,
    allowing repeated IDs across phases and phase/slice ID equality while
    rejecting duplicates within one phase. All 17 focused producer tests pass.
    All 49 slice ownership/state pairs survive the migration. Installed writer
    and reader validation and 40/48/80-column renders pass; all six current
    slice titles fit the operator screenshot's 48-column pane. The private
    live status is republished with local IDs and current wait notes.

- `BB-2026-09-15-2000-NUMBERING` — Renumber manual validation phase.
  Completed 2026-09-15; owner: Codex; directly authorized by the operator.
  - Commit `19d40a1` renamed former phase `V` to `2000` and initially published
    qualified slice labels. Its mappings were `V.1` → `2000.1000`,
    `V.2` → `2000.2000`, `V.3` → `2000.3000`, `V.4` → `2000.4000`,
    `V.5` → `2000.5000`, and `V.6` → `2000.6000`. These qualified labels are
    historical evidence only; the later local-slice correction above
    supersedes their display and reference format.
  - Roadmap and project-management references were updated. Historical
    task, request and bug IDs remain unchanged; acceptance evidence and open
    manual checks retain their original scope and status.
  - Republished live Ubersight state and verified all six states are preserved,
    with the warning/fallback slice current. Installed writer/reader validation,
    40/50/80-column renders, roadmap links, historical identifier preservation
    and whitespace checks pass. The live file retains its private, ignored status.

- `BB-2026-09-15-TRACKING` — Review Ubersight expectations and refresh live state.
  Completed 2026-09-15; owner: Codex; direct operator request.
  - Reconciled FieldManual guidance, the installed Ubersight 0.1.0 writer and
    reader, and project completion/manual records. Moved final validation 2000
    after delivered phases so phase 1000 remains in the visible phase window.
    Marked deferred platform observations blocked and led notes with the
    warning/fallback operator wait. All three existing human requests remain open.
  - Updated regeneration/visibility/staleness guidance and roadmap indexes;
    republished the ignored live status with private directory/file modes.
    The installed consumer reads this checkout's default status path.
  - Validation: producer dry run, installed writer/reader normalization,
    fresh timezone-aware timestamp, expected manual-phase ownership, completed
    phase 1000, blocked delivery, private modes and ignore boundary pass.
    Status-only rendering at 40x20, 50x24 and 80x30 shows recent completion and the operator
    wait. No dashboard environment refresh, runtime-job rewrite or program
    behavior change was needed; whitespace checks pass.

- `BB-2026-09-15-1000` — Relative graph durations and spaced phase numbering.
  Started and completed 2026-09-15; owner: Codex; direct operator authorization.
  - All four phase 1000 slices are complete. AGENTS.md numbering guidance and
    the phase plan were published first in `3044393`, initially using qualified
    1000-step slice IDs. The local-slice correction above supersedes that
    naming convention while preserving the delivered scope and evidence.
  - `--graph --last DURATION` accepts every requested five-hour spelling,
    five-minute `5:00`, decimal/English quantities and compounds from seconds
    through millennia. One invocation instant anchors the end. Months and
    larger units use the operator-selected calendar subtraction, preserve
    local time and clamp month-end; smaller units subtract elapsed time.
    Invalid, ambiguous, conflicting or unrepresentable ranges fail explicitly.
  - README, manual, help and specifications are synchronized. All four
    installation mode/scope combinations copy the generated manual. Dev user
    service installation now publishes a user-owned manual in the user's
    normal manual tree, with shared-owner and modified-file preservation on
    removal. Installed support modules include the duration parser.
  - Validation: 378 native tests pass on Ubuntu/aarch64 Python 3.13.7.
    Python 3.9.21 (SQLite 3.47.1) and 3.14.7 (SQLite 3.53.1) each pass 359
    tests with two expected native-GI skips and ResourceWarning treated as an
    error. Direct staged install/query/uninstall smoke checks also pass on
    both compatibility interpreters. Official Astral runtime SHA256 hashes
    were verified; the temporary runtimes were removed afterward.
  - Real SQLite CLI tests check exact range endpoints and selection without
    modifying source bytes. Native staged executable queries for five hours,
    five minutes and two millennia resolve the installed parser; staged
    removal deletes that module and manual. Regressions cover calendar
    month-end/leap years, DST gaps/ambiguities, ancient timestamp precision,
    overflow, malformed input and warning envelopes. All 49 installer tests,
    shellcheck/Bash syntax, read-only prerequisite/install checks, generated
    documentation, warning-free man rendering, ten guide shell blocks and
    whitespace checks pass.
  - ROADMAP and Ubersight are current; phase ACP completed in `754deab` on main.
    No host installation or service change was performed. Existing physical
    and fallback requests remain open under 2000; the operator retains deployment
    with `./install.sh --mode dev --dev-command local`.

- `BB-2026-09-15-V4` — Installed collector and initial history acceptance.
  Completed 2026-09-15; observations: operator; verification: Codex.
  - The corrected development installation succeeded, the managed CLI selected
    the checkout, and the system service reported active/enabled with collector
    ready. The user service was absent. The initial system history graph and
    summary contained seven valid observations over 30 seconds at 80%.
    Repeated extrema labels and unavailable short/flat-run statistics behaved
    as specified. New data occupied the right edge of the default 24-hour view.
  - Read-only corroboration: all four installed runtime files match the
    checkout; recording health reports no error or dropped records. Nineteen
    recent durable samples have median cadence 5.043 seconds, with no sensor
    errors or observer-coverage warnings. No service control or host mutation
    was performed during corroboration.
  - Validation for these record changes: Ubersight producer and whitespace
    checks pass. BB-MANUAL-03 remains open for phase 2000: slice 5000 verifies
    warning/fallback/merged-history behavior, and slice 6000 verifies physical
    sleep observations. Earlier platform requests remain open.

- `BB-2026-09-15-01` — Continuous history and optional systemd services.
  Started and completed 2026-09-15; owner: Codex; authorized by the operator's
  instruction to fully implement. Roadmap P6–P10 is implemented and ACP'd.
  - Delivered five-second collection, batched SQLite history, prudent writes,
    singleton system/user services, shared foreground fallback, merged arbitrary
    history graphs, warning envelopes, management, installation and removal.
    Durable behavior is in the continuous-history and installation contracts.
  - Final acceptance: 344 native tests pass on Ubuntu/aarch64 Python 3.13.7.
    Python 3.9.21 (SQLite 3.47.1) and 3.14.7 (SQLite 3.53.1) each pass 325
    compatibility tests with two expected native-GI skips and resource warnings
    treated as errors. Installed subprocess launchers intentionally use the
    distribution interpreter; shared modules/helpers also run directly under
    each compatibility interpreter.
  - Native read-only background and shared foreground smoke runs record real
    five-second sensor observations and durable prudent barriers, with orderly
    cleanup. An actual main/SQLite/GLib/SIGINT test verifies 25 graph rows,
    summary, final durable records, no periodic JSONL duplication, restored
    signal handlers and closed inhibitor descriptors. Host power endpoints in
    this test are simulated; real smoke collection performs no power action.
  - Staged install/help/history/uninstall, 46 installer tests, shellcheck,
    shell syntax, read-only prerequisite/install checks, generated-document
    consistency, warning-free man rendering and ten manual-guide shell blocks
    pass. Owned temporary runtimes and native-smoke fixtures were removed.
  - Delivery: ROADMAP, specifications, README/man and Ubersight are current.
    The operator retains actual installation with
    `./install.sh --mode dev --dev-command local`. Live service installation,
    activation and physical sleep are not claimed; BB-MANUAL-03 and earlier
    BB-MANUAL-01/02 remain under 2000 for observations and any subsequent fixes.

- `BB-2026-09-15-P10` — Integration verification and operator handoff.
  Completed 2026-09-15; owner: Codex; operator-authorized roadmap P10.
  - Full native/compatibility/static and isolated native/staged artifact
    validation passed as recorded above. The new end-to-end recorder test
    replaces only external hardware endpoints, retaining the real CLI, event
    loop, writer and signal path.
  - Automatable work is complete. Remaining manual scope is explicitly deferred
    to 2000 and BB-MANUAL-01/02/03, with exact commands in docs/testing.md; this
    phase is ACP'd without another review gate as authorized.

- `BB-2026-09-15-P9` — Service installation, scoped removal and documentation.
  Completed 2026-09-15; owner: Codex; operator-authorized roadmap P9.
  - Default system installation creates the non-login service account, managed
    units/support modules and narrow delay-inhibition policy; optional user
    installation preserves login/lingering boundaries. Dev CLI follows the
    checkout while default system daemon uses a root-owned copy.
  - New installs activate recording; updates preserve intentional stopped or
    disabled state. Custom system prefixes publish a tracked unit under /etc.
    Uninstall preserves history/configuration by default, guards explicit purge
    against active foreground writers, and preserves shared or modified artifacts.
  - Validation: 46 installer tests pass on native Python 3.13 and Python 3.14,
    including both user-mode removal orders, custom-prefix registration,
    shared ownership, private directory modes, unsafe destinations and purge
    races. Staged executable help/history/imports and scoped removal pass.
  - README/man sources, specifications, install/remove help and manual guide are
    synchronized. Shellcheck, Bash syntax, prerequisite/install read-only checks,
    generated-document verification and warning-free manual rendering pass.
    No host installation was performed; BB-MANUAL-03 provides the operator steps.

- `BB-2026-09-15-P7-CRITICAL` — Immediate critical-battery durability.
  Completed 2026-09-15 during final acceptance; owner: Codex.
  - Kernel `capacity_level=Critical` makes each affected sample urgent and
    commits preceding buffered observations. No inferred percentage threshold
    or power action is introduced.
  - All 32 service tests pass, including a real SQLite boundary test confirming
    critical data commits without an explicit flush or normal batch deadline,
    and a low-percentage contrast that retains normal batching.

- `BB-2026-09-15-P8` — CLI management, warning envelopes and historical graphs.
  Completed 2026-09-15; owner: Codex; operator-authorized roadmap P8.
  - Added all scoped/inferred service actions, prudent writes, and arbitrary-time
    merged history graphs. Every CLI path freshly probes recording and warns
    at both ends when absent/unhealthy, including help and usage errors.
  - Operational runs consume shared snapshots without repeated hardware polls;
    diagnostics drain durably on the main thread, final samples precede reports,
    and failed pre-sleep flushes prevent burnbag's own sleep request.
  - Historical views preserve real gaps, extrema, lid/sleep markers and event-only
    intervals. Malformed or unreadable sources warn while usable data survives;
    reduced-resolution graphs retain actual coverage metadata.
  - Validation: 15 CLI/history tests, seven recorder integration tests, 19
    native GLib lifecycle cases, 27 battery and 13 failure-handling tests pass.
    Isolated installed executable imports support modules and runs help/history
    without creating state; native shared foreground collection has one owner,
    real five-second samples, prudent flush and clean teardown.

- `BB-2026-09-15-P7` — Optional collector services and coordinated fallback.
  Completed 2026-09-15; owner: Codex; operator-authorized roadmap P7.
  - Atomic machine-wide ownership, bounded peer-verified discovery, service
    readiness, system/user management and prudent-write leases are implemented.
    Shared foreground recording takes over when background recording is absent;
    one observer owns physical events even with several foreground clients.
  - Native D-Bus observations and paired clocks record lid/profile/charger and
    evidenced sleep. Bounded preparation flushes release delay inhibition;
    background handoff pauses duplicate foreground observation.
  - Validation: 30 real socket/storage/concurrency service tests pass. Storage
    follow-up reaches 35 tests: bounded query pages, coverage metadata through
    reduction, malformed coverage isolation, unreadable files and limit-one
    regression. Native isolated Ubuntu ARM collector records real samples,
    prudent barriers and orderly SIGTERM without installing a host service.
  - Scope: service implementation is complete; installed systemd activation and
    physical suspend remain operator validation in BB-MANUAL-03.

- `BB-2026-09-14-04` — Hibernate diagnostics and reserved powered-off styling.
  Started and completed 2026-09-14. Owner: Codex; requestor: operator;
  scope: ROADMAP phase 2000, slice 2000.
  - Clock-confirmed hibernate regions use green capital `H` on magenta;
    suspend remains white `S` on red. Both fill all 25 data rows, preserve axes
    and the lid header, and alternate glyphs/colors when they share a screen
    column. Plain output retains `S`/`H`. Black digit `0` on dark gray is reserved
    for future powered-off regions; no current detector or generated `0` block
    was added.
  - An optional read-only systemd journal query classifies existing clock
    regions using one unambiguous successful operation matched by boot,
    process, unit, invocation when available, and monotonic observation window.
    The actual suboperation determines the kind. Failed, missing, malformed,
    or ambiguous evidence retains clock-confirmed `S` with mode unverified;
    compound labels alone cannot establish hibernation. Query time, bytes, and
    accepted records are bounded at three seconds, 2 MiB, and 4,096 records.
    Failure cleanup kills and reaps the owned query process.
  - A final paired-clock read includes the query duration. Additional sleep
    remains mode unverified without repeating the lookup. Logs preserve mode,
    source, monotonic brackets, bounded classification status, and region
    counts; optional journal failure does not erase valid clock coverage.
    Summary and records remain available with `--no-plot` or no battery data.
  - Validation: 225 tests passed natively on Ubuntu/aarch64 Python 3.13.7,
    including 19 actual GLib subprocess cases. Python 3.9.21 and 3.14.6 each
    passed 206 compatibility cases with one native-GLib module skip. New
    coverage includes 25 classification/reader cases with actual subprocess
    limits and reaping, nine hibernate chart cases, mixed-mode and no-plot
    GLib exits, and a final-coverage regression for sleep during the query.
    A read-only query of this host's 132 historical records classified a
    matching completed operation as suspend; no live sleep or host mutation
    was used. Generated-document consistency, warning-free man rendering,
    manual-guide shell syntax, and whitespace checks pass; FieldManual is clean.
  - Delivery: documentation, manual, roadmap, and Ubersight are synchronized
    for the operator-authorized ACP. Existing P2 profile-transition and
    supervised suspend checks remain in [BB-MANUAL-01/02](ai-human-requests.md).
    This host does not advertise hibernation, so no live hibernate check is
    requested. The development launcher picks up the change on its next run.

- `BB-2026-09-14-03` — Actual suspend diagnostics and graph regions. Started
  and completed 2026-09-14. Owner: Codex; requestor: operator;
  scope: ROADMAP phase 2000, slice 2000.
  - A read-only background observer compares required Linux `CLOCK_BOOTTIME`
    and `CLOCK_MONOTONIC` independently of GLib, with a one-second cadence and
    a final post-recovery snapshot. Coverage includes setup and teardown.
    Paired-read uncertainty and a one-millisecond threshold reject jitter;
    cumulative accounting retains smaller changes. Clock/worker failure is
    reported as incomplete observation rather than verified absence of sleep.
  - Suspended duration is measured; interval boundaries are estimated within
    their observation brackets. Numeric uncertainty is logged, and graph and
    summary identify approximate timing. Several rapid sleeps can merge into
    one region; region count is not a physical suspend-cycle count.
  - Full-run X coverage retains blank unsampled battery edges. Suspend regions
    fill all 25 rows with white capital `S` on red, taking precedence over
    battery/lid cells while retaining axis labels and the lid header. Plain
    output uses `S`. Every mode receives detection, logging, and summary,
    independently of `--ignore-lid` or `--no-plot`; no battery data means no chart.
    Separate interval records keep the final session summary bounded.
  - Validation: 188 native tests passed on Ubuntu/aarch64 Python 3.13.7,
    including 17 actual GLib subprocess cases. Python 3.9.21 and 3.14.6 each
    passed 171 compatibility cases with one native-GLib module skip. The 24
    focused detector/chart cases cover clock noise and failure, cumulative
    changes, approximate geometry, overlaps, colors, and whole-run coverage.
    Three new GLib integrations verify multiple sleeps, final reconciliation,
    ordinary/ignore-lid behavior, no-plot, reporting order, and cleanup.
    Ten thousand real paired-clock observations plus worker/finalization
    produced no false intervals or errors. Generated-document consistency,
    man rendering, help, manual-guide shell syntax, and whitespace checks pass.
    No live suspend or host state mutation was needed for automated validation.
  - Manual handoff: [BB-MANUAL-02](ai-human-requests.md) now includes the
    continued-run supervised suspend check in [the testing guide](../docs/testing.md#3-supervised-suspendresume).
    Physical sleep/resume and visible `S` blocks remain awaiting the operator,
    together with the earlier P2 profile-transition check. The development
    launcher selects these changes on the next invocation.

- `BB-2026-09-14-02` — Lid-event diagnostics for `--ignore-lid`. Started and
  completed 2026-09-14. Owner: Codex; requestor: operator;
  scope: ROADMAP phase 2000, slice 2000.
  - Shutdown reports separate detected close/open counts, including zero.
    Initial snapshots and duplicate unchanged property notifications are
    excluded. Observations survive a subsequent log failure; current telemetry
    availability is reported accurately after read failure or recovery.
  - Transition records include local observation time, battery-aligned
    `CLOCK_BOOTTIME` elapsed time, and cumulative counts. The final state adds
    counts without embedding an unbounded history array.
  - Graph overlays use magenta close and yellow open lines, with C/O/B headers,
    distinct plain markers, and alternating colors for shared columns. Battery
    traces, fixed 25-row height, gaps, and all extrema labels remain intact.
    Event times can extend the X domain without adding battery observations.
    Counts remain when `--no-plot` is used or battery data is unavailable.
  - Validation: 161 tests passed natively on Ubuntu/aarch64 Python 3.13.7.
    Python 3.9.21 and 3.14.6 each passed 147 compatibility cases with one native
    GLib module skip. Coverage includes duplicate/initial-state handling,
    telemetry recovery, log failure, marker geometry at 20/40/190 columns,
    color/plain output, clock changes, overlapping events, and actual GLib
    callbacks through Ctrl-C and durable finalization, with and without plots.
    Help, generated-document consistency, man rendering, guide shell syntax,
    and whitespace checks pass. No live host mutation was needed.
  - Manual follow-up: [event-count/marker check](../docs/testing.md#1a-lid-event-counts-and-graph-markers)
    is ready through the development launcher. Existing P2 profile-change and
    suspend/resume checks remain separate. The operator's ordinary lid/backlight
    and extrema confirmations are recorded in `BB-MANUAL-01`.

- `BB-BUG-2026-09-14-01` — Always label chart extrema, including equal values.
  Started and completed 2026-09-14 under roadmap phase 2000, slice 2000;
  owner: Codex;
  requestor: operator. Both axis boundaries now retain labels before interior
  callouts, with aligned ticks and no fabricated data. 141 native tests,
  Python 3.9/3.14 compatibility, real-session replay, and generated-doc/man
  checks passed. See the [bug record](bugs/closed/BB-BUG-2026-09-14-01-chart-extrema-labels.md).

- `BB-2026-09-14-P3` — Shutdown graph and summary. Started, deferred, and
  completed 2026-09-14. Owner: Codex; manual validation: operator.
  Original request/acceptance: [roadmap P3](../ROADMAP.md#p3--reliable-shutdown-graph-and-summary).
  - Delivered in `4eebb8d`, with P4 hardening in `eab9d1d` and synchronized
    documentation in `e405325`. Signals and handled errors preserve teardown,
    graph/statistics attempts, and the final running-log record.
  - Operator confirmed that the first revised-build Ctrl-C test worked in a
    small terminal panel, with the lid open and backlight control disabled.
    Read-only inspection of its real log corroborated approximately 25 seconds,
    three valid energy-derived battery observations, initial lid-state success,
    SIGINT, inhibitor release, no deviations, exit zero, completed teardown,
    and no recorded terminal-output failure.
  - The 138-test native suite already covers handled signal/error cases through
    actual GLib, plus rendering and cleanup boundaries. Visible graph/summary
    confirmation now closes phase P3, slice 4000. The operator is additionally
    checking a maximized terminal; any layout finding will be handled in final
    validation.
  - P2's revised-build physical lid/backlight/profile and supervised sleep
    observations remain active in `BB-MANUAL-01`/`BB-MANUAL-02`. This lid-open
    test does not establish those behaviors.

- `BB-2026-09-14-P5` — Documentation and installation consistency. Started and
  completed 2026-09-14. Owner: Codex; requestor: operator.
  Original request/acceptance: [roadmap P5](../ROADMAP.md#p5--documentation-and-installation-consistency).
  - Synchronized CLI/source comments, README, man page, and behavior contracts
    for Ubuntu/ARM prerequisites, derived percentages, handled exits, verified
    profiles, capability failures, logging order, and recovery limits. Corrected
    `normal` and countdown wording. Added a specification index and exact
    automated/manual verification guide.
  - Hardened `makedocs.py`: outputs are anchored to its checkout, each file is
    replaced atomically, unsafe targets fail clearly, and `--check` detects
    stale outputs without writing. Generator anchoring, stale detection,
    symlink refusal, and cleanup were exercised in a disposable fixture.
  - Validation: final native suite 138/138 passed; generated docs match source;
    man rendering has no warnings; ShellCheck, Bash syntax, standard/dev
    readiness, and whitespace checks pass. A real isolated staged install
    delivered byte-identical executable/manual with modes 0755/0644 and passed
    installed help and man rendering. P4's Python 3.9/3.14 compatibility results
    remain recorded below.
  - Delivery: operator selected self-installation with `./install.sh --mode dev`;
    readiness and launcher selection instructions are supplied. Live installation
    and physical observations remain in `BB-MANUAL-01`/`BB-MANUAL-02`, owned by
    final validation and deferred P2/P3. All automated scope is complete.
  - Repository boundaries: FieldManual remains pinned and clean; unrelated
    operator `.gitignore` edits are preserved outside the phase commits.

- `BB-2026-09-14-P4` — Runtime and installer hardening. Started and completed
  2026-09-14. Owner: Codex; requestor: operator.
  Original request/acceptance: [roadmap P4](../ROADMAP.md#p4--error-and-exception-hardening).
  - Runtime: capability checks before lid-dependent or sleep operations;
    advertised power profiles and actual snapshots; readback-verified changes
    and restoration; uncertain Set replies retain recovery obligations.
    `normal` retains only a verified balanced result. Explicit method deadlines
    are 10 seconds, or 30 seconds for interactive sleep requests.
  - Recovery: each cleanup step and owned inhibitor close is attempted despite
    earlier failures. GLib callback exceptions end the loop. SIGINT/SIGTERM/
    SIGHUP and recorded failures prevent subsequent mutations even when they
    arrive during a capability query. Reporting isolates narrative, chart, and
    statistics, falls back to stderr, and finalizes the running log afterward.
    Earlier failures cannot be overwritten by a successful lid cycle.
  - Installer: validates options/targets before prerequisites, contains staged
    paths, makes staging check-only for packages, preserves declined/EOF/default
    launcher selection, detects isolated assistant homes, and diagnoses partial
    installation while cleaning unpublished launcher files.
  - Validation: 138 tests passed on native Ubuntu/aarch64 Python 3.13.7 with
    PyGObject/GLib. Python 3.9.21 and 3.14.6 each ran 126 compatibility cases
    successfully with one native-GLib module skip (those interpreters lack GI).
    Seventeen installer regressions, shell syntax, ShellCheck, prerequisite and
    installer readiness checks, and whitespace checks passed. Read-only live
    capability checks confirmed lid telemetry, power-saver/balanced profiles,
    and clean rejection of unsupported hibernation.
  - Remaining platform observations are already owned by P2/P3 and the human
    requests. No live suspend, hibernate, profile, or backlight mutation was
    used as automated validation. ACP without review is operator-authorized.

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

- `BB-2026-09-15-P6` — Durable telemetry foundation, completed 2026-09-15.
  - Approved contract and roadmap P6–P10 recorded; SQLite DELETE/EXTRA transactions, separate bounded writer, per-update prudent mode, five-second sensor snapshots and bounded merged queries implemented.
  - 30 real storage tests pass, including crash-after-commit, concurrent readers/writers, failure/queue paths, segmented per-metric collisions and interval-wide reduction.
  - Read-only ARM sampler: one battery, five supplies, 43 thermal zones; approximately 2.4 KB snapshot in 43 ms. No power actions or installation.
