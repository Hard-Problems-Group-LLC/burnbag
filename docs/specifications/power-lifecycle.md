# Power State, Lid Capabilities, And Recovery

- Status: Implemented; physical platform validation remains operator-owned
- Last reviewed: 2026-09-14
- Authorization: Ubuntu/ARM reliability and error-handling phases in `ROADMAP.md`

## Profile Selection And Ownership

Persistent profile modes snapshot the daemon's actual `ActiveProfile` before
attempting a change. Burnbag never invents a startup profile when reading it
fails. Plain `run` may proceed without profile control, with an explicit
warning when the read fails. A mode requesting a profile refuses to proceed
when the daemon or snapshot is unavailable.

Before changing a profile, burnbag checks the daemon's advertised `Profiles`.
An unsupported selection, including `run-hot` on a platform without
`performance`, is a failed request; no profile Set or inhibitor acquisition
follows that refusal. An already-active requested profile satisfies the
request without a Set.

Every Set has a synchronized mutation-intent record. Before dispatch, burnbag
marks the profile as potentially changed and its current state as unknown.
A lost reply or timeout can occur after the service applied a request; it
must not erase the recovery obligation. After an accepted Set, burnbag reads
`ActiveProfile` back and requires the requested value before reporting success.

For temporary profile modes, handled teardown attempts to restore the actual
snapshot whenever a Set might have changed it. Restoration also requires
readback verification. Failed restoration records a deviation, clears mission
success, selects nonzero status, and leaves the final profile unknown or at the
last observed value. It must not report an assumed successful restoration.

`normal` deliberately retains a successfully verified `balanced` result. Its
successful Set is not undone during teardown. A failed or uncertain `normal`
Set still triggers recovery to the original snapshot. Normal mode does not
release inhibitor descriptors owned by other processes or reset system-wide
policy.

The final narrative and structured final state distinguish unchanged,
verified changes retained by `normal`, verified restoration, attempted but
unverified restoration, and unavailable profile information.

## Inhibitor Descriptor Recovery

Burnbag validates the returned D-Bus handle and native descriptor and retains
close-on-exec ownership of acquired descriptors. Cleanup attempts every owned
descriptor even if another close, intent record, or diagnostic fails. A close
error produces nonzero status and an explicit unverified-release flag; it
cannot be silently described as successful release.

Failed closes are not retried because Linux may already have released the
descriptor number for reuse. Clearing the application's descriptor list means
all owned close attempts were made; it is not proof that every attempt
succeeded. Process death remains the kernel's final descriptor cleanup path.

## Lid Capability Contract

Before persistent operational mutation, burnbag verifies boolean UPower
`LidIsPresent` and `LidIsClosed` properties through
`org.freedesktop.DBus.Properties.Get`. The default lid-cycle exit and every
configured lid-close suspend timeout require usable lid telemetry. If that
capability is absent, startup fails before inhibitor acquisition.

An untimed `--ignore-lid` run may proceed without a lid sensor, with an explicit
warning that SIGINT, SIGTERM, or SIGHUP must end it. Initial lid state is read again
after listener registration, so starting with a closed lid arms the configured
timer. Changed values must be actual booleans; invalidated properties are
reread. Losing a required lid sensor terminates the session through handled
cleanup instead of pretending the old observation remains authoritative.

Burnbag counts detected closes and opens separately. The initial lid snapshot
establishes state and may arm a countdown, but is not a transition. A valid
property notification counts only when it changes the last observed state;
duplicate same-state notifications do not increment counts or add events.
These are observed sensor transitions, which may include false triggers,
rather than proof of physical lid movement.

Every transition retains its actual local wall-clock observation time and
suspend-inclusive `CLOCK_BOOTTIME` elapsed time. Lid events and battery samples
share one process-start elapsed origin so their positions can be compared.
With `--ignore-lid`, the shutdown narrative reports separate detected-close
and detected-open totals, including zero. Unavailable lid telemetry is
qualified; a later valid state observation clears that qualification without
counting an unchanged state. Counting and durable event logging continue with
`--no-plot` or without valid battery observations. The final structured state
includes both totals; individual event history remains in transition records.

`--ignore-lid` keeps the session alive across opens and enables the diagnostic
lid-transition overlay defined by [battery monitoring](battery-monitoring.md).
It does not disable sensor observation or change countdown semantics: an open
still cancels the active countdown, and a later close starts a fresh one.

## Sleep Requests And Timeouts

Immediate suspend, hibernate, and timer-triggered suspend check the relevant
systemd-logind `Can*` capability before sending the action. `yes` and
`challenge` permit a request with interactive authorization enabled. Denied,
unsupported, inhibited, and unrecognized results refuse the action with
nonzero status. A configured timeout also checks suspend capability during
startup, and rechecks it at expiry because policy or inhibitors can change.

Mission success is recorded only after logind accepts the requested action.
A timer capability or action failure selects nonzero status, records the
reason, and exits the event loop. Acceptance describes logind's response; it
does not prove a complete physical suspend/resume cycle.

Burnbag uses explicit project timeout policy: 10 seconds for property,
capability, and inhibitor requests, and 30 seconds for interactive suspend or
hibernate actions. Gio's default timeout is also finite; these values make
the application's bounds explicit. A timed-out action can still complete on
the service side, so its result remains unverified rather than being described
as definitely rejected.

## Actual suspend observation

Every accepted operational run uses a read-only clock observer with a nominal
one-second sampling interval. It runs independently of GLib in a background
thread, starting from the application-entry clock baseline and ending with a
final snapshot after host recovery and immediately before shutdown reporting.
This coverage includes setup, persistent operation or one-shot action, and
teardown. It requires no journal access, elevated privileges, or additional
runtime package and never requests, delays, or inhibits sleep itself.

Linux `CLOCK_BOOTTIME` includes suspended time while `CLOCK_MONOTONIC` excludes
it. Their offset therefore supplies suspend evidence independently of wall
clock changes and event-loop or process scheduling delays. Burnbag brackets
each monotonic read with boottime reads and retains the tightest of three
captures to reduce read uncertainty. Offset growth must exceed both a
one-millisecond floor and read uncertainty; cumulative accounting retains
smaller changes for reconciliation instead of discarding each one. Clock
absence, invalid readings, or observer failure make coverage incomplete,
never a claim that no suspend occurred.
This detector requires the real boottime clock rather than using a monotonic
fallback. See the [Linux clock contract](https://man7.org/linux/man-pages/man3/clock_gettime.3.html).

Suspended duration is measured; its placement between observations is an
estimate. Burnbag subtracts the suspended duration from the observation window,
splits the remaining awake time equally before and after it, and records half
that awake window plus clock-read error as boundary uncertainty. Scheduling
delays enlarge that uncertainty. Multiple sleeps between observations can
merge into one detected region; neither a region nor its plotted width
establishes a physical sleep cycle count. The shutdown summary and
[graph](battery-monitoring.md#actual-suspend-regions)
identify approximate timing; structured records retain numeric uncertainty.
The summary remains available without battery output or with `--no-plot`.

Sleep requests and `PrepareForSleep` notifications alone do not establish
actual suspended time. In particular, logind can emit the end-of-preparation
signal when its operation fails; the clock observer avoids treating those
notifications as proof. See [systemd's failure path](https://github.com/systemd/systemd/blob/main/src/login/logind-dbus.c).

## Sleep mode classification

Clock evidence establishes actual suspended time but does not distinguish
suspend from hibernate. After recovery, only when detected intervals exist,
burnbag may query the current boot's systemd journal to classify those
intervals. This optional read-only query has a three-second deadline, a 2 MiB
output cap, and a 4,096-record cap. It requires no elevated privileges and
never alters journal access, installs a dependency, or requests sleep.

Classification requires one unambiguous, successful start/stop pair emitted by
root's `systemd-sleep`, matched within the interval's monotonic observation
window and across the same boot, PID, system unit, and invocation identity when
available. The recognized start
message must identify the actual `suspend` or `hibernate` suboperation; a
compound `SLEEP` field alone is insufficient. Start messages indicate intent,
and stop records can be emitted after failure, so neither alone proves success.
Missing pairs, explicit failure, unrecognized formats, competing operations,
and compound or mixed operations that cannot be split reliably retain mode
`unknown`. See the systemd sleep implementation for
[structured suboperation records](https://github.com/systemd/systemd/blob/v257/src/sleep/sleep.c),
[earlier explicit messages](https://github.com/systemd/systemd/blob/v249/src/sleep/sleep.c),
and [legacy single-operation messages](https://github.com/systemd/systemd/blob/v239/src/sleep/sleep.c).

Only a successful matched hibernation pair changes a clock-confirmed region to
`H`; verified suspend and unknown mode use `S`, with unknown mode identified in
the report. Journal absence, inaccessible records, timeout, malformed output,
or limit exhaustion cannot erase clock evidence or turn a complete clock
observation into a coverage failure. They leave mode classification explicitly
unavailable or unverified. Classification changes neither measured duration
nor estimated boundaries; it does not infer separately timed stages from one
clock observation window. Counts describe classified regions, not guaranteed
physical sleep-cycle totals.

After the optional query, one final paired-clock observation extends coverage
through the query itself. Additional sleep detected in that window is retained
with mode `unknown`, and classification counts and the reason are updated.
Burnbag does not repeat the query, so another sleep cannot create an unbounded
shutdown lookup cycle.

The green-on-magenta hibernate encoding and reserved black-on-dark-gray
powered-off encoding are defined by [the chart contract](battery-monitoring.md#actual-suspend-regions).
The reservation introduces no power-off detection. Unhandled power loss cannot
finalize this process's report, and elapsed time alone cannot identify it as a
powered-off region.

## Verification

Stateful service fakes cover actual profile values, unavailable selections,
readback mismatches, lost Set replies after mutation, failed recovery,
retained normal mode, invalid/missing lid capabilities, invalidated lid
properties, denied sleep capabilities, and timer action failures. Real owned
pipe descriptors exercise cleanup after injected close and diagnostic errors.
Physical lid transitions, visible backlight restoration, and sleep/resume
remain separate manual checks on each new platform.

Primary interface references:

- [Gio proxy timeout policy](https://docs.gtk.org/gio/property.DBusProxy.g-default-timeout.html)
- [systemd-logind D-Bus contract](https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.login1.html)
- [Power Profiles daemon interfaces](https://upower.pages.freedesktop.org/power-profiles-daemon/ix01.html)
