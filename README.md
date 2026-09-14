# burnbag

**Ephemeral clamshell mode, battery monitoring, backlight control, power profiles, and sleep inhibition for Linux laptops.**

`burnbag` is a desktop-agnostic, ephemeral D-Bus control utility for Ubuntu/Debian and Fedora/Red Hat Enterprise Linux family systems running GNOME or standard systemd/freedesktop stacks. It allows a laptop (such as a ThinkPad T480) to continue operating with its lid closed—whether docked on a desk or thrown into a backpack—while managing performance profiles and enforcing optional safety countdowns.

---

## Why "burnbag"?

In intelligence and government work, a burn bag is where classified documents go for destruction. In systems engineering, it is what your backpack turns into when you throw a running laptop compiling code inside with zero airflow. `burnbag` controls power profiles and optional sleep countdowns. A countdown measures continuous lid-closed time; it does not measure temperature or establish a safe temperature limit.

---

## Architecture and recovery

Unlike traditional lid-close scripts that permanently mutate `/etc/systemd/logind.conf` or set permanent `gsettings` overrides, `burnbag` uses **ephemeral D-Bus inhibitor file descriptors** (`org.freedesktop.login1.Manager.Inhibit`).

* **Process-owned inhibitors:** Holding the returned Unix file descriptor open maintains the sleep/lid prohibition. If `burnbag` terminates normally, crashes, or is killed (`SIGINT`, `SIGTERM`, `SIGKILL`), the kernel closes the file descriptors, signaling `systemd-logind` to drop this process's inhibitor locks. Other inhibitors and OS policy still apply.
* **Default Backlight Control:** Persistent `run*` modes record every kernel screen-backlight device, turn the backlight off three seconds after process startup, verify it is off, and restore and verify a nonzero brightness before every handled exit. `--do-not-touch-backlight` explicitly opts out.
* **Validated Display Session:** Backlight control prefers the process's active local logind session. Launchers outside direct PID accounting, including tmux and user-service scopes, fall back through an inherited session ID to the operator's primary graphical session. Every candidate must match the effective UID, be active, and be local.
* **Explicit State Restoration:** On normal completion, handled `SIGINT`/`SIGTERM`/`SIGHUP`, or a caught application error, `burnbag` attempts and verifies restoration of the backlight and any temporary power-profile change. Unverified restoration returns nonzero. `SIGKILL`, sudden power loss, and equivalent process destruction cannot run userspace teardown; unlike inhibitor FDs, explicit brightness and profile changes cannot be promised restoration in those cases.
* **Narrative Verification:** Prints an explicit startup narrative before touching system state, and a structured teardown report upon exit detailing whether goals were achieved and any deviations observed.
* **Adaptive Terminal Presentation:** Interactive terminals receive ANSI color and stronger visual hierarchy in runtime messages, help, usage tips, and errors. Redirected streams and explicit plain-output controls remain free of terminal escapes, and status meaning is always retained in text labels.
* **Durable Running Log:** Every accepted operational session appends structured JSON Lines under the invoking user's XDG state directory. Each record is serialized across concurrent processes and synchronized with `fsync`; mutation intent is durable before safety-relevant host changes, and handled teardown is recorded before exit.
* **Battery Depletion History & Statistics:** Burnbag reads up to two installed Linux power-supply batteries before host mutation, every fifteen seconds during persistent modes, and once more at handled exit. The synchronized samples feed a full-terminal-width, 25-row depletion chart plus quantization-aware trend and gauge-rate-variability statistics without changing charging or power-supply state.

---

## Requirements

* **OS:** Ubuntu/Debian or Fedora/RHEL family Linux with systemd-logind; x86-64 and ARM64
* **Python:** Distribution `/usr/bin/python3` (Python 3.9+)
* **System Libraries:** PyGObject: `python3-gi gir1.2-glib-2.0` on Ubuntu/Debian; `python3-gobject` on Fedora/RHEL
* **D-Bus Services:** `systemd-logind`; `UPower` for lid-driven behavior; `power-profiles-daemon` for requested profile changes.

Install or verify the distribution-provided Python binding from the checkout:

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

The installer requests `sudo` only when package or system-file installation requires it. Use `./install.sh --check` for a read-only readiness check. `--destdir /absolute/staging/root` stages files without installing host packages, using sudo, or updating the host manual index. Paths containing `..`, escaping staging symlinks, and directory/symlink file targets are rejected. Use `./install.sh --help` for all options.

For a repository-local development install, run:

```bash
./install.sh --mode dev
command -v burnbag
```

In an interactive terminal, dev mode reports any competing `burnbag` command and asks whether bare invocations should prefer this checkout. If accepted, it installs a managed launcher at `~/.local/bin/burnbag` and verifies that command lookup selects it. The user bin directory must already precede the installed command on `PATH`; the installer cannot change its parent shell's environment.

Non-interactive dev installs leave existing launchers and command resolution unchanged unless policy is explicit. Declining the interactive prompt or reaching end-of-input also preserves them:

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
| `hibernate` | Request system hibernation after checking platform support and policy. |
| `normal` | Select, verify, and retain the `balanced` profile. Other running processes retain their own inhibitors. |

Profiles are checked before a requested change. If `performance` is not advertised, `run-hot` fails clearly; use `powerprofilesctl list` to inspect available profiles. Plain `run` can leave profiles untouched when the profile daemon is unavailable. Lid-dependent runs require valid lid telemetry; `--ignore-lid` without a suspend countdown can operate without it. Suspend and hibernate requests check the system-reported capability first.

### Options

* `--suspend-after-minutes <MIN>`: Request suspend after `MIN` minutes of continuous lid closure. If the lid is opened before the timer expires, the timer is cancelled.
* `--no-inhibit-auto-suspend`: Allow standard OS background idle timers to suspend the system normally while lid-switch sleep remains blocked.
* `--ignore-lid`: Keep a `run*` mode active when the lid opens. Lid opening still cancels an active suspend countdown; a later closure starts a fresh countdown. Without this option, the first observed close/open cycle ends the program.
* `--do-not-touch-backlight`: Leave the screen backlight untouched. Without this opt-out, persistent `run*` modes turn every discovered backlight off three seconds after process startup and restore and verify it as on before handled exit.
* `--log-file <FILE>`: Write the mandatory synchronized running log to an explicit absolute path instead of the XDG state default. The parent must be owned by the effective user and must not be group/world writable.
* `--no-color`: Disable ANSI color in runtime messages, help, usage, and error output. Color remains automatic by default for interactive terminals.
* `--no-plot`: Suppress the 25-row battery depletion chart at exit. Discovery, fifteen-second sampling, synchronized log records, and per-battery statistics remain enabled.
* `-h`, `--help`: Display syntax and usage help.

---

## Terminal Output

`burnbag` automatically adds color and visual hierarchy when the relevant standard-output or standard-error stream is an interactive terminal. It emits plain text when a stream is redirected, when `TERM=dumb`, when the `NO_COLOR` environment variable is present, or when `--no-color` is specified. Text labels such as `[INFO]`, `[OK]`, `[WARNING]`, and `[FATAL ERROR]` remain present in every mode, so color is never the only indication of status.

The battery plot and statistical summary follow the same capability policy. Interactive output uses yellow for the first battery, blue for the second, and green where their plot lines overlap; gauge-rate variability and per-minute statistics use magenta. Plain output uses `1`, `2`, and `X` in the plot and retains statistic labels and units, so every meaning remains available with `--no-color` or redirected output.

Running `burnbag` without a mode prints a concise quick-start guide to standard error and exits with status 2. `burnbag --help`, the zero-argument guide, and command-line validation run before PyGObject is loaded, so they remain available even when runtime prerequisites are not yet installed.

---

## Battery Monitoring, Exit Plot & Statistics

Burnbag discovers present entries of type `Battery` under `/sys/class/power_supply` in lexical kernel-name order and monitors up to two independently. It takes an initial reading before operational host mutation, samples persistent `run*` modes every 15 seconds, and takes a final reading as handled teardown begins. One-shot modes receive only the initial and final readings. Percentage ordering and rate calculations use suspend-inclusive Linux `CLOCK_BOOTTIME`; local wall clock is presentation-only. Systems without an installed battery continue normally and omit battery output. Native `capacity` percentages are preferred; drivers without them use matching `energy_now/energy_full` or `charge_now/charge_full` readings, rounded to whole percentages. The selected source is identified and logged; invalid readings remain gaps.

Every sampling cycle is written to the mandatory synchronized running log. A battery discovery or read error is reported as an operational deviation and selects nonzero exit status, but it cannot prevent backlight restoration, inhibitor release, or power-profile restoration. If more than two eligible batteries are exposed, burnbag explicitly identifies the first two selected for monitoring and warns about the unplotted devices.

At handled exit, burnbag draws exactly 25 data rows across the current standard-output terminal width, with a 20-column minimum and an 80-column fallback when width is unavailable. The Y axis spans only the minimum through maximum battery percentages actually observed. Its top always labels the maximum and its bottom always labels the minimum, even when both percentages are equal; constant data remains vertically centered. Each row has at most one observed percentage label.

The X axis uses elapsed-time ordering and labels both boundaries with the actual local wall-clock `HH:mm` of the earliest and latest sample attempts, including missing readings at either edge. Both endpoint labels are reserved before interior callouts, even when the displayed times are equal. A lone sample or a history with equal elapsed times repeats its true endpoint labels without inventing a duration, while its points remain at the left. Boundary ticks align with the axis edges; interior ticks mark actual elapsed-time sample positions, and callouts leave at least two blank columns between labels. Missing readings remain gaps instead of being interpolated. `--no-plot` suppresses only this graph.

Below the graph, or by itself under `--no-plot`, burnbag prints one to three lines per battery. It reports endpoints, net percentage-point change, elapsed span, whole-run least-squares gauge trend, fit and coverage, and—when enough whole-percentage transitions exist—`gauge depletion-rate variability σ` in percentage points per hour. It also shows signed average reported-gauge change per minute and its nonnegative standard deviation in `pp/min`; falling SoC is negative and rising SoC is positive. These per-minute values are conversions of the same duration-weighted transition-rate distribution, not raw 15-second derivatives or an independent physical measurement. The variability describes how uneven the reported depletion velocity was; it is not acceleration, watts, instantaneous load, or a claim of zero draw when the integer gauge stays flat. Missing readings, long intervals, and known charge-status changes break local-rate continuity, and short, flat, mixed, or gapped histories are explicitly qualified with `n/a` where necessary.

`SIGKILL`, sudden power loss, and equivalent unhandled exits cannot take a final reading or render a chart. Samples synchronized before termination remain available in the running log.

---

Ctrl-C, SIGTERM, SIGHUP, a completed lid cycle, and handled errors all attempt the same final chart and summary once battery monitoring has begun, including with `--ignore-lid`. A broken stdout falls back to stderr when possible; output failure still selects nonzero status and cannot bypass restoration. Graph and statistics rendering are independent, so failure in one does not suppress the other.

## Durable Running Log

Every accepted operational invocation must establish its running log before PyGObject is loaded or host state is changed. The default path is `$XDG_STATE_HOME/burnbag/burnbag.log`, or `$HOME/.local/state/burnbag/burnbag.log` when `XDG_STATE_HOME` is unset. `--log-file /absolute/path` selects another file; there is deliberately no no-log option.

The log is UTF-8 JSON Lines. Records include UTC and monotonic time, a session UUID, sequence number, process and user IDs, selected mode, stable event code, severity, message, and structured details. Battery discovery and each initial, periodic, and final battery sample are recorded alongside the power lifecycle; the final summary includes versioned, unit-bearing derived statistics, signed per-minute average and standard deviation fields, and explicit validity reasons. `session_start` is synchronized before runtime initialization. A handled `session_end` is synchronized after backlight restoration, inhibitor release, power-profile restoration, and final reporting attempts, including observed output failures. If a process or the machine dies before handled teardown, the missing `session_end` remains useful evidence instead of being fabricated later.

Each complete record is appended while holding an exclusive advisory lock and is followed by `fsync` before the operation continues. The managed directory is mode `0700` and the log is mode `0600`; symlink targets, non-regular files, multiply linked files, wrong ownership, and unsafe parent permissions are rejected. Failure to open, append, lock, or synchronize the log prevents further host mutation and returns nonzero. If logging fails after state has changed, teardown still takes precedence and runs to completion.

Burnbag does not rotate, upload, truncate, or delete this file. Retention is operator-owned. An external rename-based rotation leaves an already-running process on its open inode while later sessions use the configured path.

Inspect recent records without changing them:

```bash
tail -n 20 "${XDG_STATE_HOME:-$HOME/.local/state}/burnbag/burnbag.log"
```

---

## Usage Examples

**1. Request performance mode with a 20-minute continuous-lid-closure countdown:**
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

**4. Select and retain the balanced power profile:**
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

**7. Put an automation run in a separate synchronized log:**
```bash
burnbag run-cool --log-file /absolute/path/to/automation.jsonl
```

**8. Keep battery sampling and log history but omit the exit plot:**
```bash
burnbag run-cool --no-plot
```

## Development and verification

See [the roadmap](ROADMAP.md), [behavior specifications](docs/specifications/README.md), and [automated/manual verification](docs/testing.md). Run `/usr/bin/python3 -B -m unittest discover -s tests` for the native suite. README and manual sources are in `makedocs.py`; `./makedocs.py --check` checks consistency without writing.
