# Linux platform support

Status: implemented; Ubuntu baseline lid/backlight confirmed by the operator.
Revised-build ARM profile, visible reporting, and suspend/resume checks pending.
Reviewed: 2026-09-14. Authorization: [roadmap P1/P2](../../ROADMAP.md).

Burnbag targets Linux systems with systemd-logind, UPower, and optional
power-profiles-daemon, on both x86-64 and aarch64. Distribution `/usr/bin/python3`
3.9 or later owns the native PyGObject dependency. Ubuntu 25.10/aarch64 is the
current native automated-validation platform; prior Fedora validation remains
in the completed-work records. Support of kernel/device behavior requires
capability observation, not an architecture or distribution name alone.

The prerequisite installer first checks the selected system Python and native
Gio/GLib/GTK 4.6+ and Cairo imports. If packages are needed, `/etc/os-release`
(`/usr/lib/os-release` fallback) selects `apt-get` with `python3-gi python3-gi-cairo
gir1.2-glib-2.0 gir1.2-gtk-4.0` for Ubuntu/Debian, or `dnf` with
`python3-gobject gtk4` for Fedora/RHEL derivatives. `ID` takes precedence
over `ID_LIKE`. Other distributions may pass a working-binding check but do
not receive a guessed package installation. `--check` never installs packages;
package command failure is nonzero and actionable. Help is dependency-free.

The application installer also uses prerequisite check-only mode for
`--destdir` staging, so staging cannot install host packages. See
[installation and development command selection](installation.md) for the
staging boundary, destination checks, and user-launcher policy.

References: [PyGObject installation guidance](https://pygobject.gnome.org/getting_started.html)
and [Ubuntu's python3-gi package](https://packages.ubuntu.com/questing/python3-gi).
The `burnbag` terminal command needs Gio/GLib. The optional desktop history viewer requires GTK 4.6+ and PyGObject with Cairo integration; it renders its chart with GTK/Cairo drawing.

The initial lid observation uses `org.freedesktop.DBus.Properties.Get` on the
UPower object; `Get` is not a method of `org.freedesktop.UPower`. An already
closed lid must arm the requested countdown before entering the event loop.

Validation uses real distribution imports, non-mutating service and sysfs
observations, native tests, and isolated installer fixtures. Physical lid,
visible backlight, and suspend/resume checks are separately recorded in
the project's human-request queue.
