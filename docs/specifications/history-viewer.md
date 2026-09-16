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
  that record. A table range plus View fits that interval in the graph. A graph
  double-click selects and reveals the nearest corresponding table record.
  These commands switch to the destination tab.
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

Multiple selected graph fields have independent labeled plots and Y scales,
with extrema labeled on both axes and a common time interval. Up to three plots
stack vertically; larger selections tile across the graph. Zoom, pan, focus and
fullscreen apply to all plots together; double-clicking any plot navigates to
its observation. A single bounded viewport query supplies all selected fields,
preserving raw continuity and independent units.

## Initial viewport and query boundaries

`--last DURATION` sets an initial interval ending at the single startup-time
snapshot of now. It uses the same grammar and local calendar subtraction as
the terminal graph: days/weeks are elapsed time; months/years and larger units
subtract whole calendar months at the same local time, clamping month ends.
`--from` and `--to` accept the terminal graph's ISO times and defaults; they
cannot be combined with `--last`. With no range options the viewer covers all
available history. The table initially shows the selected interval; search and
navigation may leave it without `--only`. All history fits and browses the full
allowed snapshot (All in range when locked). Graph-to-table navigation seeks
the observation and subsequent rows without inserting a hidden ID search.

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

`fields open`, `fields set --view graph|table --name FIELD --checked yes|no`,
`fields tab --view graph|table`, `fields ok` and `fields cancel` use the same
dialog widgets and commit/cancel handlers. State includes applied graph/table
fields, available catalogs, draft selections, preference path and errors.
While the dialog is open, capture returns its complete client frame; background
navigation is blocked. Return, Escape and window close operate on the dialog.
The legacy `series NAME` command selects one graph field transiently; use Fields
OK to persist it. `pointer click fields` opens the toolbar dialog.

## Acceptance

The app starts in a normal GNOME window, responds to all window controls and
F11, displays both tabs, pages large histories without blocking interaction,
keeps row/graph navigation synchronized, and supports graph zoom/pan/search.
With automation disabled there is no socket. With it enabled, a matching
controller can exercise keyboard and mouse actions, inspect state, and retrieve
full client-area PNG frames. Both database sources remain unchanged.
