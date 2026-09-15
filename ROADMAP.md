# Ubuntu, ARM, and lifecycle reliability roadmap

Owner: burnbag maintainers. Authorized by the operator on 2026-09-14.

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

## V — Manual validation and final closure

Collect the requested physical observations, address any defects they expose,
rerun affected automated checks, close linked human requests and deferred
phases, and ACP the resulting closure. Until then the overall delivery remains
awaiting manual validation, even when every automated slice is complete.

### Operator follow-up during V

On 2026-09-14, after the ordinary lid/backlight and axis-extrema checks passed,
the operator requested `BB-2026-09-14-02`: for `--ignore-lid`, report separate
numbers of detected close/open transitions and show their times as magenta
(close) and yellow (open) vertical graph lines. Preserve event timing and
counts for switch troubleshooting, keep battery observations visible, and
provide distinct plain-output markers and explicit overlap behavior. This is
an authorized addition to V.2; it does not change the battery estimator or
remove the outstanding physical profile/suspend checks.

The operator then requested `BB-2026-09-14-03`: check the entire run for actual
suspend periods before assembling the exit report, and mark those regions as
full-height blocks of white capital `S` characters on a red background.
V.2 now covers a read-only clock observer from application entry through the
post-recovery reporting snapshot, verified suspend-time accounting, approximate
interval placement with explicit uncertainty, full-run graph coverage, and
plain-output and no-plot behavior. Automated checks precede publication;
the existing supervised P2.4 suspend check also verifies the visible blocks.
