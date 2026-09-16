# Bug: Viewer command and rendering conceal available history

- ID: `BB-BUG-2026-09-15-01`
- Status: Resolved
- Priority: High
- Reported and resolved: 2026-09-15
- Reporter: Operator
- Owner: Codex
- Related work: ROADMAP phase 3100; GTK history viewer specification

## Symptom and evidence

The viewer appeared to miss system history and possibly user history. Its
bare PATH command matched the original `4cdf4ba` implementation, which graphed
only the first 500 table rows. The newer checkout was not selected. Read-only
inspection found more than 6,000 readable system records and an active system
collector. The operator's normal state directory contained the older running
log but no user SQLite store, and no user service was installed. An isolated
assistant XDG path must not be used to infer the operator's history availability.
No database loss was demonstrated.

## Root causes

The development installer published a user launcher only for burnbag; bare
viewer/controller commands continued to use system copies. The subsequent
full-history renderer also retained only bucket extrema, losing flat tails;
it treated distances between reduced points as sampling gaps and did not draw
singleton observations. Zoom reused reduced data. Graph hit testing and table
navigation could use different time ranges, while redundant JSON filtering
removed valid SQL local-date search matches. Missing Cairo integration could
prevent the drawing callback from rendering.

## Resolution

Publish and verify the complete dev command family with managed-file safeguards.
Require the Cairo binding, preserve bucket endpoints/extrema and raw segment
boundaries, draw isolated points, reread detail at viewport resolution, and
share graph drawing/click coordinates. Seek unloaded rows by time and leave
search matching to SQLite. Expose actual source paths, row counts, extents and
missing/error states; bound the launch snapshot while collectors append.
Initial/locked range handling is tested across both sources and all controls.
Capture PNGs in memory so installed builds need no executable-directory writes.

## Validation and delivery

The 426-test native suite includes actual GTK/Cairo/socket/frame verification
against both SQLite sources. Compatibility suites, installation command
resolution, source failures, flat-tail/gap regressions and manuals pass.
The final staged build exactly matches raw SQLite for 3,572 records and 3,568
battery samples in its five-hour snapshot and produces a visible complete
graph. Full evidence is in `project-management/completed-tasks.md`.

Code delivery is complete. The operator performs the actual development
installation; no host database, service or installation was modified during
investigation. Pre-existing GNOME window-control acceptance remains separate.
