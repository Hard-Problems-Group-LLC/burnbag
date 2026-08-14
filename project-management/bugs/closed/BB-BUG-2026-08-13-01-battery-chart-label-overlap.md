# Bug: Battery Chart X-Axis Callouts Can Touch

- ID: `BB-BUG-2026-08-13-01`
- Status: Resolved
- Priority: Medium
- Reported: 2026-08-13T14:33:53-07:00
- Reporter: Operator
- Owner: Codex
- Related work: `BB-2026-08-13-01`

## Symptom And Impact

The battery chart contains correct samples and plots, but adjacent local-time
callouts can touch at the left and right boundaries. The resulting strings,
such as `13:3113:33` and `14:3114:33`, are visually ambiguous and reduce the
usefulness of the X axis.

## Reproduction Or Evidence

The operator ran burnbag from approximately 13:31 through 14:33 with two
batteries. The handled-exit report contained 252 samples and rendered the
touching callouts shown above in a wide terminal.

## Expected Behavior

Every Y- and X-axis callout must identify a real observed value or real sample
position. Selected labels must never overlap or touch. The X axis should
retain useful coverage across the run, including an endpoint when it fits,
and visibly mark the sample position associated with each displayed `HH:mm`.

## Actual Behavior

X-axis capacity is estimated as one five-character label per seven plot
columns. Placement rejects direct overwrite but permits adjacency, and it does
not account for the half-label displacement lost when the first and final
labels are clamped to plot edges.

## Root Cause

The label selector treats non-overlap as sufficient and budgets no explicit
inter-label whitespace. Edge-clamped labels consume more horizontal room
toward the plot interior than centered labels, so the nominal seven-column
cadence can place consecutive five-character labels in adjacent cells.

## Resolution

The renderer now groups callout candidates by actual sampled `HH:mm`, uses the
last sample from the last group as the endpoint, and reserves that endpoint
before greedily selecting interior callouts. Each selected label interval must
leave at least two blank screen columns before the next interval. The axis
marks every selected sample column with a `+`, including the final real sample.

Y-axis behavior remains data-bound: only actually observed percentages are
eligible, and quantized values share at most one callout per plot row.

## Validation

A regression recreates 252 samples at 15-second intervals across a 190-column
terminal from 13:31 through 14:33. It asserts endpoint retention, at least two
blank columns between every displayed label, and a one-to-one count between
ticks and callouts. Existing tests continue to verify exact full width, 25
data rows, observed-only Y callouts, ANSI and plain series, overlap, missing
sample gaps, constant values, and narrow output.

The renderer was also replayed against the operator's exact 252 synchronized
`battery_sample` records without modifying the log. It selected 21 actual
callouts from `13:31` through `14:33`; the minimum measured separation was
three blank columns. The full 59-test suite passed under Python 3.9.21, system
Python 3.12.13, and Python 3.14.6. Compilation, generated-document
reproducibility, man rendering, prerequisite/installer checks, Bash syntax,
ShellCheck, whitespace, and FieldManual cleanliness also passed.

## History

- 2026-08-13T14:33:53-07:00 — Operator reported the live output and supplied
  the complete chart evidence.
- 2026-08-13T14:39:30-07:00 — Defect confirmed and moved directly into active
  remediation.
- 2026-08-13T14:42:36-07:00 — Collision-aware callouts, exact ticks, live-log
  replay, supported-version regression suites, and documentation passed;
  marked resolved and closed.
