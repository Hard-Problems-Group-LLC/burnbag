# Tasks In Progress

- `BB-2026-09-14-V` — Manual validation and final closure; started 2026-09-14.
  Owner: Codex; observations: operator.
  - Scope: [roadmap 9000](../ROADMAP.md#9000--manual-validation-and-final-closure).
  - Operator confirmed the ordinary lid cycle, visible backlight recovery, and
    graph extrema. `BB-2026-09-14-02` lid counts/markers are delivered and ready
    for the optional two-cycle visible check.
  - `BB-2026-09-14-03` is delivered: actual suspend detection across the whole
    run, approximate full-height white `S` on red graph regions, and durable
    coverage/uncertainty reporting. The 188-test native suite and compatibility
    checks pass. The continued-run supervised
    test is ready for physical sleep/resume and visible block confirmation.
  - `BB-2026-09-14-04` is delivered: bounded successful journal evidence can
    identify hibernate regions as green `H` on magenta; black `0` on dark gray
    is reserved for future powered-off regions. Unverified mode preserves
    clock-confirmed sleep with explicit uncertainty. All 225 native tests and
    compatibility/document checks pass. Automatable work is complete; no live
    hibernation is requested on this unsupported host.
  - P2 profile-transition and suspend observations remain in
    [BB-MANUAL-01/02](ai-human-requests.md).
  - On results, reactivate affected slices, repair reported defects,
    rerun affected checks, close requests, and ACP without another review gate.
  - Continuous history P6–P10 is now delivered: 344 native tests and both
    compatibility suites pass. Operator dev installation, service readiness
    and initial historical query passed on 2026-09-15 (slice 4000): seven system
    readings over 30 seconds, active/enabled service and ready collector.
    BB-MANUAL-03 now awaits warning/fallback/merged-history checks (slice 5000)
    and a supervised service-only sleep interval (slice 6000). All automatable
    work is complete.
  - Phase 1000 is complete: `--graph --last DURATION`, calendar subtraction
    and installed manual verification. The full suite now passes 378 native
    tests and 359 tests on each compatibility interpreter with two native-GI
    skips. Existing manual acceptance remains unchanged.


- `BB-2026-09-15-3000` — GTK 4 history viewer; started 2026-09-15.
  Owner: Codex; operator supplies final GNOME-session observations.
  - Scope: [roadmap phase 3000](../ROADMAP.md#phase-3000--gtk-4-history-viewer).
  - Slices 1000–5000 complete: GTK graph/table navigation, paged cross-database
    search, opt-in Unix socket automation/controller, installation, and manual
    are implemented. Live X11 smoke checks captured the client frame and
    exercised fullscreen, tabs, selection, search, and window operations.
  - Automated verification passed: 407 unit tests, installer syntax and
    read-only check, generated-doc check, groff validation, and `git diff
    --check`. No privileged/system installation was performed.
  - Slice 6000 awaits GNOME title-bar minimize, maximize/restore, and close
    checks. F11 graph-only fullscreen is automated; request BB-MANUAL-04 for
    visible GNOME window-manager controls. Phase 9000's earlier manual checks
    remain independently deferred.

- `BB-MANUAL-04` — GTK 4 history viewer GNOME window controls.
  - Created and activated: 2026-09-15. Owner: operator. Requestor: Codex.
  - Scope: roadmap phase 3000, slice 6000. Run the installed/development viewer
    in the normal GNOME session, then confirm the title-bar minimize button
    hides the window, restoring it returns the same viewer state, maximize and
    restore work, and close exits cleanly. On the graph tab press F11 and verify
    graph-only fullscreen reaches the screen edges; press F11 again and confirm
    the notebook returns. The socket automation test already covers F11 state,
    captured client frames, and minimize/maximize/restore/close requests, but
    compositor decoration behavior needs this visible check.
  - Acceptance: report pass/fail for each control and any visual/layout issue.
    If it passes, close the slice and phase. If not, record the defect and
    reactivate implementation before ACP.
