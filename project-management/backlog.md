# Backlog

Use this backlog to track pending work in priority order. Keep the next item
at the top. Use a dated bullet with an indented body for each entry. Include a
stable ID, concise context, requestor or owner details, acceptance criteria,
dependencies and blockers, links to authoritative proposals, bugs, or
specifications, and ISO 8601 timestamps.

## Current Queue

- `BB-2026-09-15-VIEWER-LIVE` — Add live data updates to the graphical viewer.
  - Created: 2026-09-15T23:24:51-07:00. Requestor: operator. Owner: unassigned.
  - Status: backlog only, explicitly excluded from today's phase 6000 work.
  - Future scope: refresh from ongoing collection without reopening; update
    grouped unit ranges from every value currently shown while preserving
    navigation, field choices, gaps and read-only access. Define follow-tail
    versus user-pinned viewport behavior and refresh cadence before execution.
  - Phase allocation and implementation are deferred; do not add timers,
    database tailing, collector changes or automatic refresh in phase 6000.

- `BB-2026-09-15-GRAPH-ONLY` — Add the approved passive live terminal battery graph.
  - Created: 2026-09-15T22:13:07-07:00. Requestor: Operator. Implementation
    owner: unassigned until scheduled.
  - Status: approved and queued; implementation has not started. The operator
    explicitly places upcoming installer bug work ahead of this feature.
  - Authority and acceptance:
    [BB-PROP-2026-09-15-01](proposals/approved/BB-PROP-2026-09-15-01-passive-live-graph.md).
    Add `graph-only`, fixed refresh by default, and the uncapped increasing
    interval curve; sample and graph battery state without inhibitors, power
    controls, service changes, or persistence.
  - Dependency: address the operator's upcoming installer reports before
    selecting this item for execution. No additional feature approval is
    required, but this drafting task does not authorize starting implementation.
  - Scheduling: allocate a roadmap phase and local slices only when execution
    is scheduled, using the next available IDs under AGENTS.md.
  - 2026-09-15 update: the reported sudo/PATH installer defect is repaired and
    operator-verified (phase 5000; BB-MANUAL-05 closed). This feature remains
    queued; no implementation has started.

Existing warning/fallback and physical acceptance checks remain in
[the human-request queue](ai-human-requests.md), independently of this queued
feature.
