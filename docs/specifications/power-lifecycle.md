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
