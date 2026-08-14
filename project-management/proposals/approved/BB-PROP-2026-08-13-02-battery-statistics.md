# Quantized Battery Depletion Statistics

- ID: `BB-PROP-2026-08-13-02`
- Author: Codex
- Sponsor: Operator
- Date: 2026-08-13
- Status: Approved
- Reviewers: electrical engineer/lithium-battery specialist, Linux
  power-management specialist, statistician/data scientist; Operator is the
  decision authority and has pre-authorized implementation after board review
- Affected projects or audiences: burnbag maintainers and operators
- Related work:
  - `BB-2026-08-13-02`
  - [Battery monitoring specification](../../../docs/specifications/battery-monitoring.md)
  - [Battery-chart callout bug](../../bugs/closed/BB-BUG-2026-08-13-01-battery-chart-label-overlap.md)

## Problem Statement

The handled-exit chart makes an hour of dual-battery behavior visible, but it
does not quantify net depletion, the best-fit drain trend, or how much the
observed gauge drain rate varied. A simple derivative of integer percentage
readings every fifteen seconds is actively misleading: one one-point gauge
update appears as a `240 pp/h` spike among many zeros.

The summary must be sophisticated enough to be useful while remaining honest
about Linux fuel-gauge resolution, dual-pack sequencing, gaps, charging, and
short runs.

## Goals

- Render one to three concise lines per selected battery below the chart, or
  below the shutdown report when `--no-plot` suppresses the graph.
- Report start/end percentage, net percentage-point change, observed span,
  valid/attempted readings, a whole-run depletion or charging trend, and fit
  quality when the data supports them.
- Estimate local first-derivative variability without differentiating raw
  fifteen-second integer steps.
- Make flat, short, gapped, missing, charging, and mixed-direction data
  explicit instead of fabricating precision.
- Preserve the yellow/blue series identity and readable text without ANSI.
- Include the computed fields in the synchronized `battery_monitor_summary`
  running-log event.

## Non-Goals

- Infer watts, watt-hours, battery health, electrochemical state, thermal
  condition, or remaining runtime from integer state-of-charge percentages.
- Compare or combine dual-pack percentage-point rates as though pack
  capacities were equal.
- Claim that a fuel-gauge update cadence is direct high-frequency electrical
  load measurement.
- Add new required dependencies or mutate any power-supply property.

## Use Cases

- An operator can see that one pack remained unresolved at `5%` while the
  other fell from `98%` to `87%` at an approximately `11 pp/h` trend.
- A stable discharge can be distinguished from a gauge history whose local
  rate changes substantially or reverses direction.
- A short one-shot run says that statistics are unavailable rather than
  reporting a meaningless enormous rate.
- Missing battery readings reduce visible coverage and break local-rate
  continuity instead of being interpolated.

## Constraints And Assumptions

Verified constraints:

- Current portable telemetry is an integer `capacity` percentage read from
  Linux power-supply sysfs every fifteen seconds with actual monotonic times.
- Both selected batteries are sampled independently and may drain
  sequentially.
- The operator's live session contains 252 valid readings per battery over
  3756.9 seconds. `BAT0` stayed at `5%`; `BAT1` fell through eleven level
  transitions from `98%` to `87%`.
- Summary rendering occurs after safety teardown and cannot block state
  recovery.

Assumptions:

- Integer capacity is a filtered fuel-gauge estimate, not a direct energy or
  power measurement.
- Ordinary least squares is useful as a descriptive staircase trend, while
  `R²` is fit context rather than an inferential confidence claim.
- Actual elapsed times, not the nominal cadence, are authoritative.

## Current Context

The chart already retains actual sample positions, gaps, observed-only Y
callouts, and collision-free local-time X callouts. The shutdown narrative
reports only final percentages and sample count. The running log retains every
sample but does not contain derived session statistics.

## Proposed Approach

### Whole-Run Descriptive Trend

For one battery, take every valid pair `(t_i, p_i)`, where `t_i` is
suspend-inclusive Linux `CLOCK_BOOTTIME` elapsed hours and `p_i` is integer
percentage. Always show identity,
`first→last`, net `Δ` in percentage points, observed duration, and
`valid/attempted` coverage when at least two valid readings exist.

With at least five valid readings, at least five minutes of span, and at least
two observed levels, fit:

```text
p_i = alpha + beta * t_i
```

Report `-beta` as a positive depletion trend or `beta` as a positive rising
SoC trend, in `pp/h`; only optional status corroboration may use the words
discharging or charging. Also report descriptive `R² = 1 - SSE/SST`. Call a
direction resolved only when net and fitted change over the span are both at
least two percentage points and agree in sign. A constant eligible series
says `no reported whole-percentage change`; it does not claim zero physical
drain. Short or sparse series says exactly which evidence gate was not met.

### Eligible Reported-Gauge Transitions

Raw adjacent derivatives are forbidden. Instead, process contiguous valid
readings into constant-level plateaus. Place each observed level transition
halfway between the last old-level sample and first new-level sample. This is
the center of an interval-censored gauge-publication interval, not an estimate
of an electrochemical threshold crossing; retain the bracket width as timing
uncertainty in the structured result. A missing reading, `present=0`, status
transition, or elapsed gap greater than `max(45 seconds, 3 * median attempt
cadence)` breaks the per-battery segment and cannot contribute a derivative
across that boundary. Re-read optional `present` and `status` each cycle;
attribute absence is normal and not an error.

For consecutive eligible reported-gauge transitions in one segment, calculate signed
local depletion:

```text
r_j = -(q_j - q_(j-1)) * 3600 / (tau_j - tau_(j-1))  pp/h
```

With at least three local rates (four eligible transitions), report the
duration-weighted population standard deviation. For each local rate, let
`w_j = tau_j - tau_(j-1)`:

```text
mu_w = sum(w_j * r_j) / sum(w_j)
sigma_w = sqrt(sum(w_j * (r_j - mu_w)^2) / sum(w_j))
```

Duration weighting answers how uneven the reported depletion velocity was
over covered time without overrepresenting short gauge-update intervals. It
is labeled `gauge depletion-rate variability`, not acceleration, electrical
power variability, or background-load measurement. With at least five local
rates and one-directional transitions, show `100*sigma_w/abs(mu_w)` as
contextual CV. Also report `n`, the number of rates. Calculate unweighted
robust `MADσ = 1.4826 * median(abs(r_j - median(r)))` for the structured log,
but do not spend screen space on it in the default case.

Report median minutes per percentage point from same-direction, single-point
eligible intervals when at least two exist; multi-point jumps do not reveal
the intermediate publication times. Count observed sign reversals between
nonzero level transitions. One isolated one-point rebound is a reversal, not
a charging claim. Label the history `mixed` when opposite-direction motion
totals at least two points or occurs in at least two transitions; retain
signed variability and reversals, and omit CV and a single-direction cadence
claim. Local statistics cover only the first-to-last eligible transition
span, not the initial and final censored plateaus.

### Presentation

Use two logical lines per battery on wide terminals and three on narrower
terminals, never exceeding the one-to-three-line budget. A representative
wide result is:

```text
● BAT1 98→87%  Δ−11 pp / 1h02m37s │ depletion trend 11.0 pp/h │ R² .99 │ data 252/252
  ↳ gauge depletion-rate variability σ 1.8 pp/h (weighted, CV 16%, n=10) │ median 1 pp / 5m15s │ reversals 0
  ↳ avg reported-gauge Δ/min −0.19 pp/min │ σ 0.03 pp/min
```

A constant series is explicit:

```text
● BAT0 5→5%  Δ0 pp / 1h02m37s │ no reported whole-percentage change │ data 252/252
  ↳ gauge depletion-rate variability n/a — no observed level transitions
  ↳ avg reported-gauge Δ/min n/a │ σ n/a
```

Color the bullet, battery name, and headline trend with its existing series
color (yellow first, blue second). Use cyan/dim hierarchy for fit and coverage
and magenta for variability. Format pp/h and variability to one decimal and
`R²` to two decimals so the whole-percent gauge does not imply false
precision. Text, arrows, units, and `n/a` remain complete under `--no-color`
and redirection. `--no-plot` suppresses the plot only; the statistics remain
after the shutdown narrative. Render two lines at ordinary widths and up to
three compact lines per battery down to a documented 40-column minimum.

### Logging And Failure Boundaries

Samples use `CLOCK_BOOTTIME` so suspend time cannot masquerade as ordinary
15-second depletion. Derived fields are calculated from already-owned
in-memory samples and added
to `battery_monitor_summary`: coverage, endpoints, span, net change, trend,
fit, transition/rate counts, excluded gaps/segments/status breaks, weighted
mean and sigma, CV, median cadence, robust MAD sigma, reversals, direction,
signed average reported change and its standard deviation in `pp/min`,
timebase, bracket uncertainty, and validity reason. Fields live in a versioned
per-battery object and use JSON `null`, never NaN or Infinity. Calculation or rendering
failure is presentation/observation failure after sampling and must never
interrupt backlight, inhibitor, or power-profile recovery.

## Alternatives Considered

- **Raw 15-second first differences:** rejected because one integer step is a
  fictitious `240 pp/h` impulse and its standard deviation mostly measures
  quantization.
- **Non-overlapping fixed five- or fifteen-minute regressions:** more directly
  window load, but the observed hour would supply only four fifteen-minute
  rates, each containing about 2.75 quantized points. Arbitrary boundaries are
  less stable than the ten eligible event-to-event rates already present.
- **Optional `power_now`, `power_avg`, or `energy_now`:** technically valuable
  when drivers expose them, but not portable across supported devices and a
  material telemetry-schema expansion. Defer to a separate proposal rather
  than silently falling back between incompatible meanings.
- **Endpoint rate:** rejected because boundary quantization dominates short
  runs; whole-run OLS uses the complete staircase.
- **ETA to empty:** rejected because dual-pack sequencing, reserve cutoffs,
  load changes, temperature, voltage relaxation, and nonlinear discharge make
  short-run percentage extrapolation falsely authoritative.
- **Confidence intervals and p-values:** rejected because serial dependence
  and integer quantization violate ordinary inferential assumptions.

## Risks And Mitigations

- **Statistics look like electrical measurement:** use `pp/h`, label bounce as
  gauge `dSoC/dt`, document capacity resolution, and reject wattage claims.
- **Quantized flat line interpreted as zero draw:** say `no reported
  whole-percentage change`, never `0 pp/h`.
- **Charging or recalibration corrupts drain claims:** detect direction changes,
  show mixed history and reversal count, and omit one-direction CV/cadence.
- **Gaps create false rates:** reset transition continuity on missing readings
  and long elapsed gaps; expose coverage and excluded-gap count.
- **Overwide presentation wraps:** select two or three layout lines from the
  detected terminal width and test maximum visible width after stripping ANSI.
- **Metric calculation affects safety:** compute only from memory after final
  sampling; catch presentation errors after teardown.

## Validation

- Deterministic formulas cover linear falling/rising SoC, constant,
  quantized staircase, mixed direction, missing readings, long gaps, irregular
  cadence, minimum sample/span gates, and outlier-resistant logged MAD.
- A regression replays the operator's 252-sample session and expects
  approximately `11.0 pp/h`, `R² .99`, weighted `σ 1.8 pp/h`, and `5m15s`
  median per point for `BAT1`, with whole-percentage-change gating for `BAT0`.
- ANSI/plain tests verify series identity, hierarchy, full text, one-to-three
  lines per battery, and terminal-width bounds.
- `--no-plot` tests verify statistics remain visible.
- Running-log tests verify derived fields are synchronized before session end.
- Full tests and compilation pass under Python 3.9, system Python, and Python
  3.14; generated README/man output and installer checks remain reproducible.

## Open Questions

None for this revision. Optional Linux power/energy telemetry requires a
separate proposal because availability, units, sign, averaging semantics,
pack scope, and comparability materially change the data contract.

## Milestones

1. **Board review** — expert reviewers; exit after the draft receives
   adversarial statistical, Linux, and battery-domain critique.
2. **Decision/specification** — Codex under delegated operator authority; exit
   when the disposition and exact metric contract are durable.
3. **Implementation/tests** — Codex; exit when calculation, rendering,
   logging, and failure behavior pass focused tests.
4. **Validation/documentation** — Codex; exit when the supported matrix and
   generated user documentation pass.

## Adoption And Rollout

No command-line migration is required. Existing sample records remain valid;
older sessions simply lack derived summary fields. `--no-plot` retains its
documented sampling behavior and now makes the statistics, rather than the
graph, the final battery presentation. Rollback removes only derived display
and fields, not the underlying samples.

## Decision Log

- 2026-08-13 — Operator requested a small electrical/Linux/lithium/statistics/
  data-science board, authorized implementation immediately after the board
  reviewed and argued over the draft, and delegated final resolution of that
  discussion to Codex.
- 2026-08-13 — The adversarial board rejected raw derivatives, fixed windows,
  optional watt telemetry in this scope, false precision, and electrical-load
  claims. It approved capacity-only OLS plus interval-censored transition
  rates after requiring `CLOCK_BOOTTIME`, per-device segmentation, explicit
  validity gates, and careful gauge terminology. Under the Operator's
  delegated authority, Codex approved the amended proposal for implementation.
- 2026-08-13 — The Operator directly requested average percentage change per
  minute and its standard deviation in addition to the approved display. The
  implementation converts the existing gated duration-weighted local mean and
  sigma from `pp/h` to `pp/min`, negating the depletion convention so the
  average follows natural signed percentage change. It does not introduce a
  raw-sample derivative or a second estimator; unsupported histories remain
  `n/a`. The per-battery structured schema advances to version 2.
