# Installation and development command selection

Status: implemented. Reviewed: 2026-09-14.
Authorization: [roadmap P1, P4, and P5](../../ROADMAP.md).

This specification defines the filesystem and command-selection behavior of
[`install.sh`](../../install.sh). Distribution package selection belongs to
[Linux platform support](platform-support.md). `install.sh --help` lists the
supported options; help does not load Python bindings or install anything.

## Standard and staged installation

Standard mode installs the executable as `bin/burnbag` with mode 0755 and the
manual as `share/man/man1/burnbag.1` with mode 0644 under the selected absolute
prefix, which defaults to `/usr/local`. Existing ordinary destination files
may be replaced. A destination file must not be a directory or symlink.
System installation uses `sudo` when required and refreshes the manual index
when `mandb` is available.

`--destdir DIR` prepends a staging root to the prefix. DIR must be absolute
and must not resolve to the filesystem root. Empty paths and parent-directory
(`..`) components are rejected. Both target files must resolve inside the
canonical staging root; existing intermediate symlinks that escape it cause
failure before file installation. Staging invokes neither `sudo` nor `mandb`.

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
`--dev-command`, `--user-home`, and `--force` apply only to development mode.

## Development installation

Development mode runs as the intended non-root user. It creates repository-local
links at `.local/bin/burnbag` and `.local/share/man/man1/burnbag.1`. Rerunning
accepts existing links to the same source; unrelated links and existing files
are preserved with an error.

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

[`tests/test_install.py`](../../tests/test_install.py) checks isolated staged
files and modes, prerequisite check-only staging, command-resolution policies,
actual terminal EOF handling, implicit assistant homes, unsafe target refusal,
and injected launcher/partial-installation failures. These fixtures do not
install packages or modify the operator's real user or system installation.
