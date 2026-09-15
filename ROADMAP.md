# Ubuntu, ARM, and lifecycle reliability roadmap

Owner: burnbag maintainers. Authorized by the operator on 2026-09-14.

## Phase 1000 — Relative history durations

Authorized 2026-09-15. Phase and slice IDs now follow the spaced numbering
policy in AGENTS.md; published P1–P10 references remain stable. Manual validation
is now phase 2000 under the operator's subsequent renumbering instruction.
Current status: all four slices complete, verified 2026-09-15. Numbering
guidance was committed before feature implementation. All 378 native tests
pass; Python 3.9.21 and 3.14.7 each pass 359 compatibility tests with two
expected native-GI skips. Staged installed queries and manual copies pass.
Existing manual checks remain pending under phase 2000.

- **1000.1000 — Numbering and contract:** publish the numbering rule and define
  unambiguous duration grammar, units, range bounds and option conflicts.
- **1000.2000 — Duration parsing and range calculation:** support numeric and
  English quantities, case/space variants, seconds through millennia, and
  right-aligned colon time (M:SS or H:MM:SS); preserve one common end instant.
- **1000.3000 — CLI and documentation:** add `--last DURATION` to historical
  graphs, synchronize help/README/man/specifications, and preserve warning
  envelopes and read-only history behavior. Verify installation of the generated
  manual in every mode and service scope.
- **1000.4000 — Verification and publication:** test every requested example,
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
BB-MANUAL-03, alongside earlier P2 and phase 2000 checks. The
[phase stack](project-management/state/phase-slice-stack.md) retains detailed
state and generates Ubersight, now awaiting BB-MANUAL-01/02/03 observations.

- **P6 — Durable telemetry:** P6.1 specify approved behavior; P6.2 implement
  SQLite schema, safe paths and bounded batched writer; P6.3 implement sensor
  collection and merged history queries; P6.4 verify real storage/failure paths.
- **P7 — Collector services:** P7.1 enforce global ownership and readiness;
  P7.2 collect events/sleep with bounded lifecycle flushes; P7.3 coordinate
  foreground fallback and prudent-write requests; P7.4 test concurrent clients,
  failures and handoff without host mutations.
- **P8 — CLI and history graphs:** P8.1 add service actions, scope inference and
  warning envelopes; P8.2 connect existing run graphs to collector observations;
  P8.3 add arbitrary-time merged history graphs; P8.4 verify all CLI exit paths.
- **P9 — Installation and documentation:** P9.1 install system/user units and
  supporting modules; P9.2 add scoped history-preserving uninstallation;
  P9.3 synchronize specifications, generated README/man and installer;
  P9.4 verify staging, dev paths and failure recovery.
- **P10 — Integration and handoff:** P10.1 run full native/compatibility/static
  checks; P10.2 conduct read-only real sampling and isolated daemon smoke tests;
  P10.3 publish bounded operator service/sleep checks and ACP all phase work.

Proceed automatically across independent slices; ACP each completed phase and
each phase deferred for manual completion, without another review gate. The
earlier P2 and phase 2000 physical checks remain pending rather than being replaced.

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

- **P1.1 Inventory:** inspect distribution Python, native bindings, available
  system services, and current automated baseline.
- **P1.2 Portability:** support Ubuntu/Debian prerequisite packages and package
  selection while retaining Fedora/RHEL behavior. Keep help independent of GI.
- **P1.3 Verification:** test package selection/failure paths with isolated
  commands, run real non-mutating prerequisite checks and staged installation.
- **P1.4 Hardware:** collect real desktop/backlight/lid confirmation after
  software fixes are available; publish a manual handoff if needed.

Acceptance: distro-appropriate actionable setup; native GI loads on this
Ubuntu system; tests and staged executable pass; manual limitations recorded.

## P2 — ARM platform support

Original request: “This is the first ARM platform running burnbag. Review
~/AI-ASSISTED-ADMIN if you want platform details, or go get them yourself
(you're authorized). Investigate, test, and address any issues uncovered.
As before, address what you can, then ask for manual testing.”

- **P2.1 Inventory:** inspect CPU architecture and actual kernel power-supply,
  backlight, logind, UPower, and profile capabilities without changing hardware.
- **P2.2 Compatibility:** repair demonstrated sysfs/API assumptions using
  documented, validated fallbacks, with explicit telemetry provenance.
- **P2.3 Verification:** run native ARM tests plus representative driver-shaped
  fixtures and read-only real battery discovery/sampling.
- **P2.4 Hardware:** verify visible backlight restoration, lid behavior, and
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

- **P3.1 Reproduce:** trace actual telemetry and subprocess signal behavior.
- **P3.2 Lifecycle:** define operational start, centralize handled finalization,
  and preserve final sample, graph, and summary across signals and errors.
- **P3.3 Regression:** exercise actual GLib/subprocess signal delivery with
  external hardware boundaries substituted, including `--ignore-lid`.
- **P3.4 Confirmation:** ask the operator to verify the original visible symptom
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

- **P4.1 Audit:** inspect setup, timers, callbacks, mutations, teardown, terminal
  writes, runtime logs, installer arguments, and partial installation failures.
- **P4.2 Runtime:** isolate cleanup actions, bound external calls, handle
  callback/signal/report failures, and use actionable nonzero outcomes.
- **P4.3 Installer:** fail before mutation on invalid input, preserve unmanaged
  paths, contain staging, and diagnose/clean up partial operations.
- **P4.4 Verify:** add failure-injection regressions for demonstrated risks and
  run the full suite and shell/static checks.

Acceptance: failure in one observer or cleanup action cannot silently skip the
remaining recovery actions; diagnostics identify the failed boundary without
exposing secrets; installer failures do not falsely claim success.

## P5 — Documentation and installation consistency

Original request: “Improve and synchronize documentation, man pages, and the
installer.”

- **P5.1 Contracts:** align supported systems, telemetry sources, signal/exit
  behavior, capability limits, logging, and recovery guidance.
- **P5.2 Generated docs:** update `makedocs.py`, regenerate README/man page,
  and check help/man/source consistency and reproducibility.
- **P5.3 Delivery:** validate standard/staged/dev installer paths; install the
  verified application and manual for operator checks when needed. The operator
  selected self-installation with `./install.sh --mode dev` on 2026-09-14;
  delivery readiness and exact launcher instructions complete the agent slice.
- **P5.4 Closeout:** publish evidence and exact remaining manual steps, refresh
  tracking, and ACP this phase.

Acceptance: the delivered executable, CLI, README, manual, specifications, and
installer describe the same behavior; the operator has a bounded validation
procedure and all automated work is published.

## 2000 — Manual validation and final closure

Renamed from phase V on 2026-09-15 at the operator's direction. Its six
assigned slices now use 2000.1000 through 2000.6000 in the same order; scope,
acceptance evidence and open human requests retain their existing status.

Collect the requested physical observations, address any defects they expose,
rerun affected automated checks, close linked human requests and deferred
phases, and ACP the resulting closure. Until then the overall delivery remains
awaiting manual validation, even when every automated slice is complete.

Continuous-service acceptance is tracked separately within phase 2000:

- **2000.4000 — Installed collector and initial history:** passed 2026-09-15. The
  operator installed dev mode, verified the system service active/enabled and
  collector ready, and displayed system history with seven valid observations.
- **2000.5000 — Warning envelope and foreground fallback:** next operator check;
  stop the service, verify help warnings and a prudent foreground run, query
  merged history, then restart and verify readiness.
- **2000.6000 — Continuous service sleep coverage:** pending supervised desktop
  suspend/wake with the background collector running and no foreground run.

These checks do not replace the earlier profile/backlight and physical ARM
sleep observations in BB-MANUAL-01/02.

### Operator follow-up during 2000

On 2026-09-14, after the ordinary lid/backlight and axis-extrema checks passed,
the operator requested `BB-2026-09-14-02`: for `--ignore-lid`, report separate
numbers of detected close/open transitions and show their times as magenta
(close) and yellow (open) vertical graph lines. Preserve event timing and
counts for switch troubleshooting, keep battery observations visible, and
provide distinct plain-output markers and explicit overlap behavior. This is
an authorized addition to 2000.2000; it does not change the battery estimator or
remove the outstanding physical profile/suspend checks.

The operator then requested `BB-2026-09-14-03`: check the entire run for actual
suspend periods before assembling the exit report, and mark those regions as
full-height blocks of white capital `S` characters on a red background.
2000.2000 now covers a read-only clock observer from application entry through the
post-recovery reporting snapshot, verified suspend-time accounting, approximate
interval placement with explicit uncertainty, full-run graph coverage, and
plain-output and no-plot behavior. Automated checks precede publication;
the existing supervised P2.4 suspend check also verifies the visible blocks.

The related `BB-2026-09-14-04` follow-up distinguishes verified hibernation
with full-height green `H` on magenta and reserves black `0` on dark gray for
future powered-off regions. Clock evidence continues to establish actual sleep;
a bounded read-only journal lookup may classify its mode from an unambiguous
successful systemd sleep operation. Missing, failed, or ambiguous mode evidence
retains `S` with an explicit unverified-mode qualification. Shared suspend and
hibernate columns preserve both encodings. The reserved powered-off style adds
no current detector or generated powered-off region. Synchronize contracts,
generated documentation, tests, and tracking before the authorized ACP.
