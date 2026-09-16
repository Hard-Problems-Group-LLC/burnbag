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
  - Operator feedback found that the initial implementation exposed only the
    first 500 table rows and based its graph and field list on those loaded
    rows. Slice 3000 was reactivated to make no-argument startup cover the full
    history while preserving paged table loading; the correction below closes
    the slice.
  - Fix implemented: full-history scan builds a bounded, extrema-preserving
    graph overview and global measurement catalog; the table reports total rows
    and continues through all pages. Graph double-click now locates records
    outside the first table page. Live X11 check found 5,553 available system
    rows and an all-history overview with fields from beyond the first page.
    User history is unavailable in this environment and reported as such.
  - Automated verification passed: 408 unit tests, installer syntax/read-only
    check, generated-doc check, groff validation, and `git diff --check`. No
    privileged/system installation was performed.
  - Slice 6000 awaits GNOME title-bar
    minimize/maximize/restore/close checks in BB-MANUAL-04. Phase 9000's
    earlier manual checks remain independently deferred.
  - Phase 6000 is now complete: all traces share one rectangle, unit-grouped
    scales and alternating label strips, with a lower-center 50%-alpha color
    key. Actual GTK frames and interactions pass; the same GNOME check can
    include the updated graph after refreshing the intended installation.
    Native PyGObject 3.46 capture has a separately recorded pre-existing binding
    limitation; see [completed phase evidence](completed-tasks.md).
  - Follow-up phase 3100 is complete; its investigation, fixes and current
    426-test verification are in [completed tasks](completed-tasks.md).
    The earlier isolated assistant environment is not the operator's data
    location. Inspection of the operator's normal state directory confirms
    that its user SQLite store is absent, while the live system store is intact.
    Ready for `./install.sh --mode dev`, which now publishes
    all three bare commands from the checkout. The operator retains deployment.
    Follow-up slice 5000 also makes the selected system/user service follow
    checkout code and makes standard installation select installed copies.
    Phase 5000 subsequently repairs standard installation under sudo's restricted
    PATH and resolves the caller home for managed dev-launcher retirement;
    automated verification is complete. Operator standard installation and
    all three normal-shell command paths passed on 2026-09-15; BB-MANUAL-05
    is closed. The installed standard commands are now selected.

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
