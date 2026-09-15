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

- `BB-2026-09-15-01` — Continuous power history and optional services; started 2026-09-15.
  Owner: Codex; authorized by operator instruction to fully implement.
  - Scope and acceptance: [continuous history](../docs/specifications/continuous-history.md), roadmap P6–P10.
  - P6 storage is completed with 30 passing tests. Collector and installer slices proceed independently; CLI/graphs and integration owned by primary agent.
  - ACP without review at each completed or manually deferred phase. No host installation or live sleep is performed by automated tests.
