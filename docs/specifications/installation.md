# Installation and development command selection

Status: implemented. Reviewed: 2026-09-15.
Authorization: [roadmap P1, P4, P5, P9, 1000, and 3100](../../ROADMAP.md).

This specification defines the filesystem and command-selection behavior of
[`install.sh`](../../install.sh). Distribution package selection belongs to
[Linux platform support](platform-support.md). `install.sh --help` lists the
supported options; help does not load Python bindings or install anything.

## Standard and staged installation

Standard mode installs `bin/burnbag`, `bin/burnbag-viewer`, and
`bin/burnbag-viewerctl` with mode 0755, and installs their manual pages under
`share/man/man1/` with mode 0644 beneath the selected absolute prefix, which
defaults to `/usr/local`. Reusable Python modules and the removal helper live
in `lib/burnbag/`; `bin/burnbag-uninstall` is the installed removal entry point. Existing ordinary destination files
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
`--force` applies only to development mode. `--user-home` identifies the
operator whose command selection is being configured and the owner of a user
service. Checks and staging do not activate commands or services.

Standard installation supports both `./install.sh` (requesting sudo only for
privileged steps) and `sudo ./install.sh`. In a root process with sudo caller
metadata, the default operator home comes from the account database only after
matching numeric `SUDO_UID` and `SUDO_USER`. Missing, invalid or mismatched
identity fails before writes with an explicit `--user-home` remedy. That
option takes precedence; direct root without caller metadata uses HOME.
Non-root invocations ignore sudo metadata and retain their own HOME behavior.
No shell startup files are loaded and no directories are added to root's PATH.

## Service installation

The default scope is the system `burnbag.service`, running under the non-login
`burnbag:burnbag` account. Standard mode uses a root-owned installed executable;
development mode executes the selected checkout as described below. The installer deploys
the unit, sysusers declaration, and a narrow polkit rule allowing only bounded
delay inhibition for pending telemetry writes before sleep/shutdown. Runtime
singleton ownership prevents system and user collectors from running together.
Installing while the other applicable scope is active fails with remediation.

`--install-user-service` instead installs the unit under
`$XDG_CONFIG_HOME/systemd/user/` or `~/.config/systemd/user/`. Actual user service
installation runs as its intended non-root login user; root invocations are
rejected during preflight, including `--check` (staging is exempt). The selected state
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
links for the CLI, viewer, viewer controller, and both manuals under `.local/bin/`
and `.local/share/man/man1/`. Rerunning
accepts existing links to the same source; unrelated links and existing files
are preserved with an error.

Both system and user services execute checkout code in development mode.
The user service uses the source executable directly. For a system service,
PID 1 binds the checkout directory read-only at `/run/burnbag-dev/source` in
that unit's mount namespace, and starts `/usr/bin/python3 -B` with its
`burnbag.py`. `RuntimeDirectory` manages the mount's parent; `RequiresMountsFor`
orders access to the checkout filesystem. `ProtectHome=yes` and the normal
`burnbag:burnbag` identity remain in effect. The private mount bypasses private
home ancestors without changing their permissions. The checkout itself and its
runtime files must be readable by the service account. A source path containing
`:` is rejected because it conflicts with the bind-mount separator.

The directory mount observes atomic file replacements. Code changes take effect
on the next process invocation/restart without recopying application code;
reinstall after changing installation/unit definitions. A missing/inaccessible
checkout fails visibly; the service never falls back to the installed copy.
Development mode deliberately trusts the operator's mutable source code.
A dev system installation may retain packaged copies, but neither operator
commands nor its service execute those copies.

Both modes install current manuals. The user dev mode publishes manuals under
`<user-home>/.local/share/man/man1/`; repository-local links follow the checkout.
The operator retains actual host installation and service activation.

The mount behavior follows [systemd's execution documentation](https://raw.githubusercontent.com/systemd/systemd/main/man/systemd.exec.xml).

The managed user launchers are `burnbag`, `burnbag-viewer` and
`burnbag-viewerctl` under `<user-home>/.local/bin/`. Apply command selection to
the whole family so the GUI cannot silently keep running an older system copy.
The selected home must be an existing absolute directory. An explicit
`--user-home` overrides the ambient HOME. Without that option, a resolved HOME
named `.codex-home`, `.claude-home`, `codex-home`, or `claude-home`, or located
at or beneath this checkout's `.local/`, is rejected with guidance to select
the operator's home explicitly.

## Authoritative mode and transitions

`--mode dev` always selects the checkout for user commands and the configured
service, without an additional selection prompt. Standard mode is the default
when `--mode dev` is absent; it installs complete copies and selects those
copies. Code source and system/user service scope are independent choices.
Interactive and noninteractive invocations have identical mode semantics.

The obsolete `BURNBAG_DEV_LAUNCHER_MODE` is ignored with a diagnostic.
`--dev-command` is a compatibility spelling only: `local` may accompany dev
and `system` may accompany standard. A conflicting value or `prompt` fails
before installation. Neither mechanism can override the selected mode.

Dev mode preflights all three user-launcher targets, publishes managed wrappers
and verifies command lookup. Non-root standard mode checks inherited PATH
before installation, then verifies that all three commands resolve under the
installed prefix. Other checkout directories or unmanaged executables earlier
on that PATH cause an actionable error.

Root/sudo standard mode does not treat its privileged PATH as the caller's
shell PATH: the destination need not occur there, and a successful install
does not claim verified bare-command lookup for the user. Before retiring any
launchers, standard mode verifies that all three installed commands are regular
executable files, not symlinks. It retires only the selected operator's managed
dev wrappers and this checkout's managed command links. Root installs warn
about preserved unmanaged launcher targets and tell the operator to check
`command -v burnbag burnbag-viewer burnbag-viewerctl` after `hash -r` in their
normal shell. Standard copies run independently of the checkout.
Mode transitions update the selected service's execution source and reload its
unit; existing activation preferences follow the service policy above.

`--force` permits replacing an unmanaged user launcher in dev mode. Directories
are always refused. Standard mode preserves unmanaged conflicts: non-root
PATH conflicts fail; root installs warn without claiming user-shell activation.
Installers cannot change the parent shell's PATH, aliases or cached lookups;
non-root invocations verify inherited ordinary command lookup and report
`hash -r` where needed. No shell profiles
or other users' launchers are rewritten. Checks/staging never retire launchers.

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
and injected launcher/partial-installation failures. Privileged-path fixtures
substitute Bash identity/account lookup and stage the real service helper's
publication, exercising restricted PATH, sudo home selection, explicit
overrides, unmanaged preservation, read-only checks and incomplete publication
without granting root or touching the host service manager. All four mode/scope
combinations verify installed manual bytes, including `--last` calendar
semantics; user manual removal checks both shared ownership and modified-file
preservation. These fixtures do not
install packages or modify the operator's real user or system installation.
