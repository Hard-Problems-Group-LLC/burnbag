# Backlight Lifecycle Specification

- Status: Implemented; awaiting live hardware validation
- Owner: burnbag maintainers
- Last reviewed: 2026-08-07

## Scope

This specification defines screen-backlight behavior for persistent `run*`
sessions. Immediate `suspend`, `hibernate`, and `normal` operations finish
without entering the event loop and therefore do not reach the delayed
backlight transition.

## Default Behavior

Unless `--do-not-touch-backlight` is present, burnbag must:

1. discover every kernel backlight device under `/sys/class/backlight`;
2. record each device's requested, actual, and maximum brightness before any
   backlight mutation;
3. resolve the caller's logind session and use its
   `org.freedesktop.login1.Session.SetBrightness` method;
4. schedule brightness zero for three seconds after process startup;
5. verify that every controlled device reports zero actual brightness;
6. before every handled exit, restore each device to its recorded nonzero
   brightness, or to ten percent of maximum when it started at zero; and
7. verify that every restored device reports nonzero actual brightness before
   process termination.

If discovery, mutation, or verification fails, burnbag must record the
deviation, attempt to restore every device it may have changed, terminate its
persistent session, and return a nonzero status. Failure to restore a touched
backlight is a teardown failure and must also produce a nonzero status.

## Opt-Out

`--do-not-touch-backlight` is non-default and suppresses discovery, scheduling,
mutation, and restoration. The startup and shutdown narratives must identify
the backlight as untouched.

## Lifecycle Limits

Normal completion, lid-triggered completion, handled `SIGINT`/`SIGTERM`, fatal
application errors, and caught main-loop exceptions use the verified teardown
path. No userspace program can run cleanup after `SIGKILL`, sudden power loss,
or an equivalent process destruction; documentation must not promise
backlight restoration for those cases.

## Acceptance And Validation

- The command-line help, README, generated man page, startup narrative, and
  shutdown narrative agree with this contract.
- Focused tests use a fake logind session and disposable sysfs-shaped files to
  cover delayed power-down, verified restoration, opt-out, mutation failure,
  and restoration failure without changing workstation hardware.
- A supported Fedora/RHEL laptop test remains required to validate the real
  logind policy, device driver, timing, and visual outcome.
