# GTK 4 history viewer

This specification is authorized by the operator's 2026-09-15 request for a
GNOME desktop viewer for burnbag's system and user telemetry databases. The
viewer is a separate helper application and does not change collector behavior.

## User interface

- Use GTK 4 and native window decorations so GNOME's minimize, restore,
  maximize, and close controls remain available. F11 toggles fullscreen.
- Present two notebook tabs: a graph and a virtualized, continuously paged
  table. The graph is the first tab. In graph fullscreen, graph content fills
  the client area and all viewer controls, tabs, and table content are hidden.
- The table presents local date and time as its first two columns; remaining
  columns represent telemetry measurements and record attributes. Heterogeneous
  JSON fields may appear blank for records that do not contain them. Discover
  measurement columns across the complete available history, not just the
  currently loaded table page.
- Support graph zoom, pan, and search. A row double-click focuses the graph at
  that record. A table range plus View highlights and fits that interval in the
  graph. Both table actions switch to Graph. Graph double-click sets the cursor
  and clears the highlighted interval without switching tabs.
- With no range parameters, cover all available history in both the graph and
  table. Build a bounded overview of all numeric samples for the graph while
  preserving the table's responsive keyset paging; show the total row count and
  continue loading older/newer rows as the user scrolls. Keep downsampled graph
  extrema so short-lived peaks remain visible, and let zoom reveal detail.
- Read both system and user SQLite databases when readable. Treat absent or
  unreadable sources as a visible per-source condition; never create a database
  or modify collector data. Stream rows in stable timestamp/record-ID order and
  fetch table pages as needed rather than materializing the full history.
  Expose each source path, state, snapshot row count and time extent through
  automation and the status tooltip. Capture row-ID ceilings on open, releasing
  read locks between pages, so collector appends do not extend a query forever.
  Reopening reads a new snapshot. The older operational `burnbag.log` is a
  separate JSON-lines narrative, not a SQLite telemetry store.
- Merge duplicate record IDs with system records taking precedence. For
  measurement streams with system coverage metadata, suppress only overlapping
  user-side measurements; retain other user measurements from the same record.
  Report ID collisions, source failures, corrupt records, and coverage-based
  overlap suppression in the UI.
- Search across record IDs, event kinds, scopes, local timestamps, and serialized
  telemetry in both sources. Run source queries off the GTK main thread and page
  matching results just like ordinary table rows.

## Field selection and preferences

The toolbar's **Fields...** button replaces the single-measurement drop-list.
It opens a modal window with Graph and Table pages, each containing two columns
of named checkboxes and vertical scrolling. Graph choices are numeric sample
fields from the complete snapshot catalog; Table choices include measurement
and record fields. Date and Time always remain the first two table columns.
The dialog is available once discovery finishes, including for empty histories.
Long names have full-name tooltips. Graph and Table selections are independent.
The implementation uses a transient modal `Gtk.Window`, consistent with
[GTK's dialog guidance](https://docs.gtk.org/gtk4/class.Dialog.html), while
retaining compatibility with the project's GTK 4.6 baseline.

Checkboxes edit a draft only. **OK** atomically saves both selections and then
applies them together; **Cancel**, Escape and titlebar close discard the draft.
Enter activates OK. No field changes affect either view before OK. Failed saves
leave the draft open with a visible error and keep both applied views unchanged.
Changes preserve viewport/locks, search text, loaded rows and table selection.

Persist versioned JSON in `$XDG_CONFIG_HOME/burnbag/viewer.json`, falling back
to `~/.config/burnbag/viewer.json` for unset/empty/non-absolute XDG_CONFIG_HOME.
The file is private (0600), published through a temporary sibling and atomic
replacement. Preferences never write to a history database. Missing preferences
retain the former defaults: the first percentage field (otherwise first numeric
field), and all table columns. Invalid/unreadable preferences give a visible
warning and use defaults without overwriting the file until OK. Explicit empty
selections are valid; an empty graph explains how to select fields and the table
retains Date/Time. Saved names absent from the current snapshot are retained
for future launches. Newly discovered names remain unchecked after an explicit
selection. Concurrent viewers use the last successfully saved selection.

## Shared plot and unit scales

Phase 6000 replaces tiled panels with one exact plot rectangle for **all**
selected traces. One time transform is shared, and each unit type has one
independently autoranged Y transform. Its range contains all finite values
shown for every selected field in that unit within the visible time interval,
including reduced extrema. Hidden fields and out-of-viewport values do not
expand it. Empty/flat ranges get safe bounds; gaps and singleton points remain
visible. Changes to selection, viewport or size recompute layout and ranges.

Known units include %, W, Wh, V, A, Ah, degrees Celsius and MHz. Battery
percentages and CPU busy percentages share %. Energy and full energy share Wh;
charge and full charge share Ah; all temperature channels share degrees Celsius.
Explicit synthetic units include Cycles, Online state and Backlight power state.
Brightness/actual-brightness counts share a unit only within the same device,
since hardware count scales differ. Unknown numeric fields receive their own
field-named unit, never a shared catch-all unitless scale. No conversion or
guessing from observed magnitudes is performed.

Unit ordering follows first occurrence in the deterministic selected-field
catalog. Axis strips alternate outside-in: unit 1 is outer left, unit 2 outer
right, unit 3 next inward on the left, unit 4 next inward on the right. All strips
share the plot's vertical extent; no series has its own panel or inset plot.
Center each unit title along its strip and rotate it 90 degrees counter-clockwise
on both sides. Measure text before allocating strip widths. Aim for ten divisions
(eleven ticks), reducing divisions when vertical spacing would be less than
1.5 times the measured numeric label height. Use readable distinct tick labels
and bounds that retain every displayed value. Do not shrink text into illegibility
to force a fit; explain when the window must be enlarged or fewer unit types chosen.

Give each trace a distinguishable color. The color key is a box inside the plot,
centered horizontally near its bottom, with a 50%-alpha background and opaque
labels colored to match the corresponding traces. Wrap labels within the box;
keep it inside the plot and retain full field/unit names in automation. Render
the key above traces, with data remaining visible through its background.

Zoom, pan, focus and fullscreen share the same plot geometry. Clicks in label
strips do not select observations; inside the plot, pick the closest displayed
observation in pixel space across all traces. Drag distance uses the plot
width, not the whole widget width.
One bounded viewport query supplies all selected fields. The snapshot remains
fixed: live updates are explicitly backlog-only, with no refresh timer today.

## Cursor, highlighted interval and navigation

Phase 7000 keeps three independent concepts: the cursor (timestamp and record
ID), the highlighted inclusive time interval, and the graph viewport. Left-drag
inside the plot replaces the highlight, without moving the viewport or cursor.
Reverse drags work; endpoints clamp to the plot edges. Movement under four
horizontal pixels is click jitter, not a range. The translucent selection band
is clipped to the plot and drawn beneath the traces/cursor/key.

Single-left-click sets the closest displayed observation as cursor, retaining
any interval. Double-left-click sets the cursor and clears the interval, staying
on Graph. Without observations, double-click still clears the interval but does
not invent a cursor. Clicking axis strips does nothing. Arrow buttons/keys pan
only the viewport, preserving cursor and highlighted interval.

On Table, only rows inside the highlighted interval are navigable, intersected
with the search and any `--only` lock. Without a highlight the entire allowed
snapshot is navigable, independent of graph zoom or startup viewport. The cursor
row is highlighted by ID, not timestamp alone; it remains remembered if outside
the interval or excluded by search but does not bypass either filter. Finding a
cursor beyond the first page loads preceding pages asynchronously rather than
silently redefining the table's lower bound. Tab changes restore its highlight.
Search changes retain the interval; stale page responses cannot restore an old
filter or cursor selection.

The toolbar orders **−**, **Fit**, **+**. Fit is enabled only with a highlighted
interval and fits the graph to it exactly; table filtering remains that same
interval. Plus halves and minus doubles the current graph time span about its
midpoint, then updates the highlight/table interval to that resulting viewport.
Wheel zoom uses the same synchronization with finer increments. Zoom has a
one-second minimum span; `--only` remains a hard boundary. Y axes continue to
autorange by unit over the new viewport. Fit does not switch tabs or clear the
cursor. A single table row selected with View uses a one-second graph window
around its exact timestamp, while the table interval retains that timestamp.

Right-click resets the graph to its initial viewport and clears cursor and
highlight. All history clears search, cursor and highlight and restores the
complete allowed snapshot in both views (All in range with `--only`). Neither
action modifies persistent preferences or queries new live data.

## Initial viewport and query boundaries

`--last DURATION` sets an initial interval ending at the single startup-time
snapshot of now. It uses the same grammar and local calendar subtraction as
the terminal graph: days/weeks are elapsed time; months/years and larger units
subtract whole calendar months at the same local time, clamping month ends.
`--from` and `--to` accept the terminal graph's ISO times and defaults; they
cannot be combined with `--last`. With no range options the viewer covers all
available history. Initial range arguments affect the graph only; the table is
unrestricted unless an interval is highlighted or `--only` is supplied. All
history fits and browses the full allowed snapshot (All in range when locked).
Cursor navigation never inserts a hidden ID search or hides preceding rows.

`--only` requires an explicit range option. It restricts graph/table queries,
search, overview statistics and navigation to the fixed inclusive interval.
Zoom and pan inside the interval remain supported; zoom-out, reset, row/range
focus and drag are clamped at its boundaries. Neither startup loading nor a
search/series change may reset the viewport to a different interval. Automation
reports the initial range, allowed bounds, actual viewport and source paths.

Graph reduction retains each time bucket's first, last, minimum and maximum
observations. Continuity is determined from raw samples before reduction;
long distances between reduced representatives cannot create false gaps.
Real missing measurements, long raw intervals and collector changes break
lines; dots retain isolated observations. Zoom/pan rereads the requested
viewport at its own resolution. Rendering and hit testing share its exact
time transform, including empty leading/trailing time in an explicit range.

## Automation

Automation is opt-in with `--automation SOCKET_PATH`; ordinary launches create
no control socket. The path is a caller-supplied Unix-domain socket. A matching
`burnbag-viewerctl` controller connects to it. Use bounded newline-delimited
JSON requests and correlated IDs, with explicit protocol/version and structured
errors. The protocol supports semantic keyboard input, pointer move/button/wheel
input, table row/range selection, navigation/search/zoom commands, window state
inspection, and a complete PNG capture of the viewer client area. UI actions use
the same handlers as normal user input. Bound frame and request sizes, reject malformed messages,
restrict the socket to the launching user's access, and remove only the socket
created by this process on shutdown.

A capture includes the complete GTK client area. GNOME's server-side titlebar
and decorations belong to the window manager and are outside the application's
capture surface. Automated UI acceptance must separately verify native window
controls and F11 behavior on a GNOME session.

Known implementation limitation: the existing capture path needs PyGObject
3.48+ fundamental render-node bindings. Native 3.46 returns a binding error,
although ordinary drawing works. This is tracked separately as
[BB-BUG-2026-09-15-03](../../project-management/bugs/open/BB-BUG-2026-09-15-03-gtk-capture-bindings.md);
the installer does not yet enforce or diagnose that optional capability.

`fields open`, `fields set --view graph|table --name FIELD --checked yes|no`,
`fields tab --view graph|table`, `fields ok` and `fields cancel` use the same
dialog widgets and commit/cancel handlers. State includes applied graph/table
fields, available catalogs, draft selections, preference path and errors.
While the dialog is open, capture returns its complete client frame; background
navigation is blocked. Return, Escape and window close operate on the dialog.
The legacy `series NAME` command selects one graph field transiently; use Fields
OK to persist it. `pointer click fields` opens the toolbar dialog.

`graph_layout` reports the widget size, exact shared `plot` rectangle (`x`, `y`,
`width`, `height`), time range, measured label height, ordered unit axes with
fields/ranges/ticks/strip rectangles/rotated-title centers, trace colors and
unit associations, and key box/alpha/colored labels. Full unit and field names
remain available even when display text is elided. A null plot plus a message
explains insufficient space or an empty selection. This is the same geometry
used for drawing and pointer actions, not a parallel approximation.

Selection/navigation state additionally reports `selected_range` (nullable,
inclusive endpoints), `cursor` (nullable record ID and timestamp), `fit_enabled`,
`table_bounds`, `table_loading`, `table_has_more` and `cursor_row_selected`.
The controller's `fit` command and `pointer click fit` use the toolbar handler;
Fit with no highlighted interval is a no-op. `zoom FACTOR` scales both views.
Pointer press/move/release routes through the same drag threshold, plot transform
and cursor handlers as GTK input; a motionless press/release counts as a click.

## Acceptance

The app starts in a normal GNOME window, responds to all window controls and
F11, displays both tabs, pages large histories without blocking interaction,
keeps row/graph navigation synchronized, and supports graph zoom/pan/search.
With automation disabled there is no socket. With it enabled, a matching
controller can exercise keyboard and mouse actions, inspect state, and retrieve
full client-area PNG frames. Both database sources remain unchanged.
