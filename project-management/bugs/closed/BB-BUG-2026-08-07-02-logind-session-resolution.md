# Bug: Backlight Setup Rejects Processes Outside Logind Session Accounting

- ID: `BB-BUG-2026-08-07-02`
- Status: Resolved
- Priority: High
- Reported: 2026-08-07T14:48:37-07:00
- Reporter: Operator
- Owner: Codex
- Related work: `BB-2026-08-07-03`

## Symptom And Impact

A live `burnbag run-cool --suspend-after-minutes 20` test terminates before
acquiring inhibitors or changing the backlight because logind reports
`NoSessionForPID`. Launchers running through tmux, a user service, or another
scope can belong to the correct logged-in user without their process being
directly assigned to a logind session.

## Reproduction Or Evidence

At 2026-08-07T14:48:37-07:00, PID 512594 received:

`org.freedesktop.login1.NoSessionForPID: PID 512594 does not belong to any known session`

The failure occurred in `GetSessionByPID` during backlight preparation. The
three-second timer did not fire and the shutdown narrative correctly reported
that the backlight remained unchanged.

## Expected Behavior

Prefer the process's own active local logind session when available. If PID
accounting cannot resolve it, select the operator's primary active local
display session through documented logind user/session properties. Validate
the selected session belongs to the effective UID, is active, and is not
remote before exposing `SetBrightness`.

## Actual Behavior

Backlight preparation treats `GetSessionByPID` as the only session-resolution
path and converts `NoSessionForPID` directly into a fatal error.

## Root Cause

The implementation assumed every interactive launcher PID is directly
tracked by logind. That assumption does not hold for common long-lived shell
and user-service scopes even when the user has an active graphical session.

## Resolution

Backlight preparation now attempts the process PID, inherited
`XDG_SESSION_ID`, and the logind user object's
authoritative primary `Display` session in order. Every resulting session
proxy must belong to the effective UID, report `Active=true`, and report
`Remote=false`. The selected source and object path are printed before any
brightness mutation; complete failure reports every attempted route.

## Validation

Four new resolver regressions cover the reported `NoSessionForPID` fallback,
inherited session selection, rejection of a remote PID session in favor of the
local display, and wrong-UID rejection with combined diagnostics. A fifth test
ensures fatal setup failures appear in the shutdown deviation list. The full
23 test suite passed under Python 3.9.21, system Python 3.12.13, and pyenv
Python 3.14. Generated documentation was reproducible; source compilation,
help, prerequisite/install checks, Bash syntax, ShellCheck, man warnings,
whitespace, and diff checks passed. On 2026-08-07, the operator reran the
original live path on the supported laptop and confirmed the corrected session
resolution and backlight lifecycle looked good.

## History

- 2026-08-07T14:48:37-07:00 — Operator reported the first live hardware-test
  failure.
- 2026-08-07T14:50:03-07:00 — Moved directly into active remediation.
- 2026-08-07T14:55:11-07:00 — Implemented and non-mutating validation passed;
  retained in progress pending reproduction-path confirmation on the operator
  workstation.
- 2026-08-07T15:36:08-07:00 — Operator confirmed the live retest succeeded;
  marked resolved and closed.
