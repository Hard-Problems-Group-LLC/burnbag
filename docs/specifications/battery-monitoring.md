# Battery Monitoring, Depletion Plot, And Statistics Specification

- Status: Implemented; ready for operator validation
- Owner: burnbag maintainers
- Last reviewed: 2026-09-14
- Authorization: direct operator request `BB-2026-08-13-01` and approved
  [battery-statistics proposal](../../project-management/proposals/approved/BB-PROP-2026-08-13-02-battery-statistics.md)
  with direct per-minute extension `BB-2026-08-13-03` and the direct
  2026-09-14 requirement to always label both axis extrema

## Scope

This specification defines read-only battery discovery, fifteen-second
sampling, durable observation records, the handled-exit depletion plot, and
quantization-aware per-battery statistics.
It does not change power profiles, sleep decisions, backlight behavior, or
the safety priority of teardown.

## Discovery And Identity

Burnbag discovers Linux power-supply entries under
`/sys/class/power_supply`. An entry is eligible when its `type` is `Battery`,
its optional `present` value is not zero, and it exposes one of these sources,
in priority order:

1. Native `capacity`, validated as a whole percentage from 0 through 100.
2. A complete `energy_now` / `energy_full` pair.
3. A complete `charge_now` / `charge_full` pair.

Some ARM drivers expose energy without native percentages. Matched energy or
charge values are converted to `100 * now / full`, rounded to the nearest
whole percentage with half values rounded up. Every sample requires integer
values with `0 <= now <= full` and `full > 0`; invalid or unreadable values
produce explicit gaps. Energy and charge units are never mixed, and design
capacity, current, voltage, and power are not substitutes for a missing source.
This is a derived fuel-gauge percentage, not an electrical power measurement.
The [Linux power-supply contract](https://docs.kernel.org/power/power_supply_class.html)
allows drivers to omit attributes and distinguishes energy, charge, and
percentage units.

The chosen source remains fixed for the entire run. A native percentage or
selected ratio that becomes invalid or disappears produces a gap, even if a
lower-priority source is available. A recovered source contributes readings
again. Burnbag identifies derived sources at startup and records every selected
source in discovery, sample, and summary log details. Kernel power-supply names
provide stable series labels within one run.

Devices are selected in lexical kernel-name order. Burnbag monitors one or
two installed batteries independently. If a machine exposes more than two
eligible battery devices, burnbag monitors the first two, reports the
explicit selection, and records a non-fatal warning rather than silently
assigning an unspecified third plot color.

Selected kernel names are fixed at discovery for the duration of the run. A
selected battery that disappears and returns begins a new local-rate segment;
a newly named power supply inserted after discovery is outside this revision
and is not added mid-run.

No battery is a valid state for desktops and virtual machines. It produces an
informational result and no plot, not a mission failure.

## Sampling Lifecycle

Burnbag takes an initial sample before operational host mutation. Persistent
`run*` modes then use the GLib event loop to sample every 15,000 milliseconds.
Handled teardown cancels the timer before other cleanup and takes one final
sample so the plot includes the end of the run. One-shot modes therefore have
initial and final observations but do not establish a periodic timer.

Each sample stores:

- timezone-aware local wall-clock time for presentation;
- suspend-inclusive Linux `CLOCK_BOOTTIME` elapsed time for ordering, plot
  placement, and rate calculations;
- the independently read percentage for every selected battery that was
  available in that cycle; and
- optional `present` and `status` observations when the driver exposes them.

`present=0` creates a missing percentage observation. An unavailable optional
`status` does not invalidate a percentage. Wall clock is never used for rate
calculation, so clock adjustment cannot reorder or distort the series.

Every cycle is appended to the mandatory synchronized running log as a
`battery_sample` record, including initial, periodic, and final reasons.
Discovery, timer start and stop, read failures, and the final summary are also
recorded. A running-log failure retains its existing fail-closed behavior.

A sysfs discovery or read failure is observational: burnbag reports it,
records a deviation and nonzero final status, and continues the primary power
session and safety teardown. A repeated identical read failure is reported
once to the console while later cycles may recover and contribute data.

## Plot Contract

Unless `--no-plot` is supplied, handled shutdown prints a plot when at least
one valid battery observation exists. `--no-plot` suppresses presentation
only: discovery, sampling, logging, and the end summary remain active.

The plot has exactly 25 data rows. At render time it uses the full reported
standard-output terminal width, with a minimum of 20 columns; an 80-column
fallback applies when terminal width cannot be determined. The percentage Y
transform spans only the minimum through maximum values actually observed,
never an automatic 0--100 range. Axis labels are drawn only from observed
percentage values. The top data row always labels the observed maximum, and
the bottom data row always labels the observed minimum. When both are equal,
the same percentage appears at both boundaries while the constant series
remains vertically centered. The Y axis renders no more than one observed
percentage callout per plot row.

The X axis orders sample attempts by elapsed time and uses their actual local
wall-clock `HH:mm` values for labels. With the `--ignore-lid` diagnostic overlay,
its range includes the union of sample-attempt and lid-event timestamps, so
every event falls within the plotted interval. Otherwise only sample attempts
establish the range. Its left and right boundaries always label the earliest
and latest entries in that range, including missing battery readings or events
beyond the sample interval. These two callouts are reserved before any interior
labels are selected. Equal `HH:mm` values are repeated at both boundaries.
When the entire plotted timeline has one elapsed value, both true endpoint
labels remain without inventing a duration, and plotted points remain at the
left. Boundary ticks align with the axis edges; interior ticks retain actual
elapsed-time positions.
Callouts must leave at least two blank screen columns between adjacent labels,
so neither axis may overlap or concatenate labels.

Lines connect consecutive available samples; a missing reading creates a
visible gap instead of being silently interpolated across.

With ANSI output enabled, battery one is yellow, battery two is blue, and a
cell occupied by both is green. Plain output and `--no-color` use the distinct
ASCII symbols `1`, `2`, and `X`, respectively, so color is not the only series
encoding. The legend identifies kernel battery names and overlap semantics.

With `--ignore-lid`, actual detected lid transitions add vertical background
markers across the data rows: magenta for a close and yellow for an open.
Battery glyphs and series colors remain unchanged at intersections, taking
precedence over event markers. A separate header marks event columns with `C`
for close, `O` for open, or `B` for both. Plain vertical markers use `|`, `:`,
or `!`, respectively. When close and open map to the same screen column, the
combined `!` marker alternates magenta and yellow down the column in colored
output. Markers add no data rows and do not connect battery lines across gaps.

Several events can share a screen column; the overlay summarizes their kinds,
while separate shutdown close/open counts retain the exact detected totals,
including zero. The initial lid snapshot and duplicate same-state
notifications are excluded. Event timestamps share the battery samples'
process-start `CLOCK_BOOTTIME` origin and preserve actual local wall time.
See [lid observation semantics](power-lifecycle.md) and
[durable event fields](runtime-log.md). `--no-plot` suppresses this overlay
along with the graph but does not suppress counts or event logging. Without
any valid battery observation there is no graph, while counts remain available.
Without `--ignore-lid`, the battery graph has no lid-event overlay.

## Derived Statistics Contract

Handled shutdown prints one to three summary lines for each selected battery,
below the chart when the chart is enabled. `--no-plot` suppresses only the
graph; sampling, durable records, and statistics remain enabled. The summary
supports terminal widths of 40 columns or more without truncating a metric.

The first and last reported percentages, net change in percentage points
(`pp`), elapsed span, and valid/attempted coverage are descriptive facts. A
whole-run least-squares fit uses actual `CLOCK_BOOTTIME` hours:

```text
p(t) = a + b*t
reported depletion trend = -b pp/h
```

The trend requires at least five valid readings, five elapsed minutes, and at
least two reported levels. `R²` is a descriptive staircase-fit diagnostic,
not a confidence claim. A qualifying constant history says `no reported
whole-percentage change`; it must never claim zero electrical draw. Direction
is called depleting or rising only when fitted and endpoint changes agree and
each has magnitude of at least 2 pp. Kernel `status=Discharging` or
`status=Charging` may corroborate the corresponding wording; otherwise the
display says falling or rising SoC.

Raw differences between adjacent 15-second integer readings are prohibited:
a one-point update would manufacture a `240 pp/h` impulse among zeros. Instead,
each reported level change between consecutive valid observations is an
interval-censored event placed at the midpoint of its two observation times.
Its uncertainty is up to half that bracket. A multi-point jump remains one
event. Missing readings, a nonpositive interval, an interval greater than
`max(45 seconds, 3 * median attempt cadence)`, or a known status change starts
a new per-battery segment.

Local reported-gauge rates are formed only between consecutive transition
events in the same segment:

```text
r[j] = -(q[j] - q[j-1]) * 3600 / (tau[j] - tau[j-1]) pp/h
w[j] = tau[j] - tau[j-1]
mean = sum(w[j] * r[j]) / sum(w[j])
sigma = sqrt(sum(w[j] * (r[j] - mean)^2) / sum(w[j]))
average reported change per minute = -mean / 60 pp/min
reported change standard deviation per minute = sigma / 60 pp/min
```

The displayed `gauge depletion-rate variability σ` is therefore a
duration-weighted population standard deviation of the inferred gauge rates.
It describes how uneven the reported depletion velocity was; it is not
acceleration, watts, instantaneous system load, or battery-health telemetry.
It requires at least three local rates. A coefficient of variation requires
at least five local rates and one observed direction. Median minutes per
one-point update excludes multi-point jumps and requires at least two eligible
same-direction intervals. Mixed histories, observed reversals, coverage,
segments, gaps, status breaks, transition count, robust MAD scale, and maximum
transition bracket are retained in the structured log; relevant warnings are
also shown on screen.

The summary additionally shows the duration-weighted average reported-gauge
change per minute and its standard deviation. The average is signed in the
natural percentage direction: falling SoC is negative and rising SoC is
positive. The standard deviation is nonnegative. Both use `pp/min`, not a
relative percent-of-percent unit. They are minute-unit conversions of the
same gated transition-rate distribution, not derivatives of raw samples and
not a second independent physical measurement. When local variability is
unavailable, both per-minute values say `n/a`; a constant integer gauge must
not display `0.00` as though it proved zero electrical drain.

Opposite movement is classified as mixed only when it totals at least 2 pp or
appears in at least two transitions. This keeps an isolated one-point gauge
recalibration visible as a reversal without overclaiming a charging phase.
The two batteries are always analyzed independently; their percentages are
never averaged.

The summary uses the plot-series color for battery identity and trend, and
magenta for gauge-rate variability. Plain output retains every label and unit,
so color carries no exclusive meaning.

## Derived Running-Log Schema

The final `battery_monitor_summary` and handled `session_end` retain a
`battery_statistics` array. Each version-2 per-battery object identifies
`CLOCK_BOOTTIME`, endpoints, span, coverage, unit-bearing OLS and variability
fields, signed average reported change and standard deviation in `pp/min`,
transitions, local rates, robust MAD scale, cadence, reversals,
segments, gap/status-break counts, and validity reasons. Unavailable values
are JSON `null`, never NaN or infinity.

## Failure And Safety Boundaries

Battery reads and calculations are strictly observational and must not delay or replace backlight
restoration, inhibitor release, or power-profile restoration. Timer
cancellation and final sampling occur inside handled teardown, but any
battery-monitor failure is caught before persistent-state recovery begins.
Chart and statistics rendering are attempted independently. A rendering or
output error selects nonzero status and is included in the final running-log
outcome, but cannot interrupt or reverse completed teardown. If stdout fails,
reporting tries stderr when available.

`SIGKILL`, sudden power loss, and equivalent unhandled termination cannot
render a plot or take a final sample. Previously synchronized periodic sample
records remain the forensic result in those cases.

## Acceptance Criteria

- Real temporary sysfs fixtures cover discovery, absence, presence filtering,
  two-battery selection, percentages, and malformed or failed reads. An
  energy-only Qualcomm-shaped fixture produces observations, chart, statistics,
  and source records. Charge fallback, source priority, half-up quantization,
  invalid ratios, missing source recovery, and mixed-unit/design rejection are
  covered without touching host state.
- Timer tests verify an immediate sample, 15,000-millisecond cadence, handled
  cancellation, and a final sample.
- Chart tests verify 25 data rows, selected terminal width with a 20-column
  minimum, observed-only Y range, unconditional top/bottom percentage labels,
  and unconditional left/right sample-attempt `HH:mm` labels. Coverage includes
  equal extrema, constant centered series, lone/equal-time samples at the left,
  missing edge readings, non-overlapping callouts and ticks, two series,
  overlap, and ANSI/plain encodings.
- Formula tests cover falling, constant, mixed, gapped, status-changing, and
  uneven quantized histories, validity gates, weighted variability, and
  suspend-inclusive timing.
- Summary tests verify one-to-three lines per battery, 40-column bounds,
  ANSI/plain semantics, signed per-minute average and standard deviation,
  explicit units, and the no-watts qualification.
- Lifecycle tests verify `--no-plot` suppresses only the chart and battery
  failure cannot prevent safety teardown.
- Help, startup/shutdown narratives, running-log final state, README, and man
  page document the default and opt-out.
- The suite passes on Python 3.9, system Python, and Python 3.14.
