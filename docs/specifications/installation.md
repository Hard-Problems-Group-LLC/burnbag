# Installation and development command selection

Status: implemented. Reviewed: 2026-09-15.
Authorization: [roadmap P1, P4, P5, P9, and 1000](../../ROADMAP.md).

This specification defines the filesystem and command-selection behavior of
[`install.sh`](../../install.sh). Distribution package selection belongs to
[Linux platform support](platform-support.md). `install.sh --help` lists the
supported options; help does not load Python bindings or install anything.

## Standard and staged installation

Standard mode installs the executable as `bin/burnbag` with mode 0755 and the
manual as `share/man/man1/burnbag.1` with mode 0644 under the selected absolute
prefix, which defaults to `/usr/local`. Reusable Python modules and the removal
helper live in `lib/burnbag/`; `bin/burnbag-uninstall` is the installed removal
entry point. Existing ordinary destination files
may be replaced. A destination file must not be a directory or symlink.
The installed manual is a byte-for-byte copy of the generated `burnbag.1`,
including the [`--last` duration and calendar semantics](duration-ranges.md).
System installation uses `sudo` when required and refreshes the manual index
when `mandb` is available. Privileged destination ancestors must be root-owned
and not writable by group or other users. Existing private user directories
retain their permissions.

`--destdir DIR` prepends a staging root to the prefix. DIR must be absolute
and must not resolve to the filesystem root. Empty paths and parent-directory
(`..`) components are rejected. All target files must resolve inside the
canonical staging root; existing intermediate symlinks that escape it cause
failure before file installation. Staging invokes neither `sudo` nor `mandb`,
and never creates host service accounts or changes service activation.

Prerequisites are checked before application files are installed. A normal
standard or development installation may install missing native bindings.
`--check` and staged `--destdir` installations pass `--check` to the
prerequisite helper, so missing bindings produce a nonzero diagnostic without
installing host packages. `--check` does not install application files;
`--skip-prerequisites` explicitly skips both package verification and package
installation.

Option values, incompatible mode options, required source files, and standard
destination constraints are validated before invoking the prerequisite helper.
`--destdir` and an explicit `--prefix` are incompatible with development mode.
`--dev-command` and `--force` apply only to development mode. `--user-home`
also identifies the intended user for user-service staging and removal.

## Service installation

The default scope is the system `burnbag.service`, running under the non-login
`burnbag:burnbag` account with a root-owned executable. The installer deploys
the unit, sysusers declaration, and a narrow polkit rule allowing only bounded
delay inhibition for pending telemetry writes before sleep/shutdown. Runtime
singleton ownership prevents system and user collectors from running together.
Installing while the other applicable scope is active fails with remediation.

`--install-user-service` instead installs the unit under
`$XDG_CONFIG_HOME/systemd/user/` or `~/.config/systemd/user/`. Actual user service
installation runs as its intended non-root login user. The selected state
directory is retained in the unit; no lingering preference is changed.

New installations enable and start the selected service. Updates restart an
active service and preserve deliberate stopped/disabled states. A failed first
activation remains recorded as pending, so rerunning can finish it. Installation
does not silently stop another collector. The service account, database paths,
permissions, activation commands and ownership protocol are specified in
[continuous history](continuous-history.md).

System prefixes outside `/usr` and `/usr/local` also publish a managed unit
copy at `/etc/systemd/system/burnbag.service`, so systemd can find the collector
under a custom prefix. This copy belongs to the installation manifest and is
staged beneath `--destdir` during staging. Removal checks the selected unit's
actual path before stopping it; uninstalling an older prefix preserves a
collector currently selected from another installation.

## Development installation

Development mode runs as the intended non-root user. It creates repository-local
links at `.local/bin/burnbag` and `.local/share/man/man1/burnbag.1`. Rerunning
accepts existing links to the same source; unrelated links and existing files
are preserved with an error.

Plain `--mode dev` still installs the default system service and its own
root-owned daemon copy. Reinstall after changing daemon code. Combining dev
mode with `--install-user-service` makes that daemon execute this checkout
directly and installs a user-owned manual copy at
`<user-home>/.local/share/man/man1/burnbag.1` with mode 0644. Reinstall to refresh
this copy after documentation changes; the repository-local manual link still
follows the checkout immediately. Both variants retain the CLI command-selection
policy below.

The optional managed user launcher is `<user-home>/.local/bin/burnbag`.
The selected home must be an existing absolute directory. An explicit
`--user-home` overrides the ambient HOME. Without that option, a resolved HOME
named `.codex-home`, `.claude-home`, `codex-home`, or `claude-home`, or located
at or beneath this checkout's `.local/`, is rejected with guidance to select
the operator's home explicitly.

Command-selection policy is selected by `--dev-command`, then
`BURNBAG_DEV_LAUNCHER_MODE`, then the default `prompt`:

| Policy | Required behavior |
| --- | --- |
| `prompt` | Ask on an interactive terminal. Acceptance selects `local`; declining, EOF, or a noninteractive invocation preserves the existing user launcher and command resolution. |
| `local` | Publish a managed user launcher that executes this checkout. The user bin directory must already be on PATH ahead of any competing burnbag command. Verify command lookup after publication. |
| `system` | Remove an existing managed user launcher. Preserve an unmanaged launcher and report the resulting PATH resolution. |

`--force` permits replacing an unmanaged user launcher during `local`
selection. A directory or symlink to a directory is refused even with
`--force`. The installer does not edit shell profiles or change its parent
shell's environment; it reports when existing shells should run `hash -r`.

## Scoped uninstallation

`uninstall.sh` and the installed `burnbag-uninstall` use installation manifests
to stop/disable the selected service and remove only managed artifacts. Select
`--system-service` or `--user-service` explicitly when scope cannot be inferred;
`--prefix`, `--destdir`, and `--user-home` identify matching locations. If both
standard and dev user installations exist, select `--mode standard` or
`--mode dev`. Shared files remain while another manifest references them.
This includes the user manual when a standard `--prefix <user-home>/.local`
installation and a dev user installation coexist, regardless of removal order.
Modified files, unrelated overrides and private configuration are preserved.

History, dependencies, and the service account remain by default. Explicit
`--purge-data` removes only the selected history after stopping its service.
User-history purge reserves the foreground ownership socket, refusing while
an existing foreground collector owns it and preventing fallback from opening
the database during deletion. `--check` validates without removing files or
changing service state. Staged removal is confined to the staging root.

## Failures and verification

A managed user launcher is written to a unique file in its destination
directory, made executable, then renamed into place. Failed writes, permission
changes, and rename operations clean up that temporary file and preserve the
previous launcher. A cleanup failure identifies the remaining temporary path.

Installation errors return nonzero and identify the operation that failed.
Installation is not a transaction across the executable, manual, repository
links, user launcher, and package manager. Earlier successful steps may remain
after a later failure; diagnostics explain this and direct the operator to
resolve the reported error and rerun. A failed operation must not print a
successful installation claim.

[`tests/test_install.py`](../../tests/test_install.py) and
[`tests/test_service_install.py`](../../tests/test_service_install.py) check isolated staged
files and modes, prerequisite check-only staging, command-resolution policies,
actual terminal EOF handling, implicit assistant homes, unsafe target refusal,
and injected launcher/partial-installation failures. All four mode/scope
combinations verify installed manual bytes, including `--last` calendar
semantics; user manual removal checks both shared ownership and modified-file
preservation. These fixtures do not
install packages or modify the operator's real user or system installation.
