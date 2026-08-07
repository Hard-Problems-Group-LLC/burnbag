# Bug: Development Install Does Not Affect Command Resolution

- ID: `BB-BUG-2026-08-07-01`
- Status: Resolved
- Priority: High
- Reported: 2026-08-07T10:14:41-07:00
- Reporter: Operator
- Owner: Codex
- Related work: `burnbag-ECR-2026-001`

## Symptom And Impact

`./install.sh --mode dev` reports a successful development launcher under the
checkout's `.local/bin`, but that directory is not activated in the invoking
shell. A previously installed `/usr/local/bin/burnbag` therefore continues to
win normal command lookup. The success report is operationally misleading and
developers can unknowingly exercise the standard installed copy instead of
their checkout.

## Reproduction Or Evidence

1. Run `./install.sh` so the standard executable exists under `/usr/local/bin`.
2. Confirm `command -v burnbag` resolves to `/usr/local/bin/burnbag`.
3. Run `./install.sh --mode dev`.
4. Observe that the installer reports a checkout-local launcher while
   `command -v burnbag` still resolves to `/usr/local/bin/burnbag`.

## Expected Behavior

Interactive development setup detects the competing command and asks whether
bare `burnbag` invocations should prefer the checkout. When local resolution
is selected, it installs a safely managed launcher in an existing user PATH
directory and verifies that command lookup selects it. Non-interactive setup
requires an explicit override to change command resolution and otherwise
reports that the existing command remains authoritative.

## Actual Behavior

Development mode creates a link under `$(PROJECTROOT)/.local/bin` and merely
suggests adding that path to `PATH`; it neither changes nor verifies the
effective `burnbag` command.

## Root Cause

The installer treated creation of a checkout-local link as equivalent to
development command activation. A child process cannot modify its parent
shell's environment, and no already-active launcher directory was managed.

## Resolution

Development mode now detects a competing `burnbag`, offers an interactive
choice, and can place a managed launcher in the operator's existing
`~/.local/bin`. It refuses unmanaged-target replacement without `--force`,
requires the user bin directory to precede the competing command, and verifies
the resulting `command -v` lookup. Non-interactive runs leave command
resolution unchanged unless `--dev-command` or
`BURNBAG_DEV_LAUNCHER_MODE` selects an explicit policy. `--user-home` handles
isolated automation environments without writing into their synthetic home.

## Validation

Six installer regression tests cover local selection, system restoration,
non-interactive default and environment policy, unmanaged-launcher
protection, PATH-order failure, and isolated-home safety. The complete suite
passed on Python 3.9, system Python 3.12, and pyenv Python 3.14. Shell syntax,
ShellCheck, prerequisite and installer check modes, generated-document
reproducibility, man-page rendering, help smoke tests, and diff checks also
passed.

## History

- 2026-08-07T10:14:41-07:00 — Operator reported the failed command-resolution
  transition after standard and development installs.
- 2026-08-07T10:18:22-07:00 — Moved directly into active remediation.
- 2026-08-07T11:59:13-07:00 — Resolved after managed-launcher behavior,
  documentation, automation policy, and regression validation were complete.
