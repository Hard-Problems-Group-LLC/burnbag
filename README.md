# burnbag

**Clamshell control, continuous power history, historical graphs, and sleep diagnostics for Linux laptops.**

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
* **Battery Depletion History & Statistics:** An optional system or user service collects available power measurements every five seconds. Without an accessible service, operational runs record to private user SQLite history. Up to two batteries feed a full-terminal-width, 25-row depletion chart plus quantization-aware trend and gauge-rate-variability statistics without changing charging or power-supply state.

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

Install prerequisites, the terminal command, GTK viewer/controller, and manual pages under `/usr/local`:

```bash
./install.sh
```

The installer requests `sudo` only when package or system-file installation requires it. Use `./install.sh --check` for a read-only readiness check. `--destdir /absolute/staging/root` stages files without installing host packages, using sudo, or updating the host manual index. Paths containing `..`, escaping staging symlinks, and directory/symlink file targets are rejected. Use `./install.sh --help` for all options.

`sudo ./install.sh` is also supported for standard system installation. It validates installed executable paths without requiring `/usr/local/bin` on sudo's restricted `PATH`. The operator home defaults to the validated sudo caller's account home; `--user-home` overrides it. The installer does not change root's PATH or claim to verify your shell's lookup. Afterward, in your normal shell, run `hash -r` and `command -v burnbag burnbag-viewer burnbag-viewerctl`; ensure the installed bin directory precedes competing commands. Run dev and user-service installs without sudo.

For a repository-local development install, run:

```bash
./install.sh --mode dev
command -v burnbag
```

`--mode dev` selects this checkout for `burnbag`, `burnbag-viewer`, `burnbag-viewerctl`, and the selected system or user service. It publishes managed user launchers under `~/.local/bin/` and verifies command lookup, without a second selection prompt. The user bin directory must precede competing commands on `PATH`; run `hash -r` in shells that cached an older path.

Omitting `--mode dev` installs complete copies and selects those installed commands. Standard mode verifies the installed files, retires managed dev launchers, and updates the selected service. Non-root invocations also verify inherited command lookup. Both modes behave the same in interactive and unattended use:

```bash
./install.sh --mode dev  # Commands and service use this checkout
./install.sh             # Commands and service use installed copies
```

`--mode` is authoritative. The obsolete `BURNBAG_DEV_LAUNCHER_MODE` is ignored with a diagnostic; legacy `--dev-command` values are accepted only when they agree with the mode (`local` for dev, `system` for standard). Conflicting values and `prompt` are rejected. Non-root PATH conflicts cause an actionable failure; root standard installs preserve unmanaged launchers with a warning to check user-shell lookup. Dev `--force` explicitly permits replacing an unmanaged user launcher. Use `--user-home /absolute/operator/home` when automation supplies an isolated assistant `HOME`.

With `--mode dev --install-user-service`, the installer copies the manual to `<user-home>/.local/share/man/man1/burnbag.1`. Rerun the installer after documentation changes to refresh that installed copy. The repository-local `.local/share/man/man1/burnbag.1` symlink continues to follow the checkout.

---

## Graphical history viewer

`burnbag-viewer` opens the complete available system/user SQLite history in graph and paged-table tabs. Use `burnbag-viewer --last '5 hours'` for an initial viewport; add `--only` to keep queries, search, and navigation within that interval. `--only` requires `--last` or ISO `--from`/`--to` endpoints. Without `--only`, zoom/pan can leave the initial range. Months and years use the same local calendar subtraction and month-end adjustment as terminal graphs.

**Fields...** opens separate Graph and Table pages with two columns of checkboxes. OK saves and applies both selections; Cancel, Escape and closing the dialog discard edits. Multiple graph fields have separate labeled scales; Date and Time always lead the table. Preferences persist in `$XDG_CONFIG_HOME/burnbag/viewer.json` (default `~/.config/burnbag/viewer.json`). The graph and table remain unchanged until OK; a failed save keeps the dialog open with an error.

The status line reports source counts; hover for database paths and failures. Graph/table double-clicks navigate between views, and F11 gives a graph-only fullscreen view. Reopen for a fresh snapshot of ongoing collection. GTK 4.6+ and system-Python Cairo integration are required (`python3-gi-cairo gir1.2-gtk-4.0` on Ubuntu/Debian). See `man burnbag-viewer` for data sources, ranges and opt-in Unix-socket automation.

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
* `--ignore-lid`: Keep a `run*` mode active when the lid opens and show detected lid transitions on the exit battery graph. Lid opening still cancels an active suspend countdown; a later closure starts a fresh countdown. Without this option, the first observed close/open cycle ends the program.
* `--do-not-touch-backlight`: Leave the screen backlight untouched. Without this opt-out, persistent `run*` modes turn every discovered backlight off three seconds after process startup and restore and verify it as on before handled exit.
* `--log-file <FILE>`: Write the mandatory synchronized running log to an explicit absolute path instead of the XDG state default. The parent must be owned by the effective user and must not be group/world writable.
* `--no-color`: Disable ANSI color in runtime messages, help, usage, and error output. Color remains automatic by default for interactive terminals.
* `--no-plot`: Suppress the 25-row battery depletion chart, lid-event markers, and suspend/hibernate blocks at exit. Battery sampling, synchronized records, battery statistics, lid-transition counts, and suspend detection and summary remain enabled.
* `-h`, `--help`: Display syntax and usage help.

---

## Terminal Output

`burnbag` automatically adds color and visual hierarchy when the relevant standard-output or standard-error stream is an interactive terminal. It emits plain text when a stream is redirected, when `TERM=dumb`, when the `NO_COLOR` environment variable is present, or when `--no-color` is specified. Text labels such as `[INFO]`, `[OK]`, `[WARNING]`, and `[FATAL ERROR]` remain present in every mode, so color is never the only indication of status.

The battery plot and statistical summary follow the same capability policy. Interactive output uses yellow for the first battery, blue for the second, and green where their plot lines overlap; gauge-rate variability and per-minute statistics use magenta. Plain output uses `1`, `2`, and `X` in the plot and retains statistic labels and units, so every meaning remains available with `--no-color` or redirected output.

Running `burnbag` without a mode prints a concise quick-start guide to standard error and exits with status 2. `burnbag --help`, the zero-argument guide, and command-line validation run before PyGObject is loaded, so they remain available even when runtime prerequisites are not yet installed.

---

## Battery Monitoring, Exit Plot & Statistics

Burnbag discovers present entries of type `Battery` under `/sys/class/power_supply` in lexical kernel-name order and monitors up to two independently. The collector samples every five seconds; operational runs consume actual available observations through handled teardown. Very short runs may end before the first observation becomes available. Percentage ordering and rate calculations use suspend-inclusive Linux `CLOCK_BOOTTIME`; local wall clock is presentation-only. Systems without an installed battery continue normally and omit battery output. Native `capacity` percentages are preferred; drivers without them use matching `energy_now/energy_full` or `charge_now/charge_full` readings, rounded to whole percentages. The selected source is identified and logged; invalid readings remain gaps.

Every sampling cycle is recorded in SQLite using the selected batching policy. Operational JSONL records retain immediate durability. A battery discovery or read error is reported as an operational deviation and selects nonzero exit status, but it cannot prevent backlight restoration, inhibitor release, or power-profile restoration. If more than two eligible batteries are exposed, burnbag explicitly identifies the first two selected for monitoring and warns about the unplotted devices.

At handled exit, burnbag draws exactly 25 data rows across the current standard-output terminal width, with a 20-column minimum and an 80-column fallback when width is unavailable. The Y axis spans only the minimum through maximum battery percentages actually observed. Its top always labels the maximum and its bottom always labels the minimum, even when both percentages are equal; constant data remains vertically centered. Each row has at most one observed percentage label.

The X axis uses suspend-inclusive elapsed time and covers the whole run from application entry through the final post-recovery, pre-report observation. Startup and recovery remain visible even when battery readings cover less time; unsampled edges stay blank. Both boundaries always show the actual local wall-clock `HH:mm` of the coverage endpoints. Both endpoint labels are reserved before interior callouts, even when the displayed times are equal. If the entire plotted timeline has one elapsed value, its true endpoint labels repeat without inventing a duration and its points remain at the left. Boundary ticks align with the axis edges; interior ticks mark actual elapsed-time positions, and callouts leave at least two blank columns between labels. Missing readings remain gaps instead of being interpolated. `--no-plot` suppresses only this graph.

With `--ignore-lid`, vertical markers behind the battery curves show detected closes in magenta and opens in yellow. Battery glyphs and series colors remain visible at intersections. A marker header uses `C=close`, `O=open`, and `B=both`; plain vertical lines use `|=close`, `:=open`, and `!=both`. If closes and opens share a column, the `!` marker alternates magenta/yellow in colored output. The chart still has 25 data rows. Shutdown reports separate detected close/open counts, including zero; these totals remain exact even when several events share a column. The initial lid snapshot and duplicate same-state notifications do not count as transitions. `--no-plot` preserves counts and event logging; without valid battery observations there is no graph, but the counts remain available.

Actual sleep regions appear in every operational mode as full-height blocks: white `S` on red for suspend, green `H` on magenta for verified hibernation. Unverified sleep mode retains `S` with an explicit qualification. Plain output uses `S`/`H`. Each block covers all 25 data rows and takes precedence over battery curves and lid lines; axis labels and the separate lid header remain visible. If different kinds share a screen column, their glyphs and colors alternate down its rows. The shutdown summary reports detected suspended time, mode counts, and approximate boundaries. `--no-plot` keeps detection, summary, and logs; without valid battery observations there is no chart, but the summary remains available. Black `0` on dark gray is reserved for future powered-off regions; current runs do not detect or generate them.

A read-only observer samples Linux `CLOCK_BOOTTIME` and `CLOCK_MONOTONIC` approximately once per second, independently of the event loop, from application entry through the final snapshot after recovery. Growth in their difference verifies suspended time, including during setup and teardown. Clock detection needs no journal access, extra package, or elevated privileges and never triggers sleep. A one-millisecond detection floor and clock-read uncertainty filter noise while cumulative accounting retains smaller changes. Boundaries are inferred within the bounding observations and qualified by uncertainty; scheduling delays widen that uncertainty, and multiple sleeps between observations can merge into one region. Clock or observer failure is reported as incomplete coverage, never as verified absence of sleep. See [the detection contract and primary clock reference](docs/specifications/power-lifecycle.md#actual-suspend-observation).

When clock-confirmed sleep intervals exist, an optional read-only journal query can verify suspend or hibernate from an unambiguous successful systemd sleep operation in the same observation window. The query is limited to three seconds, 2 MiB, and 4,096 records. Failed requests, compound-mode labels alone, missing access, and ambiguous evidence leave the mode unverified while preserving measured sleep and clock coverage. Classification never requests sleep or guesses hibernation from intent. A final paired-clock read includes time spent querying; additional sleep remains mode-unverified without repeating the query. See [mode classification](docs/specifications/power-lifecycle.md#sleep-mode-classification).

Below the graph, or by itself under `--no-plot`, burnbag prints one to three lines per battery. It reports endpoints, net percentage-point change, elapsed span, whole-run least-squares gauge trend, fit and coverage, and—when enough whole-percentage transitions exist—`gauge depletion-rate variability σ` in percentage points per hour. It also shows signed average reported-gauge change per minute and its nonnegative standard deviation in `pp/min`; falling SoC is negative and rising SoC is positive. These per-minute values are conversions of the same duration-weighted transition-rate distribution, not raw five-second derivatives or an independent physical measurement. The variability describes how uneven the reported depletion velocity was; it is not acceleration, watts, instantaneous load, or a claim of zero draw when the integer gauge stays flat. Missing readings, long intervals, and known charge-status changes break local-rate continuity, and short, flat, mixed, or gapped histories are explicitly qualified with `n/a` where necessary.

`SIGKILL`, sudden power loss, and equivalent unhandled exits cannot take a final reading or render a chart. Samples synchronized before termination remain available in the running log.

---

Ctrl-C, SIGTERM, SIGHUP, a completed lid cycle, and handled errors all attempt the same final chart and summary once battery monitoring has begun, including with `--ignore-lid`. A broken stdout falls back to stderr when possible; output failure still selects nonzero status and cannot bypass restoration. Graph and statistics rendering are independent, so failure in one does not suppress the other.

## Durable Running Log

Every accepted operational invocation must establish its running log before PyGObject is loaded or host state is changed. The default path is `$XDG_STATE_HOME/burnbag/burnbag.log`, or `$HOME/.local/state/burnbag/burnbag.log` when `XDG_STATE_HOME` is unset. `--log-file /absolute/path` selects another file; there is deliberately no no-log option.

The log is UTF-8 JSON Lines. Records include UTC and monotonic time, a session UUID, sequence number, process and user IDs, selected mode, stable event code, severity, message, and structured details. Battery discovery and operational summaries are recorded alongside the power lifecycle; periodic samples are stored in SQLite; the final summary includes versioned, unit-bearing derived statistics, signed per-minute average and standard deviation fields, and explicit validity reasons. `session_start` is synchronized before runtime initialization. A handled `session_end` is synchronized after backlight restoration, inhibitor release, power-profile restoration, and final reporting attempts, including observed output failures. If a process or the machine dies before handled teardown, the missing `session_end` remains useful evidence instead of being fabricated later.

Each actual lid property transition is logged with its local wall-clock observation time, `CLOCK_BOOTTIME` elapsed time, and cumulative close/open counts. Lid events and battery samples share the same process-start elapsed origin. The final state includes `lid_close_count` and `lid_open_count`; individual transition records retain the history without copying an unbounded event array into the final record.

Suspend observations are finalized after recovery. Separate `suspend_interval` records preserve measured duration, estimated boundaries, boottime/monotonic observation brackets, uncertainty, sleep kind, and classification source; `suspend_monitor_summary` records total suspended time, interval and sleep-kind counts, mode-classification status, coverage, and detector limitations or errors. Final state includes that bounded summary as `suspend_monitor`, without embedding interval history. These records remain enabled with `--no-plot`; an unhandled exit cannot finalize them.

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

## Continuous history and services

The default installer installs, enables, and starts a **system service** running as the non-login `burnbag:burnbag` account. `./install.sh --install-user-service` selects a user service instead; it follows login sessions and does not enable lingering. Only one background collector can run per machine. Upgrades preserve intentionally stopped or disabled service state.

Plain `./install.sh --mode dev` makes both the commands and system daemon follow this checkout. The system service sees it through a private read-only directory bind mount; it retains its burnbag account and home-directory isolation. A dev user service executes the checkout directly. Restart a running collector after code edits; no application recopy is needed. `--check` is read-only; `--destdir` stages files without changing host accounts or services. `./install.sh --install-user-service --prefix "$HOME/.local"` installs the standard executable and user service under user-owned paths.

System telemetry is `/var/lib/burnbag/history.sqlite3`, readable by local accounts. User telemetry is `$XDG_STATE_HOME/burnbag/history.sqlite3` or `$HOME/.local/state/burnbag/history.sqlite3`, private to that account. The collector records available battery, charger, CPU, thermal, backlight, lid and profile information. Hardware capabilities determine which measurements exist. It never wakes the machine to sample.

Samples are collected every five seconds and committed after **60 seconds or 64 KiB**, whichever comes first. Ordinary events commit within five seconds; lifecycle transitions and critical conditions request immediate commits; the kernel battery capacity level Critical makes its sample urgent. Abrupt failure can lose approximately the last minute of buffered measurements when storage is healthy. **`--prudent-writes` commits every update**: `burnbag run --ignore-lid --prudent-writes` temporarily requests this from the serving collector. Multiple requesting runs cannot cancel each other's prudent mode.

The service is optional. Without accessible continuous recording, burnbag prints a prominent warning at the beginning and end of output, including help and usage errors, and operational runs record locally. An unhealthy service is diagnosed separately. Another user's private collector does not expose their history; the current run records locally. Existing JSONL operational diagnostics still synchronize mutation intent, outcomes, errors and session boundaries.

| Command | Effect |
| --- | --- |
| `burnbag --status-service` | Report installation, activation and collector health. |
| `burnbag --start-service` / `--stop-service` | Start or stop the selected service now. |
| `burnbag --enable-service` / `--disable-service` | Enable or disable future automatic activation. |
| `burnbag --start-user-service` / `--start-system-service` | Select a scope explicitly; all five actions support both spellings. |

Unqualified management selects the active applicable service or sole installed scope. Ambiguous changes require an explicit scope. Service startup refuses conflicting ownership. Management uses existing systemd authorization; it does not control another user's service.

### Historical graphs

`burnbag --graph --from 2026-09-14T12:00:00-07:00 --to 2026-09-14T15:00:00-07:00` renders the battery graph, summary, lid markers and verified sleep regions for that interval. `burnbag --graph` selects the last 24 hours; `--to` defaults to now and omitted `--from` is 24 hours before the selected end. `--no-plot` retains the historical summary. ISO times accept offsets or Z; local times are accepted only when unambiguous and existent.

`burnbag --graph --last 5h` selects the interval from five hours ago to now. Unit names and aliases are case-insensitive: `5H`, `"5 h"`, `"5 H"`, `"5 hours"`, `"five hours"`, `5:00:00` and `05:00:00` all select the same duration. **`5:00` means five minutes**: two clock fields are minutes:seconds; three are hours:minutes:seconds. Quote arguments containing spaces.

Durations accept decimal quantities (`1.5h`), English integers (`"twenty-one minutes"`) and compounds (`1h30m` or `"one hour and thirty minutes"`). Supported units extend from seconds through minutes, hours, days, weeks, months, years, decades, centuries and millennia; `millenia` is also accepted. `m` always means minutes; use `mo` for months. Months and larger units subtract calendar months, preserving local time and clamping to the last day when needed: one month before March 31 is February 28 (29 in a leap year). Their combined quantity must equal whole months; `1.5 years` is 18 months, while `1.5 months` is invalid. Calendar units are combined and subtracted first, then smaller units as elapsed time; days are 24 hours and weeks are seven days. `--last` requires `--graph` and cannot be combined with `--from` or `--to`. Durations must be positive and contain units or clock fields. Unsupported words, signed values, invalid clock fields, ambiguous or nonexistent calendar targets at daylight-saving transitions, and ranges outside years 1 through 9999 fail with a usage error. Use explicit `--from`/`--to` offsets when a calendar target is ambiguous or nonexistent.

See the [duration range contract](docs/specifications/duration-ranges.md) for unit aliases and exact duration semantics.

Queries read both existing system and current-user databases and merge without changing either. Duplicate identities or conflicting collection coverage warn and prefer system observations; distinct events at the same time remain distinct. Missing, damaged or unreadable sources produce explicit partial-history warnings. Long queries retain representatives spanning the full interval with a resolution warning. Statistics on reduced queries describe those retained observations. If only lid or sleep events exist, an event timeline retains them with an unavailable battery scale labeled n/a. Calendar time forms the historical X axis; unobserved gaps stay blank and do not establish power-off. Black `0` on dark gray remains reserved. Queries touching the present request a bounded durable flush when possible.

### Uninstall

`./uninstall.sh --system-service` or `./uninstall.sh --user-service` stops and disables that installation and removes only managed files. Omit the scope only when it is unambiguous. History, configuration and service accounts are retained by default; **`--purge-data` explicitly removes the selected history**. `--prefix`, `--destdir`, `--user-home` and `--check` support matching installation locations and read-only checks. If both standard and dev user installations exist, select `--mode standard` or `--mode dev`. Finish foreground runs before purging user history. Shared artifacts remain while another installation references them. Dependencies and other users' files are preserved.

See the [continuous history contract](docs/specifications/continuous-history.md) and [verification guide](docs/testing.md) for evidence limits and live service checks.
