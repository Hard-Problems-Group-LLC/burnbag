# Tasks In Progress

- `BB-2026-09-14-V` — Manual validation and final closure; started 2026-09-14.
  Owner: Codex; observations: operator.
  - Scope: [roadmap V](../ROADMAP.md#v--manual-validation-and-final-closure).
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
    and initial historical query passed on 2026-09-15 (V.4): seven system
    readings over 30 seconds, active/enabled service and ready collector.
    BB-MANUAL-03 now awaits warning/fallback/merged-history checks (V.5) and
    a supervised service-only sleep interval (V.6). All automatable work is complete.
  - Phase 1000 is complete: `--graph --last DURATION`, calendar subtraction
    and installed manual verification. The full suite now passes 378 native
    tests and 359 tests on each compatibility interpreter with two native-GI
    skips. Existing manual acceptance remains unchanged.
