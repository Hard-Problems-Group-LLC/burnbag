# Resolved Bugs

Index resolved bugs with the newest entry first. Include the stable ID,
closure timestamp, short outcome, and link to the authoritative record under
`closed/`. Keep root cause, resolution, and validation evidence in that
record.

- `BB-BUG-2026-09-14-01` — Resolved 2026-09-14; both graph axes always label
  both extrema, including equal values and short/flat histories. See the
  [closed record](closed/BB-BUG-2026-09-14-01-chart-extrema-labels.md).

- `BB-BUG-2026-08-13-01` — Resolved 2026-08-13T14:42:36-07:00; battery-chart
  axes retain only real observed callouts, mark selected sample positions, and
  guarantee visible separation between time labels. See the
  [closed record](closed/BB-BUG-2026-08-13-01-battery-chart-label-overlap.md).

- `BB-BUG-2026-08-07-02` — Resolved 2026-08-07T15:36:08-07:00; backlight
  control now resolves and validates the operator's active local display
  session when launcher PID accounting is unavailable. See the
  [closed record](closed/BB-BUG-2026-08-07-02-logind-session-resolution.md).

- `BB-BUG-2026-08-07-01` — Resolved 2026-08-07T11:59:13-07:00; development
  installs now manage and verify effective command resolution without silently
  replacing operator-owned launchers. See the
  [closed record](closed/BB-BUG-2026-08-07-01-dev-launcher-resolution.md).
