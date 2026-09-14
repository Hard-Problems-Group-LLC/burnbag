# AI Human Requests

Bounded operator checks for the Ubuntu/ARM delivery. Exact commands and expected
results are in [the testing guide](../docs/testing.md).

## Pending Requests

No additional queued requests.

## Active Requests

- `BB-MANUAL-01` — Revised-build graph, lid, backlight, and profile confirmation.
  - Created and activated: 2026-09-14. Owner: operator. Requestor: Codex.
  - Remaining scope: roadmap P2.4; P3.4 passed and closed on 2026-09-14.
  - Operator selected self-installation with `./install.sh --mode dev` after
    readiness. Read-only inspection confirms the executable managed user
    launcher selects this checkout. No agent installation into `/usr/local`
    is requested.
  - Check 1 passed: operator confirmed graph/summary and clean Ctrl-C return
    in a small panel. The real log records three valid energy-derived samples
    over approximately 25 seconds, no deviations, released inhibitors, and
    completed teardown with exit zero. The maximized-terminal check prompted
    `BB-BUG-2026-09-14-01`: always label both axis extrema, even equal values.
    That correction is verified and available on the next dev-launcher run.
  - Ordinary lid/backlight check passed on 2026-09-14: operator confirmed
    visible recovery, automatic exit, graph/summary, and corrected extrema.
    Real log evidence confirms one close/open pair, verified off/on, released
    inhibitor, and exit zero without deviations. Original and final profiles
    were both power-saver, so actual profile restoration still needs its test.
  - New diagnostic feature `BB-2026-09-14-02` is delivered: separate close/open
    counts and colored transition markers for `--ignore-lid` runs. Optional
    [check 1a](../docs/testing.md#1a-lid-event-counts-and-graph-markers) exercises
    two known cycles with the screen left on; expect close=2/open=2 and matching
    markers, or report extra detected transitions for switch investigation.
  - Next: [check 2](../docs/testing.md#2-physical-lid-backlight-and-profile),
    ordinary and repeated-ignore-lid cycles with backlight control and a real
    balanced-to-power-saver transition.
  - Acceptance: one graph and summary, valid derived battery readings, clean
    shell return, visible screen restoration, correct profile restoration,
    and expected lid termination/continuation. Report pass/fail and errors.
  - Baseline evidence: the operator's older installed run already confirmed
    lid events, delayed screen-off, verified screen restoration, and inhibitor
    release. It closed P1.4, but did not validate the revised battery reader,
    changed-and-restored profile, or physical suspend/resume.

- `BB-MANUAL-02` — Supervised ARM suspend/resume.
  - Created and activated: 2026-09-14. Owner: operator. Requestor: Codex.
  - Covers P2.4. Perform [check 3](../docs/testing.md#3-supervised-suspendresume)
    when desktop interruption is acceptable, after saving other work.
  - Acceptance: the one-minute continuous-lid-closure countdown requests sleep;
    after normal wake, burnbag exits with its report and the screen and profile
    recover. Report failures or unexpected wake behavior.
  - Hibernation is reported unsupported on this host; no hibernation test is
    requested. Automated tests establish request/failure handling, not physical
    suspend reliability.

## Completed Requests

The graph/summary portion of `BB-MANUAL-01` passed on 2026-09-14 and closes
P3.4. The request remains active for its remaining hardware observations.
