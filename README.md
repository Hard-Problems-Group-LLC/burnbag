# burnbag

**Ephemeral clamshell mode, backlight control, power profiles, and sleep inhibition for Linux laptops.**

`burnbag` is a desktop-agnostic, ephemeral D-Bus control utility for Fedora and Red Hat Enterprise Linux family systems running GNOME or standard systemd/freedesktop stacks. It allows a laptop (such as a ThinkPad T480) to continue operating with its lid closed—whether docked on a desk or thrown into a backpack—while managing performance profiles and enforcing optional safety countdowns.

---

## Why "burnbag"?

In intelligence and government work, a burn bag is where classified documents go for destruction. In systems engineering, it is what your backpack turns into when you throw a running laptop compiling code inside with zero airflow. `burnbag` gives you explicit control over your thermals and sleep timers so you don't cook your hardware.

---

## Architecture & Safety Guarantees

Unlike traditional lid-close scripts that permanently mutate `/etc/systemd/logind.conf` or set permanent `gsettings` overrides, `burnbag` uses **ephemeral D-Bus inhibitor file descriptors** (`org.freedesktop.login1.Manager.Inhibit`).

* **Crash & Kill Immune Inhibitors:** Holding the returned Unix file descriptor open maintains the sleep/lid prohibition. If `burnbag` terminates normally, crashes, or is killed (`SIGINT`, `SIGTERM`, `SIGKILL`), the kernel closes the file descriptors, signaling `systemd-logind` to immediately drop the inhibitor locks and restore standard OS sleep behavior.
* **Default Backlight Control:** Persistent `run*` modes record every kernel screen-backlight device, turn the backlight off three seconds after process startup, verify it is off, and restore and verify a nonzero brightness before every handled exit. `--do-not-touch-backlight` explicitly opts out.
* **Validated Display Session:** Backlight control prefers the process's active local logind session. Launchers outside direct PID accounting, including tmux and user-service scopes, fall back through an inherited session ID to the operator's primary graphical session. Every candidate must match the effective UID, be active, and be local.
* **Explicit State Restoration:** On normal completion, handled `SIGINT`/`SIGTERM`, or a caught application error, `burnbag` restores the recorded backlight and power profile. `SIGKILL`, sudden power loss, and equivalent process destruction cannot run userspace teardown; unlike inhibitor FDs, explicit brightness and profile changes cannot be promised restoration in those cases.
* **Narrative Verification:** Prints an explicit startup narrative before touching system state, and a structured teardown report upon exit detailing whether goals were achieved and any deviations observed.

---

## Requirements

* **OS:** Fedora 44 / RHEL family distributions
* **Python:** Distribution `/usr/bin/python3` (Python 3.9+)
* **System Libraries:** `python3-gobject` (`PyGObject`)
* **D-Bus Services:** `systemd-logind`, `power-profiles-daemon`, `UPower`

Install or verify the RPM-provided Python binding from the checkout:

```bash
./scripts/install_prerequisites.sh
./scripts/install_prerequisites.sh --check
```

The PyPI package named `gobject` is unrelated and does not provide the `gi` module used by burnbag.

---

## Installation

Install prerequisites, the executable, and the manual page under `/usr/local`:

```bash
./install.sh
```

The installer requests `sudo` only when package or system-file installation requires it. Use `./install.sh --help` for staging and prefix options.

For a repository-local development install, run:

```bash
./install.sh --mode dev
command -v burnbag
```

In an interactive terminal, dev mode reports any competing `burnbag` command and asks whether bare invocations should prefer this checkout. If accepted, it installs a managed launcher at `~/.local/bin/burnbag` and verifies that command lookup selects it. The user bin directory must already precede the installed command on `PATH`; the installer cannot change its parent shell's environment.

Non-interactive dev installs leave command resolution unchanged unless policy is explicit:

```bash
./install.sh --mode dev --dev-command local
BURNBAG_DEV_LAUNCHER_MODE=local ./install.sh --mode dev
```

Use `--dev-command system` to remove burnbag's managed user launcher and restore the other `PATH` result. Dev mode refuses to replace an unmanaged user launcher unless `--force` is explicit. When an automation environment supplies an isolated assistant `HOME`, pass `--user-home /absolute/operator/home`.

---

## Modes & Syntax

```text
burnbag <MODE> [OPTIONS]
```

### Operational Modes

| Mode | Description |
|---|---|
| `run` | Inhibit lid-close suspend; maintain currently active power profile. |
| `run-cool` | Inhibit lid-close suspend; switch to `power-saver` profile. |
| `run-balanced` | Inhibit lid-close suspend; switch to `balanced` profile. |
| `run-hot` | Inhibit lid-close suspend; switch to `performance` profile. |
| `suspend` | Immediately trigger a one-shot system suspend. |
| `hibernate` | Immediately trigger a one-shot system hibernate (requires disk swap). |
| `normal` | Clear active overrides and restore system defaults (`balanced` profile). |

### Options

* `--suspend-after-minutes <MIN>`: Unconditionally suspend after `MIN` minutes of continuous lid closure. If the lid is opened before the timer expires, the timer is cancelled.
* `--no-inhibit-auto-suspend`: Allow standard OS background idle timers to suspend the system normally while lid-switch sleep remains blocked.
* `--ignore-lid`: Keep a `run*` mode active when the lid opens. Lid opening still cancels an active suspend countdown; a later closure starts a fresh countdown. Without this option, the first observed close/open cycle ends the program.
* `--do-not-touch-backlight`: Leave the screen backlight untouched. Without this opt-out, persistent `run*` modes turn every discovered backlight off three seconds after process startup and restore and verify it as on before handled exit.
* `-h`, `--help`: Display syntax and usage help.

---

## Usage Examples

**1. Run at maximum performance inside a bag with a 20-minute thermal/battery safety fuse:**
```bash
burnbag run-hot --suspend-after-minutes 20
```

**2. Run cool while listening to audiobooks or compiling background tasks with the lid closed:**
```bash
burnbag run-cool
```

**3. Keep running with lid closed, but allow standard GNOME background idle timeout to sleep the machine:**
```bash
burnbag run --no-inhibit-auto-suspend
```

**4. Immediately restore normal system power and sleep behavior:**
```bash
burnbag normal
```

**5. Stay active across repeated lid close/open cycles until interrupted or a timeout expires:**
```bash
burnbag run-cool --ignore-lid --suspend-after-minutes 20
```

**6. Keep the screen backlight under desktop control instead of burnbag control:**
```bash
burnbag run-cool --do-not-touch-backlight
```
