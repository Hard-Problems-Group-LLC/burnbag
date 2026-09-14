# Handled shutdown and reporting

- Status: implemented; original visible symptom awaits operator confirmation
- Authorization: operator request of 2026-09-14, roadmap phase P3

An operational session begins when the controller starts battery monitoring,
before any power, backlight, or inhibitor mutation. Every handled exit from
that point follows the common cleanup and reporting path: final observation
and statistics, persistent-state restoration, inhibitor release, synchronized
session-end record, and the terminal shutdown narrative, chart, and statistics.
Failures can make individual recovery steps unsuccessful; the report must
describe the available evidence rather than fabricate successful recovery.

SIGINT (including Ctrl-C) and SIGTERM apply during setup and to every operating
mode. Signal handlers remember the first request without logging or raising
inside mutation bookkeeping. Setup stops at the next safe boundary before
beginning another operation. A signal received immediately before event-loop
entry remains pending and stops the loop. Repeated signals cannot interrupt
the cleanup phase. Existing process signal handlers are restored on return.
Synchronous external operations already in progress finish or time out before
their safe boundary is reached.

`--ignore-lid` changes lid-open termination only. It does not suppress the
shutdown narrative, chart, final battery observation, or statistics. Explicit
`--no-plot` suppresses the chart while preserving the statistics. No valid
battery observations means there is no chart to draw; unavailable output
channels likewise cannot display one. Neither condition licenses invented
readings. The battery-monitoring specification defines telemetry availability.

Help, rejected command lines, and failures before controller initialization
are not meaningful operational starts. SIGKILL, power loss, and equivalent
unhandled termination cannot execute cleanup or display a final report.
Previously synchronized running-log records remain the evidence in those cases.

Validation uses real subprocess SIGINT/SIGTERM delivery, native PyGObject/GLib,
real battery fixtures and running-log files, and substituted system D-Bus
boundaries. It covers persistent and one-shot setup, repeated signals during
restoration, the event-loop entry race, lid termination, setup failure, and
`--no-plot`. It does not exercise physical lid or backlight behavior.
