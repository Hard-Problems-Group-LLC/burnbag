# Deferred Tasks

- `BB-2026-09-14-P3` — Shutdown reporting. Started and deferred 2026-09-14;
  owner: Codex; authority: operator's manual-validation deferral instruction.
  Original request: [roadmap P3](../ROADMAP.md#p3--reliable-shutdown-graph-and-summary).
  - Outcome: signals during setup and all operational modes now request a safe
    unwind; handlers preserve resource bookkeeping and repeated signals cannot
    interrupt recovery. Reports remain available with `--ignore-lid`.
  - Evidence: 86 native tests passed, including nine real subprocess/GLib
    regressions covering SIGINT, SIGTERM, early setup, one-shot setup, repeated
    signals, loop-entry race, setup failure, lid cycle, and `--no-plot`.
  - Reactivation: visible Ctrl-C report confirmation in `BB-MANUAL-01`.
    General output/cleanup failure isolation proceeds in P4.

- `BB-2026-09-14-P2` — ARM support. Started and deferred 2026-09-14;
  owner: Codex; authority: operator's manual-validation deferral instruction.
  Original request and acceptance: [roadmap P2](../ROADMAP.md#p2--arm-platform-support).
  - Root cause: this ARM kernel battery supplies energy but no capacity
    percentage. Rejection produced zero samples, explaining the reported
    missing Ctrl-C graph. Fixed native/energy/charge source selection,
    validated whole-percent conversion, fixed-source gaps, and log provenance.
  - Evidence: 77 tests passed natively on Ubuntu/aarch64; read-only real
    battery sampling returned a valid 70% observation from energy_now/energy_full
    without errors. Tests cover driver-shaped fixtures and invalid sources.
  - Reactivation: `BB-MANUAL-01` physical backlight/lid/profile observations.
    Suspend and unsupported performance-profile handling continue under P4.

- `BB-2026-09-14-P1` — Ubuntu support. Started and deferred 2026-09-14;
  owner: Codex; authority: operator requested automatic progress with manual
  validation deferred when needed. Original request and acceptance:
  [roadmap P1](../ROADMAP.md#p1--ubuntu-support).
  - Automated outcome: distribution-selected apt/dnf prerequisite installation,
    dependency diagnostics, and corrected UPower initial-lid Properties query.
    Native Python 3.13.7 on Ubuntu 25.10/aarch64 passes 72 tests; ShellCheck,
    read-only installation check, staged executable/help/manual validation,
    and diff whitespace checks pass.
  - Reactivation: physical desktop/lid/backlight validation in `BB-MANUAL-01`.
    Continue P2-P5 first. ACP is authorized at this manual handoff.

Use this file for intentionally paused work moved from the backlog or
in-progress lists without changing the original task wording.

## Include

- stable ID
- the original request as a Markdown block quote or linked immutable record
- reason for deferral
- deferral timestamp
- the authority that chose to defer it
- the condition or decision that would reactivate it
