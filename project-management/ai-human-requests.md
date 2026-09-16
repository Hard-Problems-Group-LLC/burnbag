# AI Human Requests

Bounded operator checks for the Ubuntu/ARM delivery. Exact commands and expected
results are in [the testing guide](../docs/testing.md).

## Pending Requests

- `BB-MANUAL-04` — GTK 4 viewer GNOME interaction and automation check.
  - Created 2026-09-15. Owner: operator. Requestor: Codex.
  - Scope: roadmap phase 3000, slice 6000. Automated work covers the desktop
    shell, both views, keyset paging, search, navigation, data merging, socket
    permissions/protocol and PNG capture. Only a real GNOME session can verify
    the native minimize/restore/maximize/close controls and full-screen layout.
  - Follow [viewer manual verification](../docs/testing.md#gtk-history-viewer-manual-verification)
    after the revised build is available through the development launcher.
  - Acceptance: report native titlebar controls, F11 graph-only fullscreen,
    table paging/search and both cross-navigation gestures. For automation,
    report capture usability and socket cleanup. Include any visible errors.


## Active Requests

- `BB-MANUAL-03` — Continuous collector installation and physical sleep history.
  - Created and activated: 2026-09-15. Owner: operator. Requestor: Codex.
  - Scope: roadmap P10 operator handoff and manual acceptance in phase 9000,
    slices 4000–6000.
  - Installation/readiness/initial history passed on 2026-09-15 (slice 4000).
    Operator ran `./install.sh --mode dev --dev-command local`, refreshed
    command lookup, and reported system service loaded/active/enabled, user
    service absent, and collector ready in system scope. The initial graph
    contained seven valid system observations over 30 seconds at 80%, both
    axis extrema, summary and no absent-service warning. The point at the
    right edge is expected for new data in the default 24-hour interval;
    flat/short data correctly leaves variability and trend unavailable.
    The earlier `lokcal` typo was rejected and the corrected command succeeded.
  - Follow [continuous service acceptance](../docs/testing.md#continuous-service-acceptance):
    next check help and stopped-service warnings (slice 5000),
    prudent foreground fallback and merged history, then restart the service.
  - When desktop interruption is acceptable, save other work and perform a
    supervised desktop suspend/wake with only the service recording; query its
    interval and confirm clock-evidenced sleep coverage. Unavailable journal
    mode evidence remains explicitly unverified. No hibernation is requested.
  - Acceptance: report service status, graph observations, warning placement,
    fallback result, and whether the sleep region appears. Installation and
    hardware checks remain separate from isolated automated tests. Existing
    BB-MANUAL-01/02 remain open for their earlier hardware observations.

- `BB-MANUAL-01` — Revised-build graph, lid, backlight, and profile confirmation.
  - Created and activated: 2026-09-14. Owner: operator. Requestor: Codex.
  - Remaining scope: roadmap phase P2, slice 4000. Phase P3, slice 4000 passed
    and closed on 2026-09-14.
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
    release. It closed phase P1, slice 4000, but did not validate the revised
    battery reader, changed-and-restored profile, or physical suspend/resume.

- `BB-MANUAL-02` — Supervised ARM suspend/resume.
  - Created and activated: 2026-09-14. Owner: operator. Requestor: Codex.
  - Covers phase P2, slice 4000. Perform
    [check 3](../docs/testing.md#3-supervised-suspendresume)
    when desktop interruption is acceptable, after saving other work.
  - Acceptance: the one-minute continuous-lid-closure countdown requests sleep;
    after normal wake, burnbag exits with its report and the screen and profile
    recover. Report failures or unexpected wake behavior.
  - Hibernation is reported unsupported on this host; no hibernation test is
    requested. Automated tests establish request/failure handling, not physical
    suspend reliability.
  - `BB-2026-09-14-03` delivers actual-suspend diagnostics and graph blocks
    under phase 9000, slice 2000; 188 native tests and compatibility checks pass.
    The continued-run variant in check 3 verifies the new display: leave
    burnbag active, use desktop Suspend, wake, and then press Ctrl-C. Expect measured suspended
    time and approximate full-height white `S` on red regions; plain output
    uses `S`. The countdown request can
    finish before physical sleep begins, so it cannot by itself prove this
    display. The development launcher uses the delivered feature on its next
    invocation. No live suspend has been performed by the agent; physical sleep
    and visible-block confirmation remain pending.
  - Related `BB-2026-09-14-04` delivers hibernate identification and green `H`
    on magenta regions; 225 native tests and compatibility checks pass.
    Successful matching journal evidence identifies the
    sleep kind; unavailable or ambiguous mode evidence preserves clock-confirmed
    `S` with an explicit unverified-mode report. This does not add a live
    hibernation request on the unsupported host. Black `0` on dark gray is
    reserved for future powered-off regions, with no current detector or
    operator check.

## Completed Requests

- `BB-MANUAL-05` — Repaired standard sudo installation confirmed.
  - Created and activated: 2026-09-15. Completed: 2026-09-15T22:57:52-07:00.
    Owner and evidence source: operator. Requestor: Codex.
  - Scope: phase 5000, slice 4000 deployment handoff. The operator ran
    `sudo time ./install.sh`; prerequisites, system-service installation and
    all three installed executable checks succeeded without the PATH error.
    Installation finished in 15.27 seconds and reported removal of the two
    existing managed burnbag development launchers (user and checkout).
  - After `hash -r`, the operator's normal-shell lookup returned
    `/usr/local/bin/burnbag`, `/usr/local/bin/burnbag-viewer`, and
    `/usr/local/bin/burnbag-viewerctl`. This satisfies installation and command
    selection acceptance and closes the request. Service runtime health,
    visible GNOME behavior and physical checks are not inferred from this
    output; their existing requests remain open.

The graph/summary portion of `BB-MANUAL-01` passed on 2026-09-14 and closes
phase P3, slice 4000. The request remains active for its remaining hardware
observations.

The installation/readiness/initial-history portion of `BB-MANUAL-03` passed
on 2026-09-15 and closes phase 9000, slice 4000. Warning/fallback and sleep
checks remain active.
