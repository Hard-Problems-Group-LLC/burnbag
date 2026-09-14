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
    P4 hardening is delivered in `eab9d1d`; final native suite passes 138 tests.
    Exact revised-build instructions are in [the testing guide](../docs/testing.md).

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
  - Reactivation: `BB-MANUAL-01` physical backlight/lid/profile observations
    and `BB-MANUAL-02` supervised suspend/resume. P4 now verifies profiles,
    rejects unavailable performance/hibernation capabilities, and preserves
    recovery on uncertain results. No physical sleep success is claimed.


Use this file for intentionally paused work moved from the backlog or
in-progress lists without changing the original task wording.

## Include

- stable ID
- the original request as a Markdown block quote or linked immutable record
- reason for deferral
- deferral timestamp
- the authority that chose to defer it
- the condition or decision that would reactivate it
