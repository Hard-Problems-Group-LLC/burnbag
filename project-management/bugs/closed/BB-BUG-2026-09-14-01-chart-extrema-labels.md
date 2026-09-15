# Bug: Chart extrema need labels even when their values are identical

- ID: `BB-BUG-2026-09-14-01`
- Status: Resolved
- Priority: Medium
- Reported: 2026-09-14
- Reporter: Operator
- Owner: Codex
- Related work: ROADMAP 2000.2000; battery chart specification

## Symptom and expected behavior

During manual chart validation the operator required: “Both Graph axes always
need data labels on their extrema, or you can't get a sense of scale, even if
the values are the same at min and max.” Both Y boundaries and both X boundaries
must display their observed values; equal values must remain visibly repeated.

## Root cause

Constant Y values share the centered plotted row and therefore only receive
one centered label. X candidates collapse all samples from one displayed minute
into one group, replacing its first sample with the last. The axis can lose its
start label for short runs, and its extrema are not reserved independently of
interior callouts. The old contract allowed endpoint omission and must follow
the operator's clarified requirement.

## Resolution

The renderer reserves the top and bottom Y labels independently, retaining
both copies of a constant percentage while leaving flat data centered. X labels
at both frame boundaries come from the earliest/latest elapsed sample attempts,
including known timestamps with unreadable percentages. Both labels are reserved
before optional interior callouts and remain repeated when their displayed times
match. Single/equal-elapsed observations do not acquire a fabricated duration or
extra plotted points. Left and right ticks align with the data columns.

The fixed 25-row canvas, observed-only percentage range, actual wall-clock
labels, missing-reading gaps, ANSI/plain series, and two-column minimum spacing
remain intact. The specification and generated README/man page describe the
clarified contract, replacing earlier conditional endpoint retention.

## Validation

- 141 tests passed on Ubuntu/aarch64 distribution Python 3.13 with native GI.
- Python 3.9.21 and 3.14.6 each passed their 129-case compatibility suite with
  one explicitly skipped native-GLib module because those interpreters lack GI.
- Regression cases cover equal percentages, single/equal-elapsed observations,
  same-minute times, 0/100 boundaries, missing edge/interior readings, and clock
  changes at 20, 40, and 190 columns in ANSI and plain output.
- Read-only replay of the operator's real short flat session retains both
  identical Y bounds and both identical time labels at all three widths.
- Independent geometry checks found no label collisions or displaced ticks;
  generated-document consistency, man rendering, and whitespace checks pass.

No host power changes or new runtime sessions were needed to verify rendering.

## History

- 2026-09-14 — Direct operator requirement accepted; remediation started under
  final validation without reopening the already-confirmed Ctrl-C lifecycle fix.
- 2026-09-14 — Renderer, regression coverage, documentation, and real-session
  replay passed; resolved. Development launcher selects the correction on the
  next invocation. Physical P2 checks remain separately deferred.
