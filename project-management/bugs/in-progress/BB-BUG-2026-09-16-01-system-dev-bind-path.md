# Bug: System dev collector cannot open its checkout entry point

- ID: `BB-BUG-2026-09-16-01`
- Status: in-progress
- Priority: High
- Reported: 2026-09-16T00:36:51-07:00
- Reporter: Operator
- Owner: Codex
- Related work: roadmap phase 3100, slice 5000; `BB-2026-09-16-01`;
  `BB-MANUAL-06`

## Symptom And Impact

After development installation, starting the system collector fails with
`can't open file '/run/burnbag-dev/source/burnbag.py': [Errno 2] No such file or directory`.
The service repeatedly restarts, readiness is absent, and continuous power
history is not recorded while this failure persists.

## Reproduction Or Evidence

The operator provided a failed start, service status and journal entries on
2026-09-16. The installed service selects the intended checkout, but renders
`BindReadOnlyPaths` with the complete `source:destination` tuple inside one
pair of quotes. Read-only inspection of systemd 257's parsed properties shows
the concatenated source/destination path repeated as both mount endpoints.
The real `systemd-analyze verify` parser accepts the syntax with exit zero;
its debug dump exposes the incorrect endpoints.

## Expected Behavior

Development installation binds the checkout read-only at
`/run/burnbag-dev/source`, allowing the normal `burnbag` service account to run
checkout code while retaining `ProtectHome=yes`. The collector becomes ready
and records new observations.

## Root Cause

systemd splits bind-path definitions at unquoted colons. Quoting the entire
tuple hides the separator, so the parser sees a single path and defaults the
destination to that same path. Existing tests checked emitted text and syntax
acceptance without asserting the parsed mount endpoints.

## Resolution

Implemented: quote the source and destination separately with an unquoted
colon between them; retain service isolation. Regressions inspect the real
systemd parser's resolved mount for ordinary and special-character checkout
paths. Installed-service acceptance remains pending.

## Validation

The real-parser regression fails before the repair and passes afterward for
ordinary checkout paths and paths containing spaces, dollar signs, percent
signs, quotes and backslashes. All 57 affected `test_service_install` and
`test_install` cases pass; `bash -n install.sh uninstall.sh` and whitespace
checks pass. Tests ran unprivileged, outside the sandbox for systemd parser
access, without sudo or host-service mutations.

After integration with the delivered phases 5000–7000, all 65 installer tests
pass, including the added standard sudo-installation cases. Remote features
and completion evidence are preserved. All 17 tracking tests, final shell
syntax and whitespace checks pass on the integrated result.

Installed-service recovery is pending operator reinstallation, restart, ready
status and advancing history observations in BB-MANUAL-06. Agents must not
execute sudo commands. No successful host repair is claimed.

## History

- 2026-09-16T00:36:51-07:00: operator reported the failed collector start.
- 2026-09-16T00:41:12-07:00: confirmed parser root cause; opened in-progress
  repair and reactivated phase 3100, slice 5000. Earlier GNOME and physical
  hardware checks remain deferred independently.
- 2026-09-16T00:44:53-07:00: code repair and automated verification complete;
  bug remains in progress pending operator-installed runtime evidence.
- 2026-09-16: integrated newer delivery work and passed all 65 installer cases.
  Collector acceptance uses BB-MANUAL-06; existing closed BB-MANUAL-05 remains
  the independent standard sudo-installation acceptance record.
