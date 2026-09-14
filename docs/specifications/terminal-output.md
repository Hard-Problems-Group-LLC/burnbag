# Terminal Output Specification

- Status: Implemented; ready for operator validation
- Owner: burnbag maintainers
- Last reviewed: 2026-09-14

## Scope

This specification defines presentation for runtime messages, startup and
shutdown narratives, command-line help, usage errors, and the zero-argument
quick-start guide. It changes presentation only; operational modes and host
state behavior are outside its scope.

## Capability And Default Behavior

Color is enabled by default, independently for standard output and standard
error, when the selected stream reports that it is an interactive terminal.
ANSI styling must remain disabled for a non-terminal stream and when
`TERM=dumb`. Burnbag must not require PyGObject to show help, report a
command-line error, or print its zero-argument guide.

Runtime statuses retain explicit text labels such as `[INFO]`, `[OK]`,
`[EVENT]`, `[WARNING]`, `[ERROR]`, and `[FATAL ERROR]`. Narrative fields and
help entries retain their complete text. Color may add emphasis or hierarchy,
but must never be the only indication of meaning.

## Plain-Output Controls

`--no-color` is a non-default command-line option that disables ANSI styling
for all output streams before argument parsing renders help or errors. The
presence of the `NO_COLOR` environment variable also disables styling, as does
`TERM=dumb`. These controls apply consistently to runtime, narrative, help,
usage, and error output.

Python 3.14 and later provide an independent automatic-color facility in
`argparse`. Burnbag disables that facility and renders presentation through
its own policy boundary so `--no-color` and the environmental controls behave
consistently across supported Python versions.

The handled-exit battery chart and statistical summary follow this same color capability policy but
are otherwise governed by the canonical
[battery-monitoring specification](battery-monitoring.md). Its plain symbols
must distinguish both series and overlap without relying on ANSI color.
Battery identity and trend reuse the yellow/blue series colors; gauge-rate
variability uses magenta. Complete labels, percentage-point units, validity
reasons, and the qualification that the metric does not measure watts remain
present in plain output. Each battery also shows a signed average reported
change per minute and its nonnegative standard deviation in `pp/min`; `n/a`
preserves the estimator's evidence gates. Summary layout supports one to three
lines per battery at terminal widths of 40 columns or more. Compact output may
use `avgΔ` and `σrate`, with a footer defining their gauge-only meaning.

## Reporting failures

Handled shutdown restores host state before attempting the narrative, chart,
and statistics. Their failure boundaries are independent. Failed writes or
flushes select nonzero status; if stdout fails, the program tries stderr.
The final running-log record follows these attempts so it includes observed
output failures. A failed channel cannot prevent remaining cleanup or log
closure. See [shutdown lifecycle](shutdown-lifecycle.md) for the contract.

## Zero-Argument Invocation

Invoking `burnbag` without any arguments must print a concise error, usage
line, safe quick-start examples, and a `burnbag --help` pointer to standard
error. It returns command-line usage status 2 without loading runtime D-Bus
bindings or changing host state.

## Acceptance And Validation

- Interactive-terminal simulations cover styled help, parse errors, and the
  zero-argument guide.
- Tests cover explicit `--no-color`, `NO_COLOR`, `TERM=dumb`, and redirected
  streams, and confirm that presentation escapes do not alter plain content.
- The generated README and man page document the default, every opt-out, and
  zero-argument status.
- The suite passes on the minimum supported Python 3.9 and on system and
  current-development Python versions, including Python 3.14's argparse color
  behavior.
